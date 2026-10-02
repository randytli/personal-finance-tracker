"""Lifecycle migration rehearsal on a restored copy of a backup (D15) with timings (D12).

The target must be a disposable PostgreSQL cluster reached only through a private
Unix socket directory, and the database must be named `pft_restore_*`. Plaid is
never constructed: any client creation fails. Output is aggregate only: counts,
hashes and timings, never rows, identifiers, cursors or tokens.

Phases (PYTHONPATH selects the code under test):
  fingerprint [--reclassify]   old or new code; ledger, classification and Item hashes
  migrate [--copy-only-gate]   new code; strict Production preflight first, then init_db
  timing                       new code, after migration; lifecycle operation timings
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["fingerprint", "migrate", "timing"])
    parser.add_argument("--reclassify", action="store_true")
    parser.add_argument("--copy-only-gate", action="store_true",
                        help="migrate with the non-Production gate (rehearsal copy only)")
    args = parser.parse_args()
    _guard()
    phases = {"fingerprint": lambda: fingerprint(args.reclassify),
              "migrate": lambda: migrate(args.copy_only_gate), "timing": timing}
    with patch("plaid.ApiClient", side_effect=RuntimeError("Plaid is disabled in restore rehearsals")):
        report = asyncio.run(phases[args.phase]())
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    print()
    return 2 if args.phase == "migrate" and not report["migrated"] else 0


if __name__ == "__main__":
    sys.exit(main())
