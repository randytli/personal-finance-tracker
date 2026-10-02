"""Institution lifecycle tests on disposable PostgreSQL schemas with a fake Plaid client only."""

import io
import json
import os
import unittest
import uuid
from contextlib import ExitStack, redirect_stdout
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import jobs
from api.migrations import (LifecyclePreflightBlocked, institution_lifecycle_preflight,
                            lifecycle_preflight_errors, migrate_institution_lifecycle)
from api.models import (ONBOARDING_STATUSES, Account, Base, Item, ManualClassificationOverride, LIFECYCLE_STATES,
                        RawTransaction, Transaction)
from api.services import lifecycle
from api.services import sync_all as service
from api.services.derivation import classify_active_transactions, normalize_item_transactions
from api.services.persistence import persist_consumer_transactions
from statement_imports.persistence import external_classifications

USER = "lifecycle-user"


class Response:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class FakePlaid:
    """Synthetic SDK: one page per Item, recording the cursor each Item resumed from."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def transactions_sync(self, request, *, _request_timeout=None):
        body = request.to_dict()
        item = body["access_token"].removeprefix("token-")
        self.requests.append((item, body.get("cursor")))
        added, next_cursor = self.pages.get(item, ([], body.get("cursor") or item + "-0"))
        return Response({"added": added, "modified": [], "removed": [], "next_cursor": next_cursor,
                         "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"})


def plaid_tx(ident, account, amount, day, name, category, merchant=None, month=8):
    return {"transaction_id": ident, "account_id": account, "date": date(2026, month, day),
            "amount": amount, "name": name, "merchant_name": merchant,
            "personal_finance_category": {"primary": category}}


CHASE = [
    plaid_tx("a-zelle-in", "a-check", -50, 4, "ZELLE PAYMENT FROM SAM CONF# ABCD1234", "INCOME"),
    plaid_tx("a-coffee", "a-check", 25, 2, "COFFEE SHOP", "FOOD_AND_DRINK", "Coffee Shop"),
    plaid_tx("a-pay", "a-check", -2000, 1, "PAYROLL", "INCOME"),
    plaid_tx("a-july", "a-check", 12, 20, "BOOK STORE", "GENERAL_MERCHANDISE", month=7),
]
ALLY = [
    plaid_tx("b-zelle-out", "b-check", 50, 4, "ZELLE PAYMENT TO RANDY CONF# ABCD1234", "TRANSFER_OUT"),
    plaid_tx("b-grocery", "b-check", 30, 6, "MARKET", "FOOD_AND_DRINK", "Market"),
]


@unittest.skipUnless(os.environ.get("PFT_LIFECYCLE_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class LifecycleDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotIn(default_engine.url.port, {None, 5432})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.admin = create_async_engine(default_engine.url)
        self.schema = "lifecycle_test_" + uuid.uuid4().hex
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(default_engine.url, connect_args={
            "server_settings": {"search_path": self.schema}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = ExitStack()
        self.patches.enter_context(patch.dict(os.environ, {"PLAID_PILOT_USER_ID": USER}))
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            for item_id, name, status in (("a", "Chase", "active"), ("b", "Ally", "pending")):
                db.add(Item(item_id=item_id, user_id=USER, institution_id="ins_" + item_id,
                            institution_name=name, status=status, access_token="token-" + item_id))
                await db.flush()
                db.add(Account(account_id=item_id + "-check", item_id=item_id, name=name + " Checking",
                               type="depository", consumer_transactions_enabled=True))
            db.add(Account(account_id="a-invest", item_id="a", name="Brokerage", type="investment",
                           consumer_transactions_enabled=False))

    async def asyncTearDown(self):
        self.patches.close()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def sync(self, pages):
        client = FakePlaid(pages)
        result = await service.sync_all(USER, client=client, session_factory=self.sessions, engine=self.engine)
        return client, result

    async def onboard_pending(self, rows=ALLY, cursor="b-1"):
        """The manual onboarding path: persist and normalize, no classification."""
        async with self.sessions.begin() as db:
            item = await db.get(Item, "b")
            await persist_consumer_transactions(db, USER, "b", item.transactions_cursor, list(rows), [], [],
                                                cursor, 1, statuses=ONBOARDING_STATUSES)
            await normalize_item_transactions(db, USER, "b", statuses=ONBOARDING_STATUSES)

    async def seed(self):
        await self.sync({"a": (CHASE, "a-1")})
        await self.onboard_pending()

    async def fingerprint(self):
        async with self.sessions() as db:
            ledger = await lifecycle.ledger_snapshot(db, USER)
            rows = await db.scalar(text(
                "SELECT md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, "
                "E'\\n' ORDER BY t.transaction_id), '')) FROM transactions t"))
            items = (await db.execute(select(Item.item_id, Item.status, Item.transactions_cursor,
                                             Item.access_token).order_by(Item.item_id))).all()
            classifications = await external_classifications(db, USER)
        return {"ledger": ledger, "transactions": rows, "items": items, "classifications": classifications}

    async def classification(self, ident):
        async with self.sessions() as db:
            row = (await db.execute(text(
                "SELECT transaction_type, is_spending, is_internal_transfer FROM transactions "
                "WHERE transaction_id=:id"), {"id": ident})).one()
        return tuple(row)

    async def item(self, item_id):
        async with self.sessions() as db:
            return await db.get(Item, item_id)

    async def preview(self, kind, item_id="b"):
        return await lifecycle.preview_transition(self.sessions, USER, item_id, kind)

    async def apply(self, kind, digest, item_id="b"):
        async with self.sessions.begin() as db:
            return await lifecycle.apply_transition(db, USER, item_id, kind, digest)

    async def activate(self, item_id="b", kind="activate"):
        preview = await self.preview(kind, item_id)
        return preview, await self.apply(kind, preview["digest"], item_id)

    async def onboarding(self, kind, item_id="b"):
        async with self.sessions.begin() as db:
            return await lifecycle.change_onboarding_status(db, USER, item_id, kind)

    async def legacy_shape(self):
        """Recreate the pre-lifecycle items shape, keeping every row."""
        async with self.engine.begin() as connection:
            await connection.execute(text("DROP INDEX ix_items_user_lifecycle"))
            for column in ("sync_enabled", "published", "activated_at", "deactivated_at", "activation_digest"):
                await connection.execute(text(f"ALTER TABLE items DROP COLUMN {column}"))
            await connection.execute(text("ALTER TABLE items DROP CONSTRAINT ck_items_status"))
            await connection.execute(text("ALTER TABLE items ADD CONSTRAINT ck_items_status "
                                          "CHECK (status IN ('pending','active','disabled'))"))

    async def schema_state(self):
        """Columns, constraints and financial rows, readable on either schema shape."""
        async with self.sessions() as db:
            columns = sorted((await db.execute(text(
                "SELECT attname FROM pg_attribute WHERE attrelid='items'::regclass AND attnum>0 "
                "AND NOT attisdropped"))).scalars())
            status_check = await db.scalar(text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='ck_items_status'"))
            rows = await db.scalar(text(
                "SELECT md5(coalesce(string_agg((to_jsonb(t) - 'created_at' - 'updated_at')::text, "
                "E'\\n' ORDER BY t.transaction_id), '')) FROM transactions t"))
            items = (await db.execute(text("SELECT item_id, status, transactions_cursor FROM items "
                                           "ORDER BY item_id"))).all()
        return columns, status_check, rows, items

    async def test_pending_data_never_reaches_published_classification(self):
        await self.seed()
        self.assertEqual(await self.classification("a-zelle-in"), ("income", False, False))
        self.assertEqual(await self.classification("b-zelle-out"), (None, None, None))
        before = await self.fingerprint()
        # A later published sync reclassifies, still without the pending counterpart.
        await self.sync({"a": ([], "a-2")})
        after = await self.fingerprint()
        self.assertEqual(after["ledger"], before["ledger"])
        self.assertEqual(after["classifications"], before["classifications"])
        self.assertNotIn("b-zelle-out", after["ledger"]["transactions"])

    async def test_activation_preview_equals_actual_with_cross_institution_pairing(self):
        await self.seed()
        before = await self.fingerprint()
        preview = await self.preview("activate")
        # The preview ran the real transition and rolled it back.
        self.assertEqual(await self.fingerprint(), before)
        self.assertEqual((await self.item("b")).status, "pending")

        changed = {row["transaction_id"]: row for row in preview["changed_existing_transactions"]}
        self.assertEqual(set(changed), {"a-zelle-in"})
        self.assertEqual(changed["a-zelle-in"]["before"]["transaction_type"], "income")
        self.assertEqual(changed["a-zelle-in"]["after"],
                         {"transaction_type": "transfer", "is_spending": False,
                          "is_internal_transfer": True, "category": changed["a-zelle-in"]["after"]["category"]})
        self.assertEqual([row["transaction_id"] for row in preview["new_transactions"]],
                         ["b-grocery", "b-zelle-out"])
        self.assertEqual(preview["removed_transactions"], [])
        august = {entry["month"]: entry for entry in preview["summary_by_month"]}["2026-08"]
        self.assertEqual(august["metrics"]["income"]["delta"], "-50.00")
        self.assertEqual(august["metrics"]["gross_spending"]["delta"], "30.00")
        self.assertNotIn("2026-07", {entry["month"] for entry in preview["summary_by_month"]})

        result = await self.apply("activate", preview["digest"])
        for key in ("digest", "summary_by_month", "new_transactions", "removed_transactions",
                    "changed_existing_transactions"):
            self.assertEqual(result[key], preview[key], key)
        after = await self.fingerprint()
        self.assertEqual(lifecycle.ledger_diff(before["ledger"], after["ledger"]),
                         {key: preview[key] for key in ("summary_by_month", "new_transactions",
                                                        "removed_transactions",
                                                        "changed_existing_transactions")})
        self.assertEqual(await self.classification("a-zelle-in"), ("transfer", False, True))
        item = await self.item("b")
        self.assertEqual((item.status, item.sync_enabled, item.published), ("active", True, True))
        self.assertEqual(item.activation_digest, preview["digest"])
        self.assertIsNotNone(item.activated_at)

    async def test_stale_preview_is_refused_without_changes(self):
        await self.seed()
        preview = await self.preview("activate")
        async with self.sessions.begin() as db:
            db.add(ManualClassificationOverride(transaction_id="a-coffee", transaction_type="reimbursement",
                                                created_by="test", updated_by="test"))
        before = await self.fingerprint()
        with self.assertRaises(HTTPException) as refused:
            await self.apply("activate", preview["digest"])
        self.assertEqual(refused.exception.status_code, 409)
        self.assertEqual(await self.fingerprint(), before)
        self.assertEqual((await self.item("b")).status, "pending")

    async def test_activation_failure_midway_rolls_back_everything(self):
        await self.seed()
        before = await self.fingerprint()
        preview = await self.preview("activate")
        classify = lifecycle.classify_active_transactions

        async def fail_after_writes(db, user_id):
            await classify(db, user_id)
            raise RuntimeError("synthetic failure")

        with patch.object(lifecycle, "classify_active_transactions", new=fail_after_writes):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                await self.apply("activate", preview["digest"])
        self.assertEqual(await self.fingerprint(), before)
        item = await self.item("b")
        self.assertEqual((item.status, item.activated_at, item.activation_digest), ("pending", None, None))
        self.assertEqual(await self.classification("a-zelle-in"), ("income", False, False))

    async def test_deactivation_keeps_analytics_and_every_classification(self):
        await self.seed()
        await self.activate()
        before = await self.fingerprint()
        preview = await self.preview("deactivate")
        self.assertEqual((preview["summary_by_month"], preview["new_transactions"],
                          preview["removed_transactions"], preview["changed_existing_transactions"]),
                         ([], [], [], []))
        await self.apply("deactivate", preview["digest"])
        after = await self.fingerprint()
        self.assertEqual(after["ledger"], before["ledger"])
        self.assertEqual(after["transactions"], before["transactions"])
        self.assertEqual(after["classifications"], before["classifications"])
        # Deactivated transactions keep feeding classification: the pair still holds.
        self.assertEqual(await self.classification("a-zelle-in"), ("transfer", False, True))
        async with self.sessions.begin() as db:
            await classify_active_transactions(db, USER)
        self.assertEqual(await self.fingerprint(), after)
        item = await self.item("b")
        self.assertEqual((item.status, item.sync_enabled, item.published), ("deactivated", False, True))

    async def test_scheduled_and_requested_sync_skip_deactivated_item(self):
        await self.seed()
        await self.activate()
        await self.sync({"a": ([], "a-2"), "b": ([], "b-2")})
        preview = await self.preview("deactivate")
        await self.apply("deactivate", preview["digest"])
        client, result = await self.sync({"a": ([], "a-3"), "b": ([], "b-3")})
        self.assertEqual([item for item, _ in client.requests], ["a"])
        self.assertEqual(set(result["items"]), {"a"})
        self.assertEqual((await self.item("b")).transactions_cursor, "b-2")
        with self.assertRaisesRegex(ValueError, "not active"):
            await jobs.request_sync(USER, ["b"], session_factory=self.sessions)
        with self.assertRaises(HTTPException):
            await self.onboard_pending(rows=[], cursor="b-x")

    async def test_reactivation_resumes_from_saved_cursor(self):
        await self.seed()
        await self.activate()
        await self.sync({"a": ([], "a-2"), "b": ([], "b-2")})
        preview = await self.preview("deactivate")
        await self.apply("deactivate", preview["digest"])
        await self.sync({"a": ([], "a-3")})
        # Reactivation is its own operation; the pending-only activation refuses it.
        with self.assertRaises(HTTPException) as refused:
            await self.preview("activate")
        self.assertEqual(refused.exception.status_code, 409)
        preview, result = await self.activate(kind="reactivate")
        self.assertEqual(result["status"], "active")
        self.assertEqual((result["new_transactions"], result["changed_existing_transactions"]), ([], []))
        gap = [plaid_tx("b-during-gap", "b-check", 40, 9, "HARDWARE", "GENERAL_MERCHANDISE")]
        client, _ = await self.sync({"a": ([], "a-4"), "b": (gap, "b-3")})
        self.assertIn(("b", "b-2"), client.requests)
        self.assertEqual((await self.item("b")).transactions_cursor, "b-3")
        self.assertEqual(await self.classification("b-during-gap"), ("expense", True, False))

    async def test_pre_activation_checks_block_unready_items(self):
        async with self.sessions() as db:
            checks = await lifecycle.activation_checks(db, USER, "b")
        results = {check["id"]: check["result"] for check in checks["checks"]}
        self.assertFalse(checks["can_activate"])
        self.assertEqual(results["K5"], "fail")
        with self.assertRaises(HTTPException) as refused:
            await self.preview("activate")
        self.assertEqual(refused.exception.status_code, 409)
        self.assertIn("K5", refused.exception.detail["checks"])

        await self.seed()
        async with self.sessions.begin() as db:
            await db.execute(text("UPDATE transactions SET amount = amount + 1 WHERE transaction_id='b-grocery'"))
        async with self.sessions() as db:
            checks = await lifecycle.activation_checks(db, USER, "b")
        results = {check["id"]: check["result"] for check in checks["checks"]}
        self.assertEqual(results["K6"], "fail")
        async with self.sessions.begin() as db:
            await normalize_item_transactions(db, USER, "b", statuses=ONBOARDING_STATUSES)
        async with self.sessions() as db:
            checks = await lifecycle.activation_checks(db, USER, "b")
        self.assertTrue(checks["can_activate"], checks)
        with self.assertRaises(HTTPException):
            await self.apply("deactivate", "0" * 64, item_id="b")
        with self.assertRaises(HTTPException):
            await self.preview("activate", item_id="a")

    async def test_migration_derives_flags_and_preserves_every_fingerprint(self):
        await self.seed()
        async with self.sessions.begin() as db:
            db.add(Item(item_id="c", user_id=USER, institution_id="ins_c", institution_name="Rejected",
                        status="disabled", access_token="token-c"))
            db.add(ManualClassificationOverride(transaction_id="a-coffee", transaction_type="reimbursement",
                                                created_by="test", updated_by="test"))
        async with self.sessions.begin() as db:
            await classify_active_transactions(db, USER)
        before = await self.fingerprint()
        await self.legacy_shape()
        for _ in range(2):
            async with self.engine.begin() as connection:
                await migrate_institution_lifecycle(connection)
        after = await self.fingerprint()
        self.assertEqual(after, before)
        async with self.sessions() as db:
            flags = {row.item_id: (row.status, row.sync_enabled, row.published)
                     for row in (await db.execute(select(Item))).scalars()}
        self.assertEqual(flags, {item: (status, *LIFECYCLE_STATES[status]) for item, status in
                                 (("a", "active"), ("b", "pending"), ("c", "disabled"))})
        async with self.sessions.begin() as db:
            result = await classify_active_transactions(db, USER)
        self.assertEqual(await self.fingerprint(), before, result)
        async with self.engine.begin() as connection:
            with self.assertRaises(Exception):
                await connection.execute(text("UPDATE items SET published = false WHERE item_id='a'"))


    async def test_production_preflight_stops_before_any_ddl_unless_every_item_is_active(self):
        from api import db as database
        from api import lifecycle_preflight
        await self.seed()
        async with self.sessions.begin() as db:
            db.add(Item(item_id="c", user_id=USER, institution_id="ins_c", institution_name="Rejected",
                        status="disabled", access_token="token-c"))
        await self.legacy_shape()
        before = await self.schema_state()
        self.assertNotIn("published", before[0])

        with patch.object(database, "engine", self.engine), patch.dict(os.environ, {"PLAID_ENV": "production"}):
            with self.assertRaises(LifecyclePreflightBlocked) as blocked:
                await database.init_db()
        self.assertEqual(blocked.exception.errors,
                         ["Production Items must all be active before this migration; found disabled=1, pending=1"])
        self.assertEqual(await self.schema_state(), before)

        output = io.StringIO()
        with patch.object(lifecycle_preflight, "engine", self.engine), redirect_stdout(output):
            self.assertEqual(await lifecycle_preflight.main(), 2)
        report = json.loads(output.getvalue())
        self.assertEqual((report["migration_may_run"], report["applied"], report["status_counts"]),
                         (False, False, {"active": 1, "disabled": 1, "pending": 1}))
        self.assertEqual(await self.schema_state(), before)

        # Once the owner resolves the Items outside the migration, the gate opens.
        async with self.sessions.begin() as db:
            await db.execute(text("DELETE FROM items WHERE item_id='c'"))
            await db.execute(text("UPDATE items SET status='active' WHERE item_id='b'"))
        output = io.StringIO()
        with patch.object(lifecycle_preflight, "engine", self.engine), redirect_stdout(output):
            self.assertEqual(await lifecycle_preflight.main(), 0)
        with patch.object(database, "engine", self.engine), patch.dict(os.environ, {"PLAID_ENV": "production"}):
            await database.init_db()
            columns = (await self.schema_state())[0]
            self.assertIn("published", columns)
            # After the migration, later Pending onboarding must not block a rerun.
            async with self.sessions.begin() as db:
                db.add(Item(item_id="d", user_id=USER, institution_id="ins_d", institution_name="Later",
                            status="pending", access_token="token-d"))
            await database.init_db()

    async def test_preflight_blocks_partial_or_inconsistent_lifecycle_schema(self):
        await self.seed()
        await self.legacy_shape()
        async with self.engine.begin() as connection:
            await connection.execute(text("ALTER TABLE items ADD COLUMN published BOOLEAN"))
        async with self.engine.begin() as connection:
            with self.assertRaisesRegex(LifecyclePreflightBlocked, "partially present: published"):
                await migrate_institution_lifecycle(connection)
        async with self.engine.connect() as connection:
            report = await institution_lifecycle_preflight(connection)
        self.assertEqual(lifecycle_preflight_errors(report, production=False),
                         ["lifecycle columns are partially present: published"])

    async def test_pending_items_never_join_scheduled_catch_up_or_manual_sync(self):
        await self.seed()
        self.assertEqual((await self.item("b")).sync_enabled, False)
        client, result = await self.sync({"a": ([], "a-2"), "b": ([], "b-2")})
        self.assertEqual(([item for item, _ in client.requests], set(result["items"])), (["a"], {"a"}))
        self.assertEqual((await self.item("b")).transactions_cursor, "b-1")

        seen = []

        async def fake_sync(user_id, **kwargs):
            seen.append((kwargs["trigger_source"], kwargs["item_ids"]))
            return {"status": "idle", "run_id": None, "items": {}}

        later = datetime(2030, 1, 1, tzinfo=timezone.utc)
        # Catch-up: b has never synced, so it would be due if it were eligible.
        await jobs.tick(USER, now=later, engine=self.engine, session_factory=self.sessions, sync=fake_sync)
        await jobs.request_sync(USER, session_factory=self.sessions)
        await jobs.tick(USER, now=later, engine=self.engine, session_factory=self.sessions, sync=fake_sync)
        self.assertEqual(seen, [("jobs", ["a"]), ("manual", ["a"])])
        with self.assertRaisesRegex(ValueError, "not active"):
            await jobs.request_sync(USER, ["b"], session_factory=self.sessions)
        # Explicit onboarding is the only ingestion path for a Pending Item.
        await self.onboard_pending(rows=[], cursor="b-2")
        self.assertEqual((await self.item("b")).transactions_cursor, "b-2")

    async def test_generic_status_patch_is_retired_and_fails_closed(self):
        from api.routes import plaid
        await self.seed()
        before = await self.schema_state()
        for item_id in ("a", "b", "missing"):
            with self.assertRaises(HTTPException) as retired:
                await plaid.retired_item_status_mutation(item_id)
            self.assertEqual(retired.exception.status_code, 410)
        self.assertEqual(await self.schema_state(), before)
        route = next(route for route in plaid.router.routes if route.path == "/plaid/items/{item_id}/status")
        self.assertEqual((route.methods, [param.name for param in route.dependant.body_params]), ({"PATCH"}, []))

    async def test_rejected_item_must_return_to_pending_before_normal_activation(self):
        await self.seed()
        before = await self.fingerprint()
        self.assertEqual(await self.onboarding("reject"), {"item_id": "b", "status": "disabled"})
        rejected = await self.fingerprint()
        self.assertEqual({key: rejected[key] for key in ("ledger", "transactions", "classifications")},
                         {key: before[key] for key in ("ledger", "transactions", "classifications")})
        async with self.sessions() as db:
            checks = await lifecycle.activation_checks(db, USER, "b")
        self.assertEqual((checks["transition"], checks["can_activate"], checks["checks"][0]["result"]),
                         (None, False, "fail"))
        for kind in ("activate", "reactivate"):
            with self.assertRaises(HTTPException) as refused:
                await self.preview(kind)
            self.assertEqual(refused.exception.status_code, 409)
            with self.assertRaises(HTTPException):
                await self.apply(kind, "0" * 64)
        self.assertEqual(await self.fingerprint(), rejected)

        with self.assertRaises(HTTPException):
            await self.onboarding("reject", item_id="a")
        self.assertEqual(await self.onboarding("retry_onboarding"), {"item_id": "b", "status": "pending"})
        with self.assertRaises(HTTPException):
            await self.onboarding("retry_onboarding")
        self.assertEqual(await self.fingerprint(), before)
        # Back in Pending it repeats the normal checks, preview and confirmed activation.
        async with self.sessions() as db:
            self.assertTrue((await lifecycle.activation_checks(db, USER, "b"))["can_activate"])
        _, result = await self.activate()
        self.assertEqual(result["status"], "active")
        self.assertEqual(await self.classification("a-zelle-in"), ("transfer", False, True))


    def plaid_routes(self, client=None):
        """Route-level calls on the synthetic schema; any Plaid use without a fake fails."""
        from api.routes import plaid
        stack = ExitStack()
        stack.enter_context(patch.object(plaid, "SessionLocal", self.sessions))
        stack.enter_context(patch.object(plaid, "get_client", side_effect=AssertionError("No Plaid call expected"))
                            if client is None else patch.object(plaid, "get_client", return_value=client))
        return plaid, stack

    async def test_split_import_and_normalization_are_pending_onboarding_only(self):
        await self.seed()
        await self.activate()
        async with self.sessions.begin() as db:
            db.add(Item(item_id="c", user_id=USER, institution_id="ins_c", institution_name="Rejected",
                        status="disabled", access_token="token-c"))
            db.add(Item(item_id="d", user_id=USER, institution_id="ins_d", institution_name="Later",
                        status="pending", access_token="token-d", transactions_cursor=None))
            await db.flush()
            db.add(Account(account_id="d-check", item_id="d", name="Later Checking", type="depository",
                           consumer_transactions_enabled=True))
        preview = await self.preview("deactivate")
        await self.apply("deactivate", preview["digest"])
        before = await self.fingerprint()
        plaid, stack = self.plaid_routes()
        with stack:
            for item_id in ("a", "b", "c"):  # active, deactivated, rejected
                for call in (plaid.get_transactions, plaid.normalize_transactions, plaid.get_accounts):
                    with self.assertRaises(HTTPException) as refused:
                        await call(item_id=item_id)
                    self.assertEqual(refused.exception.status_code, 409, (item_id, call.__name__))
            # The module helpers behind the routes are onboarding-scoped too.
            with self.assertRaises(HTTPException):
                await plaid.persist_consumer_transactions("a", "a-1", [], [], [], "a-x", 1)
            with self.assertRaises(HTTPException):
                await plaid.persist_account_metadata("a", [])
        self.assertEqual(await self.fingerprint(), before)

        # A Pending Item still onboards through the split routes.
        client = FakePlaid({"d": ([plaid_tx("d-1", "d-check", 18, 7, "MARKET", "FOOD_AND_DRINK")], "d-1")})
        plaid, stack = self.plaid_routes(client)
        with stack:
            result = await plaid.get_transactions(item_id="d")
            self.assertEqual(result["added_count"], 1)
            self.assertEqual((await plaid.normalize_transactions(item_id="d"))["normalized_count"], 1)
        self.assertEqual(client.requests, [("d", None)])
        self.assertEqual(await self.classification("d-1"), (None, None, None))
        after = await self.fingerprint()
        self.assertEqual(after["ledger"], before["ledger"])
        async with self.sessions() as db:
            # Only the new unpublished row differs; every existing classification is unchanged.
            self.assertEqual(await external_classifications(db, USER, excluded=("d-1",)), before["classifications"])

    async def test_active_account_metadata_maintenance_is_locked_and_narrow(self):
        await self.seed()
        await self.activate()
        await self.sync({"a": ([], "a-2"), "b": ([], "b-2")})
        before = await self.fingerprint()

        class Accounts:
            def __init__(self, rows):
                self.rows, self.calls = rows, 0

            def accounts_get(self, request):
                self.calls += 1
                return Response({"accounts": self.rows})

        def account(ident, name, kind="depository", subtype=None):
            return {"account_id": ident, "name": name, "type": kind, "subtype": subtype, "mask": "9999"}

        renamed = Accounts([account("a-check", "Chase Total Checking"),
                            account("a-invest", "Brokerage", "investment")])
        plaid, stack = self.plaid_routes(renamed)
        with stack:
            result = await plaid.repair_account_metadata("a")
        self.assertEqual(result["account_count"], 2)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Account, "a-check")).name, "Chase Total Checking")
        after = await self.fingerprint()
        self.assertEqual((after["transactions"], after["classifications"], after["items"]),
                         (before["transactions"], before["classifications"], before["items"]))
        self.assertEqual(lifecycle._financial_ledger(after["ledger"]), lifecycle._financial_ledger(before["ledger"]))

        refusals = [
            Accounts([account("a-check", "Checking"), account("a-invest", "Brokerage", "investment"),
                      account("a-new", "New Card", "credit")]),          # account set grew
            Accounts([account("a-check", "Checking")]),                    # account set shrank
            Accounts([account("a-check", "Checking", "credit"),
                      account("a-invest", "Brokerage", "investment")]),   # type drift
        ]
        for client in refusals:
            plaid, stack = self.plaid_routes(client)
            with stack, self.assertRaises(HTTPException) as refused:
                await plaid.repair_account_metadata("a")
            self.assertEqual(refused.exception.status_code, 409)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Account, "a-new"))
            self.assertEqual((await db.get(Account, "a-check")).type, "depository")
            self.assertEqual((await db.get(Account, "a-check")).name, "Chase Total Checking")
        self.assertEqual(await self.fingerprint(), after)
        # Maintenance is Active-only and refuses before any Plaid call.
        plaid, stack = self.plaid_routes()
        with stack:
            for item_id in ("b",):
                preview = await self.preview("deactivate")
                await self.apply("deactivate", preview["digest"])
                with self.assertRaises(HTTPException) as refused:
                    await plaid.repair_account_metadata(item_id)
                self.assertEqual(refused.exception.status_code, 409)

    async def test_retry_onboarding_only_changes_status(self):
        await self.seed()
        await self.onboarding("reject")
        # Plaid has newer data for b and the staged raw row drifts; retry must use neither.
        async with self.sessions.begin() as db:
            raw = await db.get(RawTransaction, "b-grocery")
            raw.payload = {**raw.payload, "amount": 99}
        staged = await self.schema_state()
        before = await self.fingerprint()
        plaid, stack = self.plaid_routes()
        with stack:
            result = await plaid.retry_item_onboarding("b")
        self.assertEqual(result, {"item_id": "b", "status": "pending"})
        item = await self.item("b")
        self.assertEqual((item.status, item.sync_enabled, item.published, item.activated_at, item.transactions_cursor),
                         ("pending", False, False, None, "b-1"))
        after = await self.schema_state()
        self.assertEqual((after[0], after[2]), (staged[0], staged[2]))  # columns and transactions untouched
        async with self.sessions() as db:
            self.assertEqual((await db.get(Transaction, "b-grocery")).amount, -30)  # not re-normalized
            self.assertIsNone((await db.get(Transaction, "b-grocery")).transaction_type)  # not classified
        current = await self.fingerprint()
        self.assertEqual({key: current[key] for key in ("ledger", "transactions", "classifications")},
                         {key: before[key] for key in ("ledger", "transactions", "classifications")})
        client, _ = await self.sync({"a": ([], "a-2"), "b": ([], "b-2")})
        self.assertEqual([item for item, _ in client.requests], ["a"])
        async with self.sessions() as db:
            checks = {check["id"]: check["result"]
                      for check in (await lifecycle.activation_checks(db, USER, "b"))["checks"]}
        self.assertEqual(checks["K6"], "fail")  # onboarding must be repeated before activation


if __name__ == "__main__":
    unittest.main()
