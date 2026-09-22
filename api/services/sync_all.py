"""One-shot, active-Item sync with atomic consumer publication.

Plaid work is read-only with respect to PostgreSQL and finishes before the
publication transaction. Jobs and a future manual trigger can call this module
directly; neither needs to call the legacy split HTTP routes.
"""

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import plaid
from fastapi import HTTPException
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import func, select, text, update
from urllib3.exceptions import HTTPError as TransportError

from api.models import Account, Item, RawTransaction, SyncItemRun, SyncRun, SyncRuntimeState, Transaction
from api.routes.plaid import decrypt_access_token
from api.services.derivation import (
    NormalizationInputError, classify_active_transactions, normalize_item_transactions,
)
from api.services.persistence import persist_account_metadata, persist_consumer_transactions
from api.statement_semantics import lock_consumer_derivation


MAX_PAGES = 100
MAX_MUTATION_RETRIES = 2
MAX_TRANSIENT_RETRIES = 2
MAX_RUN_SECONDS = 300
REQUEST_TIMEOUT = (5, 20)


def utcnow():
    return datetime.now(timezone.utc)


def _account_snapshot(account):
    # These fields govern ownership, consumer eligibility, and Amex matching.
    return (account.account_id, account.item_id, account.name, account.official_name,
            account.type, account.subtype, account.mask, account.consumer_transactions_enabled)


@dataclass(frozen=True)
class ItemSnapshot:
    item_id: str
    user_id: str
    institution_id: str
    token: str = field(repr=False)
    cursor: str | None = field(repr=False)
    accounts: tuple = ()


@dataclass
class Buffer:
    added: list = field(default_factory=list)
    modified: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    cursor: str | None = None
    pages: int = 0
    fetched_pages: int = 0
    retries: int = 0
    metadata: list | None = None


class ItemProblem(Exception):
    def __init__(self, status, category, phase, request_id=None):
        super().__init__(category)
        self.status = status
        self.category = category
        self.phase = phase
        self.request_id = request_id
        self.retries = 0
        self.pages = 0


def _plaid_error(exc):
    try:
        body = json.loads(exc.body) if isinstance(exc.body, (str, bytes)) else {}
    except (ValueError, TypeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    code = body.get("error_code")
    request_id = _safe_request_id(body.get("request_id"))
    if code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION":
        return ItemProblem("retry", "pagination_mutation", "fetch", request_id)
    if code == "PRODUCT_NOT_READY":
        return ItemProblem("waiting", "not_ready", "fetch", request_id)
    if code in {"ITEM_LOGIN_REQUIRED", "INVALID_ACCESS_TOKEN", "ITEM_NOT_SUPPORTED"}:
        return ItemProblem("blocked", "reauthorization", "fetch", request_id)
    return ItemProblem("failed", "plaid_error", "fetch", request_id)


def _safe_request_id(value):
    return value if isinstance(value, str) and len(value) <= 100 and value.replace("-", "").isalnum() else None


def _invoke_sdk(method, request):
    response = method(request, _request_timeout=REQUEST_TIMEOUT)
    return response.to_dict() if hasattr(response, "to_dict") else response


async def _sdk_call(method, request, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ItemProblem("failed", "run_deadline", "fetch")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_invoke_sdk, method, request),
            timeout=min(remaining, REQUEST_TIMEOUT[0] + REQUEST_TIMEOUT[1] + 5),
        )
    except plaid.ApiException as exc:
        raise _plaid_error(exc) from None
    except (TimeoutError, OSError, TransportError) as exc:
        raise ItemProblem("failed", "network", "fetch") from exc


async def _fetch_pages(client, token, original_cursor, deadline):
    retries = 0
    total_pages = 0
    while True:
        buffer = Buffer(cursor=original_cursor, retries=retries)
        try:
            while True:
                if buffer.pages >= MAX_PAGES:
                    raise ItemProblem("failed", "page_limit", "fetch")
                request = {"access_token": token}
                if buffer.cursor is not None:
                    request["cursor"] = buffer.cursor
                page = await _sdk_call(client.transactions_sync, TransactionsSyncRequest(**request), deadline)
                total_pages += 1
                if not isinstance(page, dict) or not isinstance(page.get("has_more"), bool):
                    raise ItemProblem("failed", "invalid_response", "fetch")
                if page.get("transactions_update_status") == "NOT_READY":
                    raise ItemProblem("waiting", "not_ready", "fetch", _safe_request_id(page.get("request_id")))
                if not isinstance(page.get("next_cursor"), str):
                    raise ItemProblem("failed", "invalid_response", "fetch")
                for name in ("added", "modified", "removed"):
                    if not isinstance(page.get(name), list):
                        raise ItemProblem("failed", "invalid_response", "fetch")
                    getattr(buffer, name).extend(page[name])
                buffer.cursor = page["next_cursor"]
                buffer.pages += 1
                if not page.get("has_more"):
                    buffer.fetched_pages = total_pages
                    return buffer
        except ItemProblem as problem:
            if problem.category == "pagination_mutation" and retries < MAX_MUTATION_RETRIES:
                retries += 1  # Discard every page and restart from the original cursor.
                continue
            if problem.category == "network" and retries < MAX_TRANSIENT_RETRIES:
                retries += 1
                continue
            if problem.category == "pagination_mutation":
                problem.status = "failed"
            problem.retries = retries
            problem.pages = total_pages
            raise


async def _fetch_item(client, snapshot, deadline):
    try:
        token = decrypt_access_token(snapshot.token)
    except RuntimeError as exc:
        raise ItemProblem("blocked", "token_unavailable", "fetch") from exc
    buffer = await _fetch_pages(client, token, snapshot.cursor, deadline)
    known = {account[0] for account in snapshot.accounts}
    referenced = {row["account_id"] for row in buffer.added + buffer.modified
                  if isinstance(row, dict) and isinstance(row.get("account_id"), str)}
    if referenced - known:
        try:
            response = await _sdk_call(client.accounts_get, AccountsGetRequest(access_token=token), deadline)
        except ItemProblem as problem:
            raise ItemProblem(problem.status, "metadata_refresh_failed", "metadata", problem.request_id) from None
        accounts = response.get("accounts") if isinstance(response, dict) else None
        if (not isinstance(accounts, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("account_id"), str)
                or not isinstance(row.get("name"), str) or not row["name"]
                for row in accounts)):
            raise ItemProblem("blocked", "invalid_metadata", "metadata")
        # The old buffer is invalid after metadata repair, even if it looked complete.
        repaired = await _fetch_pages(client, token, snapshot.cursor, deadline)
        repaired.metadata = accounts
        repaired.retries += buffer.retries
        repaired.fetched_pages += buffer.fetched_pages
        known.update(row.get("account_id") for row in accounts if isinstance(row, dict))
        referenced = {row["account_id"] for row in repaired.added + repaired.modified
                      if isinstance(row, dict) and isinstance(row.get("account_id"), str)}
        if referenced - known:
            raise ItemProblem("blocked", "unknown_account", "metadata")
        return repaired
    return buffer


def _outcome(status, phase, category=None, buffer=None, request_id=None, retries=0, pages=0):
    return {
        "status": status, "phase": phase, "error_category": category,
        "request_id": request_id, "buffer": buffer, "retries": retries, "pages": pages,
    }


def _run_status(outcomes):
    values = [entry["status"] for entry in outcomes.values()]
    if not values:
        return "idle"
    if "success" in values:
        return "success" if all(value == "success" for value in values) else "partial"
    if all(value == "waiting" for value in values):
        return "waiting"
    if "blocked" in values:
        return "blocked"
    return "failed"


async def _record_item(db, run_id, item_id, outcome, finished_at):
    buffer = outcome.get("buffer")
    values = dict(status=outcome["status"], phase=outcome["phase"],
                  error_category=outcome.get("error_category"), request_id=outcome.get("request_id"),
                  finished_at=finished_at)
    if buffer is not None:
        values.update(pages_fetched=buffer.fetched_pages, retry_count=buffer.retries,
                      received_added=len(buffer.added), received_modified=len(buffer.modified),
                      received_removed=len(buffer.removed))
    else:
        values.update(pages_fetched=outcome.get("pages", 0), retry_count=outcome.get("retries", 0))
    if outcome["status"] == "success":
        result = outcome["result"]
        values.update(added_count=result["added_count"], modified_count=result["modified_count"],
                      removed_count=result["removed_count"],
                      skipped_disabled_count=sum(result["skipped_disabled_counts"].values()),
                      normalized_count=outcome["normalized_count"],
                      classified_count=outcome.get("classified_count", 0))
    await db.execute(update(SyncItemRun).where(
        SyncItemRun.run_id == run_id, SyncItemRun.item_id == item_id).values(**values))


async def _revalidate(db, snapshot):
    item = await db.scalar(select(Item).where(Item.item_id == snapshot.item_id)
                           .with_for_update().execution_options(populate_existing=True))
    if (item is None or item.user_id != snapshot.user_id or item.institution_id != snapshot.institution_id
            or item.status != "active"
            or item.sync_paused or item.transactions_cursor != snapshot.cursor
            or item.access_token != snapshot.token):
        raise ItemProblem("blocked", "stale_item", "publish")
    accounts = (await db.execute(select(Account).where(Account.item_id == snapshot.item_id)
                .order_by(Account.account_id).with_for_update()
                .execution_options(populate_existing=True))).scalars().all()
    if tuple(_account_snapshot(account) for account in accounts) != snapshot.accounts:
        raise ItemProblem("blocked", "stale_scope", "publish")


async def _publish_item(db, snapshot, buffer):
    await _revalidate(db, snapshot)
    if buffer.metadata is not None:
        result = await persist_account_metadata(db, snapshot.user_id, snapshot.item_id, buffer.metadata)
        if result["type_drift"]:
            raise ItemProblem("blocked", "account_type_drift", "metadata")
    # A repaired response must resolve every transaction account before cursor advance.
    known = {row[0] for row in snapshot.accounts}
    if buffer.metadata is not None:
        known.update(row["account_id"] for row in buffer.metadata)
    for transaction in buffer.added + buffer.modified:
        if (not isinstance(transaction, dict) or not isinstance(transaction.get("transaction_id"), str)
                or not isinstance(transaction.get("account_id"), str)
                or transaction["account_id"] not in known
                or not isinstance(transaction.get("date"), date)
                or transaction.get("amount") is None):
            raise ItemProblem("blocked", "invalid_transaction", "validate")
        try:
            if not Decimal(str(transaction["amount"])).is_finite():
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ItemProblem("blocked", "invalid_transaction", "validate") from exc
    for removed in buffer.removed:
        if not isinstance(removed, dict) or not isinstance(removed.get("transaction_id"), str):
            raise ItemProblem("blocked", "invalid_removal", "validate")
    result = await persist_consumer_transactions(
        db, snapshot.user_id, snapshot.item_id, snapshot.cursor,
        buffer.added, buffer.modified, buffer.removed, buffer.cursor, buffer.pages)
    try:
        normalized = await normalize_item_transactions(db, snapshot.user_id, snapshot.item_id)
    except NormalizationInputError as exc:
        raise ItemProblem("blocked", "normalization_input", "normalize") from exc
    return result, normalized["normalized_count"]


async def _finalize_failure(session_factory, run_id, outcomes, category):
    # A lost acknowledgement must never turn a committed run into a failure.
    async with session_factory.begin() as db:
        run = await db.get(SyncRun, run_id, with_for_update=True)
        if run.status != "running":
            return
        now = utcnow()
        for item_id, outcome in outcomes.items():
            if outcome["status"] in {"ready", "success"}:
                outcome = _outcome("failed", "rollback", "publication_rolled_back", outcome.get("buffer"))
            await _record_item(db, run_id, item_id, outcome, now)
        await db.execute(update(SyncItemRun).where(SyncItemRun.run_id == run_id,
                          SyncItemRun.status == "running")
                         .values(status="failed", phase="rollback", finished_at=now,
                                 error_category="publication_rolled_back"))
        run.status = "failed"
        run.error_category = category
        run.finished_at = now
        run.duration_ms = round((now - run.started_at).total_seconds() * 1000)


async def sync_all(user_id, *, trigger_source="one_shot", client=None, session_factory=None,
                   engine=None, item_ids=None):
    """Synchronize selected active Items once and return sanitized run diagnostics.

    `item_ids` narrows an explicit one-shot run; it never widens active scope.
    """
    if session_factory is None or engine is None:
        from api.db import SessionLocal, engine as default_engine
        session_factory = session_factory or SessionLocal
        engine = engine or default_engine
    if trigger_source not in {"one_shot", "manual", "jobs"}:
        raise ValueError("Unknown sync trigger")
    if item_ids is not None and not all(isinstance(value, str) for value in item_ids):
        raise ValueError("Item IDs must be strings")
    if client is None:
        from api.routes.plaid import validate_runtime_configuration
        validate_runtime_configuration()
    if os.environ.get("PLAID_ENV", "").lower() == "production" and user_id != os.environ.get("PLAID_PILOT_USER_ID"):
        raise RuntimeError("Production sync scope does not match configured pilot user")
    deadline = time.monotonic() + MAX_RUN_SECONDS
    async with engine.connect() as lock_connection:
        if os.environ.get("PLAID_ENV", "").lower() == "production":
            actual = await lock_connection.scalar(text("SELECT current_database()"))
            if actual != os.environ.get("EXPECTED_DATABASE_NAME"):
                raise RuntimeError("Production database safety check failed")
        tables = (await lock_connection.execute(text(
            "SELECT to_regclass('sync_runs'), to_regclass('sync_item_runs'), "
            "to_regclass('sync_runtime_state')"))).one()
        if any(table is None for table in tables):
            raise RuntimeError("M2 schema is missing; run the migration explicitly")
        got_lock = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
            {"key": "pft-sync:" + user_id})
        await lock_connection.commit()  # Session-level advisory lock remains held.
        if not got_lock:
            return {"status": "busy", "run_id": None, "items": {}}
        try:
            async with session_factory.begin() as db:
                # Only a new lock owner can reconcile a pre-commit crash.
                interrupted_at = utcnow()
                interrupted_ids = select(SyncRun.run_id).where(
                    SyncRun.user_id == user_id, SyncRun.status == "running")
                await db.execute(update(SyncItemRun).where(
                    SyncItemRun.run_id.in_(interrupted_ids), SyncItemRun.status == "running"
                ).values(status="interrupted", phase="rollback", finished_at=interrupted_at,
                         error_category="interrupted"))
                await db.execute(update(SyncRun).where(SyncRun.user_id == user_id,
                    SyncRun.status == "running").values(status="interrupted", finished_at=interrupted_at,
                                                          error_category="interrupted"))
                query = select(Item).where(Item.user_id == user_id, Item.status == "active",
                                           Item.sync_paused.is_(False)).order_by(Item.item_id)
                if item_ids is not None:
                    query = query.where(Item.item_id.in_(item_ids))
                items = (await db.execute(query)).scalars().all()
                snapshots = {}
                initial = {}
                for item in items:
                    accounts = (await db.execute(select(Account).where(Account.item_id == item.item_id)
                                .order_by(Account.account_id))).scalars().all()
                    account_state = tuple(_account_snapshot(account) for account in accounts)
                    snapshots[item.item_id] = ItemSnapshot(item.item_id, user_id, item.institution_id, item.access_token,
                                                            item.transactions_cursor, account_state)
                    if not accounts:
                        initial[item.item_id] = _outcome("blocked", "select", "no_accounts")
                    elif item.transactions_cursor is None and await db.scalar(select(func.count()).select_from(
                            RawTransaction).where(RawTransaction.item_id == item.item_id)):
                        initial[item.item_id] = _outcome("blocked", "select", "missing_cursor")
            if not snapshots:
                return {"status": "idle", "run_id": None, "items": {}}
            run_id = str(uuid.uuid4())
            started = utcnow()
            async with session_factory.begin() as db:
                db.add(SyncRun(run_id=run_id, user_id=user_id, trigger_source=trigger_source,
                               started_at=started, status="running"))
                await db.flush()
                for item_id in snapshots:
                    db.add(SyncItemRun(run_id=run_id, item_id=item_id, started_at=started,
                                       status="running", phase="select"))
                    await db.execute(update(Item).where(Item.item_id == item_id)
                                     .values(last_sync_attempt_at=started))
            outcomes = dict(initial)
            try:
                if client is None and len(initial) < len(snapshots):
                    from api.routes.plaid import get_client
                    client = get_client()
                for item_id, snapshot in snapshots.items():
                    if item_id in outcomes:
                        continue
                    try:
                        buffer = await _fetch_item(client, snapshot, deadline)
                        outcomes[item_id] = _outcome("ready", "fetch", buffer=buffer)
                    except ItemProblem as problem:
                        outcomes[item_id] = _outcome(problem.status, problem.phase, problem.category,
                                                     request_id=problem.request_id,
                                                     retries=problem.retries, pages=problem.pages)
            except Exception:
                await _finalize_failure(session_factory, run_id, outcomes, "fetch_failed")
                raise
            accepted = 0
            classification_ms = None
            try:
                async with asyncio.timeout_at(deadline), session_factory.begin() as db:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Sync run deadline exceeded")
                    await db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"),
                                     {"timeout": str(max(1, round((deadline - time.monotonic()) * 1000)))})
                    await lock_consumer_derivation(db, user_id)
                    for item_id, snapshot in snapshots.items():
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Sync run deadline exceeded")
                        outcome = outcomes[item_id]
                        if outcome["status"] != "ready":
                            continue
                        buffer = outcome["buffer"]
                        try:
                            async with db.begin_nested():
                                result, normalized_count = await _publish_item(db, snapshot, buffer)
                        except ItemProblem as problem:
                            outcomes[item_id] = _outcome(problem.status, problem.phase, problem.category,
                                                         buffer, problem.request_id)
                        except HTTPException as exc:
                            if exc.status_code not in {404, 409, 422}:
                                raise
                            outcomes[item_id] = _outcome("blocked", "persist", "item_conflict", buffer)
                        else:
                            outcome.update(status="success", phase="published", result=result,
                                           normalized_count=normalized_count)
                            accepted += 1
                    await lock_connection.scalar(text("SELECT 1"))  # Lost owner means no publication.
                    if accepted:
                        classify_start = time.monotonic()
                        classification = await classify_active_transactions(db, user_id)
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Sync run deadline exceeded")
                        classification_ms = round((time.monotonic() - classify_start) * 1000)
                        for item_id, outcome in outcomes.items():
                            if outcome["status"] == "success":
                                outcome["classified_count"] = await db.scalar(
                                    select(func.count()).select_from(Transaction)
                                    .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
                                    .join(Account, Account.account_id == Transaction.account_id)
                                    .where(RawTransaction.item_id == item_id,
                                           RawTransaction.is_removed.is_(False),
                                           Account.consumer_transactions_enabled.is_(True),
                                           Transaction.transaction_type.is_not(None)))
                    now = utcnow()
                    for item_id, outcome in outcomes.items():
                        await _record_item(db, run_id, item_id, outcome, now)
                        if outcome["status"] == "success":
                            changes = outcome["result"]["changed_transaction_count"]
                            values = {"last_sync_success_at": now, "next_sync_retry_at": None}
                            if changes:
                                values["last_sync_change_at"] = now
                            await db.execute(update(Item).where(Item.item_id == item_id).values(**values))
                    status = _run_status(outcomes)
                    await db.execute(update(SyncRun).where(SyncRun.run_id == run_id).values(
                        status=status, finished_at=now,
                        duration_ms=round((now - started).total_seconds() * 1000),
                        classification_status="success" if accepted else "not_run",
                        classified_count=classification["classified_count"] if accepted else 0,
                        classification_duration_ms=classification_ms,
                        published_at=now if accepted else None))
                    if accepted:
                        state = await db.get(SyncRuntimeState, user_id, with_for_update=True)
                        if state is None:
                            state = SyncRuntimeState(user_id=user_id)
                            db.add(state)
                        state.last_published_run_id = run_id
                        state.published_at = now
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Sync run deadline exceeded")
                    await lock_connection.scalar(text("SELECT 1"))
            except Exception:
                try:
                    await lock_connection.scalar(text("SELECT 1"))
                except Exception:
                    # The next owner reconciles this running row under the sync lock.
                    raise
                await _finalize_failure(session_factory, run_id, outcomes, "publication_failed")
                raise
            return {"status": _run_status(outcomes), "run_id": run_id,
                    "published": bool(accepted),
                    "classification_duration_ms": classification_ms,
                    "items": {item_id: {"status": value["status"],
                                        "error_category": value.get("error_category")}
                              for item_id, value in outcomes.items()}}
        finally:
            # A pooled PostgreSQL connection retains session locks on check-in.
            try:
                await lock_connection.scalar(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": "pft-sync:" + user_id})
                await lock_connection.commit()
            except Exception:
                await lock_connection.invalidate()
