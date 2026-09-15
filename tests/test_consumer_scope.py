import os
import unittest
import uuid
from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.consumer_scope import initial_consumer_scope, account_type_drift
from api.models import Base, Account, Item, RawTransaction, Transaction
from api.migrations import migrate_consumer_scope
from api.routes import plaid, review, analytics


class ScopePolicyTests(unittest.TestCase):
    def test_defaults_and_drift(self):
        for kind in ("credit", "depository"):
            self.assertTrue(initial_consumer_scope(kind))
        for kind in ("investment", "other", "loan", "", None):
            self.assertFalse(initial_consumer_scope(kind))
        a = SimpleNamespace(type="credit", subtype="credit card", name="Test",
                            mask="1234", consumer_transactions_enabled=False)
        self.assertIsNone(account_type_drift(a, "credit", "credit card"))
        drift = account_type_drift(a, "investment", "brokerage")
        self.assertFalse(drift["consumer_transactions_enabled"])
        self.assertEqual(drift["previous_type"], "credit")


@unittest.skipUnless(os.environ.get("PFT_CONSUMER_SYNTHETIC_TEST") == "1",
                     "isolated PostgreSQL opt-in")
class ConsumerDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine
        self.assertEqual(engine.url.port, 55439)
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "consumer_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(engine.url)
        async with self.admin.begin() as c:
            await c.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(engine.url, connect_args={
            "server_settings": {"search_path": self.schema}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = ExitStack()
        self.patches.enter_context(patch.dict(os.environ, {"PLAID_PILOT_USER_ID": "scope-test"}))
        for module in (plaid, review, analytics):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        async with self.engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            db.add(Item(item_id="i", user_id="scope-test", institution_id="ins_test",
                        institution_name="Synthetic", status="active", access_token="synthetic"))

    async def asyncTearDown(self):
        self.patches.close()
        await self.engine.dispose()
        async with self.admin.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def migrate(self):
        async with self.engine.begin() as c:
            await migrate_consumer_scope(c)

    def account(self, ident, kind="credit", subtype="credit card"):
        return dict(account_id=ident, name="Synthetic " + ident, type=kind, subtype=subtype, mask="1234")

    def tx(self, ident, account="card", amount=10):
        return dict(transaction_id=ident, account_id=account, date=date(2026, 8, 1),
                    amount=amount, name="Synthetic", personal_finance_category={"primary": "GENERAL_MERCHANDISE"})

    async def test_legacy_migration_preserves_rows_and_decisions(self):
        async with self.engine.begin() as c:
            await c.execute(text("ALTER TABLE accounts DROP COLUMN consumer_transactions_enabled"))
            await c.execute(text("INSERT INTO accounts (account_id,item_id,name,type) VALUES "
                                 "('card','i','Card','credit'),('bank','i','Bank','depository'),"
                                 "('invest','i','Invest','investment')"))
            await c.execute(text("INSERT INTO raw_transactions (transaction_id,item_id,account_id,transaction_date,payload) "
                                 "VALUES ('legacy','i','invest','2026-08-01','{}')"))
            await c.execute(text("INSERT INTO transactions (transaction_id,account_id,transaction_date,amount) "
                                 "VALUES ('legacy','invest','2026-08-01',10)"))
        await self.migrate()
        async with self.sessions.begin() as db:
            accounts = {a.account_id: a.consumer_transactions_enabled for a in (await db.execute(select(Account))).scalars()}
            self.assertEqual(accounts, {"card": True, "bank": True, "invest": False})
            await plaid.validate_consumer_activation(db, "i")  # legacy rows require no deletion
            (await db.get(Account, "bank")).consumer_transactions_enabled = False
            (await db.get(Account, "invest")).consumer_transactions_enabled = True
        await self.migrate()
        async with self.sessions() as db:
            self.assertFalse((await db.get(Account, "bank")).consumer_transactions_enabled)
            self.assertTrue((await db.get(Account, "invest")).consumer_transactions_enabled)
            self.assertIsNotNone(await db.get(Transaction, "legacy"))
        async with self.sessions.begin() as db:
            (await db.get(Account, "invest")).consumer_transactions_enabled = False
            db.add(RawTransaction(transaction_id="new-disabled", item_id="i", account_id="invest",
                                  transaction_date=date(2026, 8, 1), payload={}))
        await self.migrate()  # must not grandfather new bad rows
        async with self.sessions() as db:
            with self.assertRaises(HTTPException):
                await plaid.validate_consumer_activation(db, "i")

    async def test_discovery_ingestion_and_all_consumer_paths(self):
        await self.migrate()
        async with self.sessions() as db:
            with self.assertRaises(HTTPException):
                await plaid.validate_consumer_activation(db, "i")
        result = await plaid.persist_account_metadata("i", [
            self.account("card"), self.account("bank", "depository", "checking"),
            self.account("invest", "investment", "brokerage"),
            self.account("crypto", "investment", "crypto exchange"),
            self.account("roth", "investment", "roth"),
            self.account("other", None, None)])
        self.assertEqual([a["consumer_transactions_enabled"] for a in result["accounts"]],
                         [True, True, False, False, False, False])
        async with self.sessions.begin() as db:
            (await db.get(Account, "bank")).consumer_transactions_enabled = False
        refresh = await plaid.persist_account_metadata("i", [
            self.account("card", "investment", "brokerage"), self.account("bank", "depository", "checking"),
            self.account("invest", "credit", "credit card")])
        self.assertEqual([a["consumer_transactions_enabled"] for a in refresh["accounts"]], [True, False, False])
        self.assertEqual(len(refresh["type_drift"]), 2)
        # Restore metadata, not the domain decisions.
        await plaid.persist_account_metadata("i", [self.account("card"), self.account("invest", "investment", "brokerage")])
        result = await plaid.persist_consumer_transactions("i", None,
            [self.tx("expense"), self.tx("skip", "invest")], [], [], "c1", 1)
        self.assertEqual(result["added_count"], 1)
        self.assertEqual(result["skipped_disabled_counts"]["added"], 1)
        self.assertEqual(len(result["added"]), 1)
        with self.assertRaises(HTTPException):
            await plaid.persist_consumer_transactions("i", "c1", [self.tx("unknown", "missing")], [], [], "bad", 1)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "i")).transactions_cursor, "c1")
            self.assertIsNone(await db.get(RawTransaction, "skip"))
        result = await plaid.persist_consumer_transactions("i", "c1", [], [self.tx("skip", "invest")], [], "c2", 1)
        self.assertEqual(result["skipped_disabled_counts"]["modified"], 1)
        with self.assertRaises(HTTPException):
            await plaid.persist_consumer_transactions("i", "c1", [], [], [], "stale", 1)
        await plaid.normalize_transactions("i")
        await plaid.classify_transactions()
        before = analytics.summarize_monthly_transactions(await analytics._active_month_rows("2026-08"))
        # Seed excluded historical fixtures directly, never via consumer ingestion.
        async with self.sessions.begin() as db:
            for ident, amount, kind in (("disabled", 10, None), ("counterpart", -10, "transfer")):
                db.add(RawTransaction(transaction_id=ident, item_id="i", account_id="invest",
                    transaction_date=date(2026, 8, 1), payload=jsonable_encoder(self.tx(ident, "invest", -amount))))
                await db.flush()
                db.add(Transaction(transaction_id=ident, account_id="invest", transaction_date=date(2026, 8, 1),
                    amount=amount, transaction_type=kind, is_spending=False, is_internal_transfer=False))
        normalized = await plaid.normalize_transactions("i")
        self.assertEqual(normalized["normalized_count"], 1)
        classified = await plaid.classify_transactions()
        self.assertEqual(classified["classified_count"], 1)
        rows = await analytics._active_analytics_rows(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(len(rows), 1)
        self.assertEqual(analytics.summarize_monthly_transactions(rows), before)
        self.assertEqual(len(analytics.transaction_details(rows)), 1)
        self.assertEqual(len(await analytics._active_month_rows("2026-08", "GENERAL_MERCHANDISE")), 1)
        for group in ("account", "institution"):
            self.assertEqual(len(analytics.summarize_breakdown(rows, group)), 1)
            self.assertEqual(len((await analytics.spending_breakdown("2026-08", group))["groups"]), 1)
        self.assertEqual((await analytics.monthly_spending("2026-08"))["gross_spending"], "10.00")
        self.assertEqual((await analytics.spending_trend("2026-08"))["months"][-1]["net_spending"], "10.00")
        self.assertEqual((await analytics.analytics_transactions("2026-08", None, None, 50, 0, None, "invest"))["total"], 0)
        for mode in ("needs_review", "credits_transfers"):
            self.assertEqual((await review.transactions_needing_review(100, 0, mode, "all"))["total"], 0)
        for call in (
            review.set_override("disabled", review.OverrideRequest(transaction_type="refund")),
            review.clear_override("disabled"), review.mutate_category("disabled", "GROCERIES"),
            review.mutate_category("disabled", None),
        ):
            with self.assertRaises(HTTPException) as error:
                await call
            self.assertEqual(error.exception.status_code, 404)
        result = await plaid.persist_consumer_transactions("i", "c2", [], [],
            [{"transaction_id": "disabled"}, {"transaction_id": "absent"}, {"transaction_id": "expense"}], "c3", 1)
        self.assertEqual(result["removed_count"], 1)
        self.assertEqual(result["skipped_disabled_counts"]["removed"], 1)
        async with self.sessions() as db:
            self.assertFalse((await db.get(RawTransaction, "disabled")).is_removed)
            self.assertIsNone((await db.get(Transaction, "disabled")).transaction_type)
            self.assertFalse((await db.get(Transaction, "counterpart")).is_internal_transfer)
            self.assertEqual((await db.get(Item, "i")).transactions_cursor, "c3")
            with self.assertRaises(HTTPException):
                await plaid.validate_consumer_activation(db, "i")

    async def test_ownership_and_disabled_transfer_counterpart(self):
        await self.migrate()
        await plaid.persist_account_metadata("i", [self.account("card"),
            self.account("invest", "investment", "brokerage")])
        async with self.sessions.begin() as db:
            db.add(Item(item_id="other-item", user_id="scope-test", institution_id="ins_other",
                        institution_name="Other", status="active", access_token="synthetic"))
        with self.assertRaises(HTTPException):
            await plaid.persist_account_metadata("other-item", [self.account("new"), self.account("card")])
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Account, "new"))  # entire discovery rolled back
        credit = self.tx("credit", amount=-10)
        credit["personal_finance_category"]["primary"] = "TRANSFER_IN"
        await plaid.persist_consumer_transactions("i", None, [credit], [], [], "c1", 1)
        for added, modified, removed in (
            ([self.tx("credit")], [], []),
            ([], [self.tx("credit")], []),
            ([], [], [{"transaction_id": "credit"}]),
        ):
            with self.assertRaises(HTTPException):
                await plaid.persist_consumer_transactions("other-item", None, added, modified, removed, "bad", 1)
        async with self.sessions.begin() as db:
            db.add(RawTransaction(transaction_id="debit", item_id="i", account_id="invest",
                transaction_date=date(2026, 8, 1), payload={}))
            await db.flush()
            db.add(Transaction(transaction_id="debit", account_id="invest",
                transaction_date=date(2026, 8, 1), amount=-10, plaid_category="TRANSFER_OUT",
                transaction_type="transfer", is_spending=False, is_internal_transfer=False))
        await plaid.normalize_transactions("i")
        result = await plaid.classify_transactions()
        self.assertEqual(result["internal_transfer_matches"], 0)
        self.assertEqual(result["classified_count"], 1)
        credits = await review.transactions_needing_review(100, 0, "credits_transfers", "all")
        self.assertEqual(credits["total"], 1)
        self.assertEqual(credits["transactions"][0]["transaction_id"], "credit")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "other-item")).transactions_cursor, None)
            self.assertIsNot((await db.get(Transaction, "credit")).is_internal_transfer, True)
