"""Lifecycle migration rehearsal on a restored copy of a backup (D15) with timings (D12).

The target must be a disposable PostgreSQL cluster reached only through a private
Unix socket directory, and the database must be named `pft_restore_*`. Plaid is
never constructed: any client creation fails. Output is aggregate only: counts,
hashes and timings, never rows, identifiers, cursors or tokens.

Phases (PYTHONPATH selects the code under test):
  fingerprint [--reclassify]   old or new code; ledger, classification and Item hashes
  migrate [--copy-only-gate]   new code; strict Production preflight first, then init_db
  timing                       new code, after migration; lifecycle operation timings
  pending-timing               valid synthetic onboarding at real-backup ledger scale
"""

import argparse
import asyncio
import hashlib
import json
import os
import stat
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch


def _guard():
    from sqlalchemy.engine import make_url
    url = make_url(os.environ["DATABASE_URL"])
    socket_dir = url.query.get("host")
    if url.host is not None or not socket_dir:
        raise SystemExit("Refusing: connect through a private Unix socket directory only (?host=/path)")
    mode = Path(socket_dir).stat().st_mode
    if stat.S_IMODE(mode) & 0o077 or not Path(socket_dir).is_dir():
        raise SystemExit("Refusing: the socket directory must be private (mode 0700)")
    if not (url.database or "").startswith("pft_restore_"):
        raise SystemExit("Refusing: the database must be a pft_restore_* copy")
    if os.environ.get("PLAID_ENV", "").lower() == "production" or os.environ.get("EXPECTED_DATABASE_NAME"):
        raise SystemExit("Refusing: Production environment variables are set")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def _identity(connection):
    from sqlalchemy import text
    row = (await connection.execute(text(
        "SELECT current_database(), current_setting('listen_addresses'), inet_server_port()"))).one()
    if row[1] != "" or row[2] is not None:
        raise SystemExit("Refusing: the disposable cluster must be socket-only (listen_addresses='')")
    return {"database": row[0]}


async def _user_id(connection):
    from sqlalchemy import text
    users = (await connection.execute(text("SELECT DISTINCT user_id FROM items"))).scalars().all()
    if len(users) != 1:
        raise SystemExit(f"Refusing: expected exactly one Item owner, found {len(users)}")
    return users[0]


async def fingerprint(reclassify):
    from sqlalchemy import select, text
    from api import db as database
    async with database.engine.connect() as connection:
        await _identity(connection)
        user_id = await _user_id(connection)
    os.environ["PLAID_PILOT_USER_ID"] = user_id
    from api.models import Item
    from api.routes import analytics
    from api.services.derivation import classify_active_transactions
    from statement_imports.persistence import external_classifications

    started = time.monotonic()
    reclassified = None
    if reclassify:
        async with database.SessionLocal.begin() as db:
            reclassified = (await classify_active_transactions(db, user_id))["classified_count"]
    async with database.SessionLocal() as db:
        await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        tables = {}
        for table in ("transactions", "raw_transactions", "accounts", "manual_classification_overrides",
                      "manual_category_overrides", "manual_transaction_label_overrides",
                      "manual_benefit_category_overrides", "statement_import_batches", "statement_import_rows"):
            tables[table] = await db.scalar(text(
                f"SELECT md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, "
                f"E'\\n' ORDER BY to_jsonb(t)::text), '')) || ':' || count(*) FROM {table} t"))
        items = (await db.execute(select(Item).order_by(Item.item_id))).scalars().all()
        rows = await analytics._active_analytics_rows(date(1900, 1, 1), date(9999, 12, 31), db)
        months = {}
        for row in rows:
            months.setdefault(row[0].transaction_date.strftime("%Y-%m"), []).append(row)
        monthly = {month: analytics.summarize_monthly_transactions(month_rows)
                   for month, month_rows in sorted(months.items())}
        classifications = await external_classifications(db, user_id)
    await database.engine.dispose()
    return {
        "status_counts": {status: sum(1 for item in items if item.status == status)
                          for status in sorted({item.status for item in items})},
        "items_digest": _digest([(item.item_id, item.status, item.institution_id, item.transactions_cursor,
                                  hashlib.sha256(item.access_token.encode()).hexdigest()) for item in items]),
        "table_digests": tables,
        "classification_digest": classifications,
        "analytics_rows": len(rows),
        "analytics_months": len(monthly),
        "analytics_digest": _digest(monthly),
        "reclassified_count": reclassified,
        "seconds": round(time.monotonic() - started, 3),
    }


async def migrate(copy_only=False):
    from api import db as database
    from api.migrations import LifecyclePreflightBlocked, require_lifecycle_preflight
    async with database.engine.connect() as connection:
        await _identity(connection)
        await connection.rollback()
        try:
            # copy_only applies the non-Production gate; it never represents Production.
            report = await require_lifecycle_preflight(connection, production=not copy_only)
        except LifecyclePreflightBlocked as blocked:
            await database.engine.dispose()
            return {"migrated": False, "errors": blocked.errors, "status_counts": blocked.report["status_counts"]}
        finally:
            await connection.rollback()
    started = time.monotonic()
    # Same gate inside init_db; Production rules are applied explicitly above.
    await database.init_db()
    seconds = round(time.monotonic() - started, 3)
    await database.engine.dispose()
    return {"migrated": True, "production_gate": not copy_only,
            "status_counts": report["status_counts"], "seconds": seconds}


async def timing():
    from sqlalchemy import func, select
    from api import db as database
    from api.models import Item, RawTransaction
    from api.services import lifecycle
    from api.services.derivation import classify_active_transactions
    async with database.engine.connect() as connection:
        await _identity(connection)
        user_id = await _user_id(connection)
    os.environ["PLAID_PILOT_USER_ID"] = user_id
    result = {}

    async def timed(name, call):
        started = time.monotonic()
        value = await call()
        result[name] = round(time.monotonic() - started, 3)
        return value

    async def snapshot():
        async with database.SessionLocal() as db:
            return await lifecycle.ledger_snapshot(db, user_id)

    ledger = await timed("ledger_snapshot_seconds", snapshot)
    result["ledger_transactions"] = len(ledger["transactions"])

    async def classify():
        async with database.SessionLocal.begin() as db:
            return await classify_active_transactions(db, user_id)
    await timed("classify_seconds", classify)

    async with database.SessionLocal() as db:
        counts = dict((await db.execute(
            select(Item.status, func.count(RawTransaction.transaction_id))
            .outerjoin(RawTransaction, RawTransaction.item_id == Item.item_id)
            .where(Item.user_id == user_id).group_by(Item.status))).all())
        pending = (await db.execute(select(Item.item_id).where(Item.status == "pending"))).scalars().all()
        largest = await db.scalar(
            select(Item.item_id).join(RawTransaction, RawTransaction.item_id == Item.item_id)
            .where(Item.status == "active").group_by(Item.item_id)
            .order_by(func.count().desc()).limit(1))
    result["raw_rows_by_status"] = counts

    def summary(diff):
        return {"months_changed": len(diff["summary_by_month"]), "new": len(diff["new_transactions"]),
                "changed_existing": len(diff["changed_existing_transactions"]),
                "removed": len(diff["removed_transactions"])}

    async def operation(label, kind, item_id):
        from fastapi import HTTPException
        try:
            await _operation(label, kind, item_id)
        except HTTPException as exc:
            result[f"{label}_refused"] = {"status": exc.status_code, "detail": exc.detail}

    async def _operation(label, kind, item_id):
        preview = await timed(f"{label}_preview_seconds",
                              lambda: lifecycle.preview_transition(database.SessionLocal, user_id, item_id, kind))

        async def apply():
            async with database.SessionLocal.begin() as db:
                return await lifecycle.apply_transition(db, user_id, item_id, kind, preview["digest"])
        applied = await timed(f"{label}_apply_seconds", apply)
        result[f"{label}_impact"] = summary(preview)
        result[f"{label}_preview_equals_apply"] = all(
            preview[key] == applied[key] for key in ("digest", "summary_by_month", "new_transactions",
                                                     "removed_transactions", "changed_existing_transactions"))

    # Operations change only this disposable copy. The largest active Item is the worst case
    # for deactivation; every Pending Item is previewed for activation and then activated.
    if largest is not None:
        await operation("deactivate_largest", "deactivate", largest)
        await operation("reactivate_largest", "reactivate", largest)
    for index, item_id in enumerate(pending):
        async with database.SessionLocal() as db:
            checks = await lifecycle.activation_checks(db, user_id, item_id)
        failing = [check["id"] for check in checks["checks"] if check["result"] == "fail"]
        result[f"pending_{index}_failing_checks"] = failing
        if not failing:
            await operation(f"activate_pending_{index}", "activate", item_id)
    await database.engine.dispose()
    return result


def pending_fixture_rows(account_id, count):
    """Same payload shape as test_institution_lifecycle.plaid_tx; no copied source rows."""
    return [{"transaction_id": f"{account_id}-tx-{index}", "account_id": account_id,
             "date": date(2024 + (8 + index % 26) // 12, 1 + (8 + index % 26) % 12,
                          1 + (index // 26) % 28),
             "amount": round(37.11 + (index % 29) / 100, 2),
             "name": "REHEARSAL SYNTHETIC PURCHASE", "merchant_name": "Rehearsal Fixture Store",
             "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}}
            for index in range(count)]


def require_pending_invariant(name, actual, expected):
    if actual != expected:
        raise RuntimeError("Pending rehearsal invariant failed: " + name)


async def pending_timing():
    """Supported lifecycle-test onboarding path, on a fresh restored/migrated copy only."""
    import uuid
    from sqlalchemy import func, select, text
    from api import db as database
    from api.models import Account, Item, ONBOARDING_STATUSES, RawTransaction, Transaction
    from api.services import lifecycle
    from api.services.derivation import normalize_item_transactions
    from api.services.persistence import persist_account_metadata, persist_consumer_transactions
    from api.migrations import institution_lifecycle_preflight

    async with database.engine.connect() as connection:
        await _identity(connection)
        user_id = await _user_id(connection)
        report = await institution_lifecycle_preflight(connection)
        require_pending_invariant("migrated all-Active fresh copy", (report["applied"], report["blockers"],
                                  set(report["status_counts"])), (True, [], {"active"}))
    os.environ["PLAID_PILOT_USER_ID"] = user_id
    fixture = "pft-rehearsal-synthetic-" + uuid.uuid4().hex
    account_id = fixture + "-checking"

    async def fingerprints(db, *, original_only=False, source_only=False):
        tables = (await db.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
        result = {}
        for table in tables:
            quoted = db.get_bind().dialect.identifier_preparer.quote(table)
            predicate = ""
            if original_only:
                if table in ("items", "accounts", "raw_transactions"):
                    predicate = " WHERE t.item_id <> :fixture"
                elif table == "transactions":
                    predicate = " WHERE t.account_id <> :account"
            row = "to_jsonb(t)"
            if source_only and table == "transactions":
                row += " - 'transaction_type' - 'is_spending' - 'is_internal_transfer'"
                # The supported classifier updates this timestamp on changed fixture
                # classifications. Original rows still have a separate exact full-row check.
                row = f"CASE WHEN t.account_id = :account THEN ({row}) - 'updated_at' ELSE ({row}) END"
            if source_only and table == "items":
                row += " - 'status' - 'published' - 'sync_enabled' - 'activated_at' - 'activation_digest' - 'updated_at'"
            result[table] = await db.scalar(text(
                f"SELECT md5(coalesce(string_agg(({row})::text, E'\\n' ORDER BY ({row})::text COLLATE \"C\"), '')) "
                f"|| ':' || count(*) FROM {quoted} t{predicate}"),
                {"fixture": fixture, "account": account_id})
        return result

    async def state(db):
        return (await db.execute(select(Item.status, Item.sync_enabled, Item.published,
                                       Item.transactions_cursor).where(Item.item_id == fixture))).one()

    try:
        async with database.SessionLocal() as db:
            baseline = await fingerprints(db, original_only=True)
            baseline_ledger = await lifecycle.ledger_snapshot(db, user_id)
            size = await db.scalar(select(func.count()).select_from(RawTransaction).join(
                Account, Account.account_id == RawTransaction.account_id).join(Item, Item.item_id == RawTransaction.item_id)
                .where(Item.user_id == user_id, Item.status == "active", Account.consumer_transactions_enabled.is_(True),
                       RawTransaction.is_removed.is_(False)).group_by(Item.item_id).order_by(func.count().desc()).limit(1))
        if not size:
            raise RuntimeError("No Active consumer transactions to size the Pending fixture")
        rows = pending_fixture_rows(account_id, size)
        # Matches the supported test fixture creation + explicit Pending onboarding,
        # never Active -> Pending, never a fake cursor on an existing real Item.
        async with database.SessionLocal.begin() as db:
            db.add(Item(item_id=fixture, user_id=user_id, institution_id=fixture,
                        institution_name="Synthetic Rehearsal Institution", status="pending",
                        access_token="synthetic-unused-test-token"))
            await db.flush()
            await persist_account_metadata(db, user_id, fixture, [{"account_id": account_id,
                "name": "Synthetic Checking", "type": "depository", "subtype": "checking"}],
                statuses=ONBOARDING_STATUSES)
            await persist_consumer_transactions(db, user_id, fixture, None, rows, [], [],
                                                "synthetic-onboarding-complete", 1, statuses=ONBOARDING_STATUSES)
            await normalize_item_transactions(db, user_id, fixture, statuses=ONBOARDING_STATUSES)
            require_pending_invariant("onboarding preserves original rows", await fingerprints(db, original_only=True), baseline)
            require_pending_invariant("Pending stays unpublished", await lifecycle.ledger_snapshot(db, user_id), baseline_ledger)
        async with database.SessionLocal() as db:
            pending_state = await state(db)
            require_pending_invariant("Pending flags", tuple(pending_state[:3]), ("pending", False, False))
            checks = await lifecycle.activation_checks(db, user_id, fixture)
            require_pending_invariant("pre-activation checks", checks["can_activate"], True)
            preview_baseline = await fingerprints(db)
            source_baseline = await fingerprints(db, source_only=True)
        started = time.monotonic()
        preview = await lifecycle.preview_transition(database.SessionLocal, user_id, fixture, "activate")
        preview_seconds = round(time.monotonic() - started, 3)
        async with database.SessionLocal() as db:
            require_pending_invariant("preview rolls back all rows", await fingerprints(db), preview_baseline)
            require_pending_invariant("preview preserves Pending state", await state(db), pending_state)
        started = time.monotonic()
        async with database.SessionLocal.begin() as db:
            applied = await lifecycle.apply_transition(db, user_id, fixture, "activate", preview["digest"])
            apply_core_seconds = round(time.monotonic() - started, 3)
            for key in ("digest", "summary_by_month", "new_transactions", "removed_transactions", "changed_existing_transactions"):
                require_pending_invariant("preview/apply parity", applied[key], preview[key])
            require_pending_invariant("original rows preserved", await fingerprints(db, original_only=True), baseline)
            require_pending_invariant("source rows preserved", await fingerprints(db, source_only=True), source_baseline)
            require_pending_invariant("Active flags", tuple((await state(db))[:3]), ("active", True, True))
            require_pending_invariant("saved onboarding cursor", (await state(db))[3], pending_state[3])
            classified = await db.scalar(select(func.count()).select_from(Transaction).where(
                Transaction.account_id == account_id, Transaction.transaction_type == "expense",
                Transaction.is_spending.is_(True), Transaction.is_internal_transfer.is_(False)))
            require_pending_invariant("all fixture purchases classified", classified, size)
            require_pending_invariant("published fixture count", len(applied["new_transactions"]), size)
        apply_seconds = round(time.monotonic() - started, 3)
        async with database.SessionLocal() as db:
            require_pending_invariant("committed original rows preserved", await fingerprints(db, original_only=True), baseline)
            require_pending_invariant("committed source rows preserved", await fingerprints(db, source_only=True), source_baseline)
        return {"passed": True, "fixture_is_synthetic": True, "fixture_rows": size, "baseline_analytics_rows": len(baseline_ledger["transactions"]),
                "activation_preview_seconds": preview_seconds, "activation_apply_and_validation_seconds": apply_seconds,
                "activation_apply_core_seconds": apply_core_seconds,
                "preview_equals_apply": True, "preview_rolled_back": True, "pending_unpublished": True,
                "pre_activation_checks_pass": True, "original_rows_preserved": True, "source_rows_preserved": True,
                "cursor_preserved": True, "fixture_classification_valid": True, "lifecycle_flags_valid": True}
    finally:
        await database.engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["fingerprint", "migrate", "timing", "pending-timing"])
    parser.add_argument("--reclassify", action="store_true")
    parser.add_argument("--copy-only-gate", action="store_true",
                        help="migrate with the non-Production gate (rehearsal copy only)")
    args = parser.parse_args()
    _guard()
    phases = {"fingerprint": lambda: fingerprint(args.reclassify),
              "migrate": lambda: migrate(args.copy_only_gate), "timing": timing, "pending-timing": pending_timing}
    with patch("plaid.ApiClient", side_effect=RuntimeError("Plaid is disabled in restore rehearsals")):
        try:
            report = asyncio.run(phases[args.phase]())
        except Exception as error:
            if args.phase != "pending-timing":
                raise
            # SQL errors can contain parameters/rows; never expose them in this phase.
            safe_error = str(error) if isinstance(error, RuntimeError) and str(error).startswith(
                "Pending rehearsal invariant failed:") else "Pending rehearsal failed; no row/error parameters printed"
            report = {"passed": False, "error": safe_error, "error_type": type(error).__name__}
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    print()
    return 2 if ((args.phase == "migrate" and not report["migrated"])
                 or (args.phase == "pending-timing" and not report["passed"])) else 0


if __name__ == "__main__":
    sys.exit(main())
