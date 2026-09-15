import os
import unittest
import uuid
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.labels import (ALLOWED_LABELS, automatic_labels, effective_labels,
                        label_result, normalize_label_text)
from api.models import (Base, Account, Item, RawTransaction, Transaction,
                        ManualCategoryOverride, ManualTransactionLabelOverride)
from api.migrations import migrate_transaction_labels
from api.routes import analytics, plaid, review


def transaction(merchant=None, description=None):
    return SimpleNamespace(merchant_name=merchant, description=description)


class LabelRuleTests(unittest.TestCase):
    def test_china_vocabulary_and_conservative_rules(self):
        self.assertEqual(ALLOWED_LABELS, ("CHINA",))
        for value in (
            "Alipay*Meituan", "Weixin*Scan Qr Code", "Refund: Alipay*Meituan",
            "Refund: Weixin*Panduo Platfo", "AMAP TAXI", "Meituan",
            "Nanjing Metro", "Taobao", "Mixue Ice City", "Honey Snow Ice",
            "Jiming Soup Dum",
        ):
            with self.subTest(value=value):
                self.assertEqual(automatic_labels(transaction(value)), frozenset({"CHINA"}))
        self.assertEqual(automatic_labels(transaction(None, "Refund: Weixin*Meituan")),
                         frozenset({"CHINA"}))
        for value in ("Qrcode0645", "Scan Qr Code", "KFC", "Lawson", "Family Mart",
                      "Dalian Lawson", "Global-e", "Huangguohua", None):
            with self.subTest(value=value):
                self.assertEqual(automatic_labels(transaction(value)), frozenset())
        self.assertEqual(normalize_label_text("  Weixin*Manner Coffee "), "WEIXIN MANNER COFFEE")

    def test_effective_set_manual_include_exclude_and_clear_semantics(self):
        china = transaction("Alipay*Test")
        generic = transaction("Other")
        self.assertEqual(effective_labels(china), ("CHINA",))
        self.assertEqual(effective_labels(china, {"CHINA": "exclude"}), ())
        self.assertEqual(effective_labels(generic, {"CHINA": "include"}), ("CHINA",))
        override = SimpleNamespace(label="CHINA", decision="exclude", cleared_at=None)
        self.assertEqual(label_result(china, [override])["effective_labels"], [])
        override.cleared_at = SimpleNamespace()
        self.assertEqual(label_result(china, [override])["effective_labels"], ["CHINA"])


@unittest.skipUnless(os.environ.get("PFT_LABEL_SYNTHETIC_TEST") == "1",
                     "isolated PostgreSQL opt-in")
class LabelDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine
        self.assertEqual(engine.url.port, 55439)
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "label_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(engine.url)
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(engine.url, connect_args={
            "server_settings": {"search_path": self.schema},
        })
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = ExitStack()
        self.patches.enter_context(patch.dict(os.environ, {"PLAID_PILOT_USER_ID": "label-user"}))
        for module in (review, analytics, plaid):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            db.add(Item(item_id="item", user_id="label-user", institution_id="ins_test",
                        institution_name="Synthetic", status="pending", access_token="synthetic"))
            await db.flush()
            db.add(Account(account_id="card", item_id="item", name="Card", type="credit",
                           subtype="credit card", consumer_transactions_enabled=True))
            for ident, merchant, kind in (
                ("china", "Alipay*Meituan", "expense"),
                ("generic", "Qrcode0645", None),
            ):
                db.add(RawTransaction(transaction_id=ident, item_id="item", account_id="card",
                    transaction_date=date(2026, 7, 1), payload={"amount": 10}, source="plaid"))
                await db.flush()
                db.add(Transaction(transaction_id=ident, account_id="card",
                    transaction_date=date(2026, 7, 1), amount=Decimal("-10"),
                    merchant_name=merchant, description=merchant,
                    plaid_category="GENERAL_MERCHANDISE", transaction_type=kind,
                    is_spending=True if kind == "expense" else None,
                    is_internal_transfer=False))

    async def asyncTearDown(self):
        self.patches.close()
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def test_pending_manual_audit_noops_clear_and_classifier_survival(self):
        excluded = await review.mutate_label("china", "CHINA", "exclude")
        self.assertEqual(excluded["automatic_labels"], ["CHINA"])
        self.assertEqual(excluded["effective_labels"], [])
        async with self.sessions() as db:
            row = await db.get(ManualTransactionLabelOverride, ("china", "CHINA"))
            created, updated = row.created_at, row.updated_at
        await review.mutate_label("china", "CHINA", "exclude")
        async with self.sessions() as db:
            row = await db.get(ManualTransactionLabelOverride, ("china", "CHINA"))
            self.assertEqual((row.created_at, row.updated_at), (created, updated))
        included = await review.mutate_label("generic", "CHINA", "include")
        self.assertEqual(included["automatic_labels"], [])
        self.assertEqual(included["effective_labels"], ["CHINA"])
        await plaid.classify_transactions()
        async with self.sessions() as db:
            self.assertEqual((await db.get(ManualTransactionLabelOverride,
                                           ("generic", "CHINA"))).decision, "include")
        cleared = await review.mutate_label("china", "CHINA", None)
        self.assertEqual(cleared["effective_labels"], ["CHINA"])
        async with self.sessions() as db:
            row = await db.get(ManualTransactionLabelOverride, ("china", "CHINA"))
            self.assertIsNone(row.decision)
            self.assertIsNotNone(row.cleared_at)
            created_after_clear, updated_after_clear = row.created_at, row.updated_at
        await review.mutate_label("china", "CHINA", None)
        async with self.sessions() as db:
            row = await db.get(ManualTransactionLabelOverride, ("china", "CHINA"))
            self.assertEqual(row.created_at, created_after_clear)
            self.assertEqual(row.updated_at, updated_after_clear)

    async def test_api_review_analytics_filter_and_financial_invariance(self):
        self.assertEqual(await review.label_options(), {"labels": [{"value": "CHINA", "label": "China"}]})
        await review.mutate_label("generic", "CHINA", "include")
        async with self.sessions.begin() as db:
            (await db.get(Item, "item")).status = "active"
        monthly_before = await analytics.monthly_spending(month="2026-07")
        review_page = await review.transactions_needing_review(
            limit=100, offset=0, mode="needs_review", transaction_type="all"
        )
        self.assertEqual(review_page["total"], 1)
        self.assertEqual(review_page["transactions"][0]["effective_labels"], ["CHINA"])
        all_details = await analytics.analytics_transactions(
            month="2026-07", category=None, transaction_type=None, limit=50, offset=0,
            institution_id=None, account_id=None, label=None,
        )
        china_details = await analytics.analytics_transactions(
            month="2026-07", category=None, transaction_type=None, limit=1, offset=0,
            institution_id=None, account_id=None, label="CHINA",
        )
        self.assertEqual(all_details["total"], 2)
        self.assertEqual(china_details["total"], 2)
        self.assertEqual(china_details["transaction_count"], 1)
        self.assertIn("CHINA", china_details["transactions"][0]["effective_labels"])
        self.assertEqual(await analytics.monthly_spending(month="2026-07"), monthly_before)
        with self.assertRaises(HTTPException) as invalid:
            await analytics.analytics_transactions(month="2026-07", category=None,
                transaction_type=None, limit=50, offset=0, institution_id=None,
                account_id=None, label="TRAVEL")
        self.assertEqual(invalid.exception.status_code, 422)

    async def test_scope_and_validation(self):
        with self.assertRaises(HTTPException) as invalid:
            await review.mutate_label("china", "TRAVEL", "include")
        self.assertEqual(invalid.exception.status_code, 422)
        with self.assertRaises(HTTPException) as missing:
            await review.mutate_label("missing", "CHINA", "include")
        self.assertEqual(missing.exception.status_code, 404)
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = False
        with self.assertRaises(HTTPException):
            await review.mutate_label("china", "CHINA", "include")
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = True
            (await db.get(RawTransaction, "china")).is_removed = True
        with self.assertRaises(HTTPException):
            await review.mutate_label("china", "CHINA", "include")

    async def test_atomic_bulk_label_and_category_validation(self):
        async with self.sessions.begin() as db:
            (await db.get(Item, "item")).status = "active"
        result = await review.bulk_edit_transactions(review.BulkEditRequest(
            transaction_ids=["generic", "china"], operation="include_label", label="CHINA"))
        self.assertEqual((result["selected_count"], result["changed_count"]), (2, 2))
        repeated = await review.bulk_edit_transactions(review.BulkEditRequest(
            transaction_ids=["china", "generic"], operation="include_label", label="CHINA"))
        self.assertEqual((repeated["changed_count"], repeated["unchanged_count"]), (0, 2))
        async with self.sessions() as db:
            decisions = (await db.execute(select(ManualTransactionLabelOverride.decision))) \
                .scalars().all()
            self.assertEqual(decisions, ["include", "include"])

        with self.assertRaises(HTTPException) as missing:
            await review.bulk_edit_transactions(review.BulkEditRequest(
                transaction_ids=["china", "missing"], operation="exclude_label", label="CHINA"))
        self.assertEqual(missing.exception.status_code, 404)
        async with self.sessions() as db:
            decisions = (await db.execute(select(ManualTransactionLabelOverride.decision))) \
                .scalars().all()
            self.assertEqual(decisions, ["include", "include"])

        with self.assertRaises(HTTPException) as ineligible:
            await review.bulk_edit_transactions(review.BulkEditRequest(
                transaction_ids=["china", "generic"], operation="set_category",
                category="GROCERIES"))
        self.assertEqual(ineligible.exception.status_code, 422)
        self.assertEqual(ineligible.exception.detail["ineligible_count"], 1)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count(ManualCategoryOverride.transaction_id))), 0)
        categorized = await review.bulk_edit_transactions(review.BulkEditRequest(
            transaction_ids=["china"], operation="set_category", category="GROCERIES"))
        self.assertEqual((categorized["changed_count"], categorized["unchanged_count"]), (1, 0))
        restored = await review.bulk_edit_transactions(review.BulkEditRequest(
            transaction_ids=["china", "generic"], operation="restore_label_auto", label="CHINA"))
        self.assertEqual((restored["changed_count"], restored["unchanged_count"]), (2, 0))
        restored_by_id = {result["transaction_id"]: result for result in restored["results"]}
        self.assertEqual(restored_by_id["china"]["effective_labels"], ["CHINA"])
        self.assertEqual(restored_by_id["generic"]["effective_labels"], [])

    async def test_migration_idempotency_and_existing_row_preservation(self):
        await review.mutate_label("generic", "CHINA", "include")
        async with self.sessions() as db:
            before = (await db.execute(select(ManualTransactionLabelOverride))).scalars().one()
            snapshot = (before.transaction_id, before.label, before.decision,
                        before.created_by, before.created_at, before.updated_at)
        async with self.engine.begin() as connection:
            await migrate_transaction_labels(connection)
            await migrate_transaction_labels(connection)
        async with self.sessions() as db:
            after = (await db.execute(select(ManualTransactionLabelOverride))).scalars().one()
            self.assertEqual(snapshot, (after.transaction_id, after.label, after.decision,
                                        after.created_by, after.created_at, after.updated_at))
        async with self.sessions() as db:
            with self.assertRaises(IntegrityError):
                async with db.begin():
                    db.add(ManualTransactionLabelOverride(transaction_id="china", label="TRAVEL",
                           decision="include", created_by="test", updated_by="test"))
