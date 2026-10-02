"""Institution lifecycle transitions and their whole-ledger impact.

Previews run the real transition inside the caller's transaction and roll it
back, so a preview and the transition it describes share one code path. The
transition then recomputes the same impact under the same lock and commits only
if its digest equals the digest the owner confirmed.
"""

import hashlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, update

from api.classification import effective_classification
from api.models import (Account, Item, RawTransaction, SyncItemRun, SyncRuntimeState, Transaction)
from api.services.derivation import (
    NormalizationInputError, _classification_inputs, _normalized_differs, build_classifications,
    classify_active_transactions, normalized_raw_values, validate_consumer_activation,
    validate_normalization_input,
)
from api.statement_semantics import lock_consumer_derivation

LEDGER_START, LEDGER_END = date(1900, 1, 1), date(9999, 12, 31)
ACTIVATABLE = ("pending", "deactivated")
METRICS = ("gross_spending", "refunds", "reimbursements", "card_benefits", "net_spending",
           "income", "net_savings", "unclassified_count")


class _Rollback(Exception):
    pass


def _json(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _digest(before, after):
    canonical = json.dumps({"before": before, "after": after}, sort_keys=True, default=str,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def ledger_snapshot(db, user_id):
    """Every published consumer transaction as analytics sees it, plus monthly summaries."""
    from api.routes import analytics
    if user_id != os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user"):
        raise RuntimeError("Ledger snapshot user differs from the analytics user")
    rows = await analytics._active_analytics_rows(LEDGER_START, LEDGER_END, db)
    transactions, months = {}, {}
    for row in rows:
        transaction, removed, override_type, item, account, category_override, _ = analytics._analytics_row(row)
        if removed:
            continue
        transaction_type, is_spending, is_internal_transfer = effective_classification(
            transaction, override_type)
        month = transaction.transaction_date.strftime("%Y-%m")
        transactions[transaction.transaction_id] = {
            "transaction_id": transaction.transaction_id,
            "item_id": item.item_id,
            "institution_name": item.institution_name,
            "account_name": account.name,
            "transaction_date": transaction.transaction_date.isoformat(),
            "month": month,
            "amount": format(Decimal(transaction.amount), "f"),
            "merchant_name": transaction.merchant_name,
            "description": transaction.description,
            "transaction_type": transaction_type,
            "is_spending": is_spending,
            "is_internal_transfer": is_internal_transfer,
            "category": analytics._category(transaction, category_override, override_type),
            "manual_type": override_type is not None,
        }
        months.setdefault(month, []).append(row)
    summaries = {month: _json(analytics.summarize_monthly_transactions(month_rows))
                 for month, month_rows in sorted(months.items())}
    return {"transactions": transactions, "months": summaries}


CLASSIFICATION_FIELDS = ("transaction_type", "is_spending", "is_internal_transfer", "category")


def _category_nets(summary):
    return {entry["category"]: entry["net_spending"]
            for entry in (summary or {}).get("category_net_breakdown", [])}


def ledger_diff(before, after):
    old, new = before["transactions"], after["transactions"]
    changed = []
    for ident in sorted(set(old) & set(new)):
        if any(old[ident][field] != new[ident][field] for field in CLASSIFICATION_FIELDS):
            changed.append({**{key: new[ident][key] for key in (
                "transaction_id", "item_id", "institution_name", "account_name", "transaction_date",
                "month", "amount", "merchant_name", "description", "manual_type")},
                "before": {field: old[ident][field] for field in CLASSIFICATION_FIELDS},
                "after": {field: new[ident][field] for field in CLASSIFICATION_FIELDS}})
    months = []
    for month in sorted(set(before["months"]) | set(after["months"])):
        was, now = before["months"].get(month), after["months"].get(month)
        if was == now:
            continue
        metrics = {}
        for name in METRICS:
            a = Decimal(str((was or {}).get(name, 0)))
            b = Decimal(str((now or {}).get(name, 0)))
            if a != b:
                metrics[name] = {"before": str(a), "after": str(b), "delta": str(b - a)}
        categories = []
        old_nets, new_nets = _category_nets(was), _category_nets(now)
        for category in sorted(set(old_nets) | set(new_nets)):
            a = Decimal(old_nets.get(category, "0"))
            b = Decimal(new_nets.get(category, "0"))
            if a != b:
                categories.append({"category": category, "before": str(a), "after": str(b),
                                   "delta": str(b - a)})
        months.append({"month": month, "metrics": metrics, "categories": categories})
    return {
        "summary_by_month": months,
        "new_transactions": [new[ident] for ident in sorted(set(new) - set(old))],
        "removed_transactions": [old[ident] for ident in sorted(set(old) - set(new))],
        "changed_existing_transactions": changed,
    }


async def _locked_item(db, user_id, item_id):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(Item.item_id == item_id, Item.user_id == user_id)
                           .with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(404, "Item not found")
    return item


async def _transition_with_impact(db, user_id, item_id, transition):
    before = await ledger_snapshot(db, user_id)
    result = await transition(db, user_id, item_id)
    after = await ledger_snapshot(db, user_id)
    return result, before, after


async def _activate(db, user_id, item_id):
    item = await _locked_item(db, user_id, item_id)
    if item.status not in ACTIVATABLE:
        raise HTTPException(409, f"Only pending or deactivated Items can be activated, not {item.status}")
    failed = [check for check in await activation_checks_in_session(db, user_id, item)
              if check["result"] == "fail"]
    if failed:
        raise HTTPException(409, {"message": "Pre-activation checks failed",
                                  "checks": [check["id"] for check in failed]})
    await db.execute(update(Item).where(Item.item_id == item_id).values(
        status="active", activated_at=datetime.now(timezone.utc)))
    classification = await classify_active_transactions(db, user_id)
    return {"item_id": item_id, "status": "active", "classification": classification}


async def _deactivate(db, user_id, item_id):
    item = await _locked_item(db, user_id, item_id)
    if item.status != "active":
        raise HTTPException(409, f"Only active Items can be deactivated, not {item.status}")
    await db.execute(update(Item).where(Item.item_id == item_id).values(
        status="deactivated", deactivated_at=datetime.now(timezone.utc)))
    # The classification input is still every published Item, so nothing may change.
    classification = await classify_active_transactions(db, user_id)
    return {"item_id": item_id, "status": "deactivated", "classification": classification}


TRANSITIONS = {"activate": _activate, "deactivate": _deactivate}


async def preview_transition(session_factory, user_id, item_id, kind):
    """Run the transition, capture the ledger before and after, then roll back."""
    captured = {}
    try:
        async with session_factory() as db:
            async with db.begin():
                _, before, after = await _transition_with_impact(db, user_id, item_id, TRANSITIONS[kind])
                captured.update(before=before, after=after)
                raise _Rollback
    except _Rollback:
        pass
    before, after = captured["before"], captured["after"]
    return {"item_id": item_id, "transition": kind, "digest": _digest(before, after),
            **ledger_diff(before, after)}


async def apply_transition(db, user_id, item_id, kind, preview_digest):
    """Commit only when the recomputed impact equals the confirmed preview."""
    if not preview_digest:
        raise HTTPException(422, "A confirmed preview digest is required")
    result, before, after = await _transition_with_impact(db, user_id, item_id, TRANSITIONS[kind])
    digest = _digest(before, after)
    if digest != preview_digest:
        raise HTTPException(409, "The ledger changed since the preview; preview again before confirming")
    if kind == "activate":
        await db.execute(update(Item).where(Item.item_id == item_id).values(activation_digest=digest))
    return {"item_id": item_id, "status": result["status"], "digest": digest,
            **ledger_diff(before, after)}


def _check(ident, label, result, detail):
    return {"id": ident, "label": label, "result": result, "detail": detail}


async def activation_checks_in_session(db, user_id, item):
    """Pre-activation checks; fail blocks activation, warn is shown only."""
    item_id = item.item_id
    checks = [_check("K1", "Item can be activated",
                     "pass" if item.status in ACTIVATABLE else "fail",
                     f"Status is {item.status}")]
    accounts = (await db.execute(select(Account).where(Account.item_id == item_id)
                                 .order_by(Account.account_id))).scalars().all()
    enabled = [account for account in accounts if account.consumer_transactions_enabled]
    checks.append(_check("K2", "Consumer accounts discovered", "pass" if enabled else "fail",
                         f"{len(enabled)} of {len(accounts)} accounts are in consumer scope"))
    try:
        await validate_consumer_activation(db, item_id)
        ownership = ("pass", "Account ownership is consistent")
    except HTTPException as exc:
        ownership = ("fail", exc.detail)
    checks.append(_check("K3", "Account ownership and disabled-account data", *ownership))
    checks.append(_check("K5", "Initial sync completed",
                         "pass" if item.transactions_cursor is not None else "fail",
                         "A saved cursor exists" if item.transactions_cursor is not None
                         else "No transactions have been synced"))
    rows = (await db.execute(
        select(RawTransaction, Transaction)
        .join(Account, (Account.account_id == RawTransaction.account_id)
              & (Account.item_id == RawTransaction.item_id))
        .outerjoin(Transaction, Transaction.transaction_id == RawTransaction.transaction_id)
        .where(RawTransaction.item_id == item_id, RawTransaction.is_removed.is_(False),
               Account.consumer_transactions_enabled.is_(True))
    )).all()
    stale = invalid = 0
    for raw, normalized in rows:
        try:
            validate_normalization_input(raw)
        except NormalizationInputError:
            invalid += 1
            continue
        values = {"account_id": raw.account_id, "transaction_date": raw.transaction_date,
                  **normalized_raw_values(raw)}
        if normalized is None or _normalized_differs(normalized, values):
            stale += 1
    checks.append(_check("K6", "Normalization is complete", "fail" if stale or invalid else "pass",
                         f"{len(rows)} rows; {stale} missing or stale; {invalid} invalid source rows"))
    inputs = await _classification_inputs(db, user_id, Item.published.is_(True))
    classifications, _ = build_classifications(*inputs[:4], active_manual_types=inputs[4])
    outdated = sum(1 for ident, row in inputs[5].items()
                   if (row.transaction_type, row.is_spending, row.is_internal_transfer)
                   != classifications[ident])
    checks.append(_check("K7", "Published classification is current", "fail" if outdated else "pass",
                         f"{outdated} published rows differ from a fresh classification"))
    latest = await db.scalar(select(SyncItemRun.status).where(SyncItemRun.item_id == item_id)
                             .order_by(SyncItemRun.started_at.desc()).limit(1))
    problems = [name for name, bad in (("sync paused", item.sync_paused),
                                       ("metadata warning", item.metadata_warning is not None),
                                       ("last sync blocked", latest == "blocked")) if bad]
    checks.append(_check("K8", "Sync health", "warn" if problems else "pass",
                         ", ".join(problems) or "No sync problems recorded"))
    dates = (await db.execute(select(func.min(Transaction.transaction_date), func.max(Transaction.transaction_date))
                              .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
                              .where(RawTransaction.item_id == item_id, RawTransaction.is_removed.is_(False)))).one()
    ledger_start = await db.scalar(
        select(func.min(Transaction.transaction_date))
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .where(Item.user_id == user_id, Item.published.is_(True), RawTransaction.is_removed.is_(False)))
    earlier = dates[0] is not None and ledger_start is not None and dates[0] < ledger_start
    checks.append(_check("K10", "Date range", "warn" if earlier else "pass",
                         f"{dates[0] or '—'} to {dates[1] or '—'}" +
                         (f"; starts before the published ledger ({ledger_start})" if earlier else "")))
    running = await db.scalar(select(SyncRuntimeState.running_sequence).where(
        SyncRuntimeState.user_id == user_id, SyncRuntimeState.running_sequence.is_not(None),
        SyncRuntimeState.running_sequence > SyncRuntimeState.handled_sequence))
    checks.append(_check("K12", "No sync in progress", "warn" if running else "pass",
                         "A sync is running; activation waits for its lock" if running else "Idle"))
    return checks


async def activation_checks(db, user_id, item_id):
    item = await db.scalar(select(Item).where(Item.item_id == item_id, Item.user_id == user_id))
    if item is None:
        raise HTTPException(404, "Item not found")
    checks = await activation_checks_in_session(db, user_id, item)
    return {"item_id": item_id, "status": item.status, "checks": checks,
            "can_activate": not any(check["result"] == "fail" for check in checks)}
