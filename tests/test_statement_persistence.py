"""All database tests run only in disposable schemas on the synthetic test port."""
import asyncio
import os
import json
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api.models import (Base, Item, Account, RawTransaction, Transaction, StatementImportBatch,
                        StatementImportRow, ManualClassificationOverride, ManualCategoryOverride)
from api.migrations import migrate_statement_imports
from api.routes import plaid, analytics, review
from api.statement_semantics import normalized_raw_values, statement_classification
from api.classification import effective_classification
from api.categories import effective_category
from statement_imports.robinhood import RobinhoodGoldCardCSV
from statement_imports.persistence import (preview, apply, rollback_preview, rollback, ImportBlocked,
                                           candidate_match, row_identity)


def csv_bytes(rows=None):
    rows = rows or ["2026-06-01,1:00 PM,Test,20,0,0,Posted,Purchase,Weee,Purchase",
                    "2026-06-02,1:00 PM,Test,-5,0,0,Posted,Refund,Shop,Refund",
                    "2026-06-03,1:00 PM,Test,-100,0,0,Posted,Payment,,Payment",
                    "2026-06-04,1:00 PM,Test,10,0,0,Posted,Fee,,Fee"]
    return (",".join(RobinhoodGoldCardCSV.headers) + "\n" + "\n".join(rows) + "\n").encode()


class StatementSemanticsTests(unittest.TestCase):
    def test_cli_preview_file_is_private_and_never_overwritten(self):
        from statement_imports.__main__ import main
        from unittest.mock import AsyncMock
        from contextlib import redirect_stdout, redirect_stderr
        import io
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "synthetic.csv"
            csv_path.write_bytes(csv_bytes())
            output = Path(directory) / "preview.json"
            args = ["statement-imports", "preview", str(csv_path), "--adapter", "robinhood-gold-card",
                    "--account-id", "card", "--output", str(output)]
            result = {"digest": "review-me", "blockers": [], "rows": []}
            with patch("sys.argv", args), patch("statement_imports.__main__.database_command",
                      new=AsyncMock(return_value=result)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(), 0)
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(SystemExit) as failure:
                    main()
                self.assertEqual(failure.exception.code, 2)
            self.assertEqual(json.loads(output.read_text()), result)

    def test_signs_and_source_kinds(self):
        for kind, amount, expected in [("purchase", -10, "expense"), ("fee", -1, "expense"),
                                       ("refund", 10, "refund"), ("payment", 10, "payment")]:
            self.assertEqual(statement_classification(kind, amount)[0], expected)
            self.assertIsNone(statement_classification(kind, -amount))
            self.assertIsNone(statement_classification(kind, 0))
        self.assertIsNone(statement_classification("unknown", -10))
        t = SimpleNamespace(amount=Decimal(-10), statement_kind="purchase", plaid_category=None,
                            account_id="a", description="", merchant_name="Weee")
        self.assertEqual(plaid.classify_transaction(t)[0], "expense")
        self.assertEqual(effective_category(t), "GROCERIES")

    def test_candidate_window_identity_and_source_normalization(self):
        self.assertTrue(candidate_match(date(2026, 1, 1), -10, "USD", date(2026, 1, 8), -10, "USD"))
        self.assertFalse(candidate_match(date(2026, 1, 1), -10, "USD", date(2026, 1, 9), -10, "USD"))
        self.assertFalse(candidate_match(date(2026, 1, 1), -10, "USD", date(2026, 1, 1), -10, "CAD"))
        row = RobinhoodGoldCardCSV().parse(csv_bytes()).transactions[0]
        self.assertTrue(row_identity("a", row).startswith("statement:"))
        self.assertNotEqual(row_identity("a", row), row_identity("b", row))
        raw = SimpleNamespace(source="statement", payload={"amount": "-10", "kind": "purchase"})
        self.assertEqual(normalized_raw_values(raw)["amount"], -10)
        raw = SimpleNamespace(source="plaid", payload={"amount": 10, "personal_finance_category": {"primary": "TRAVEL"}})
        self.assertEqual(normalized_raw_values(raw)["plaid_category"], "TRAVEL")
        self.assertIsNone(normalized_raw_values(raw)["statement_kind"])


@unittest.skipUnless(os.environ.get("PFT_STATEMENT_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class StatementDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine
        self.assertEqual(engine.url.port, 55439)
        self.assertIn(engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "statement_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(engine.url)
        async with self.admin.begin() as c:
            await c.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(engine.url, connect_args={"server_settings": {"search_path": self.schema}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.patches = ExitStack()
        self.patches.enter_context(patch.dict(os.environ, {"PLAID_PILOT_USER_ID": "test"}))
        for module in (plaid, analytics, review):
            self.patches.enter_context(patch.object(module, "SessionLocal", self.sessions))
        self.patches.enter_context(patch.object(plaid, "get_client", side_effect=AssertionError("No Plaid calls")))
        async with self.engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            db.add(Item(item_id="i", user_id="test", institution_id="ins_test", institution_name="Synthetic",
                        access_token="synthetic", status="pending", transactions_cursor="cursor-before"))
            await db.flush()
            db.add(Account(account_id="card", item_id="i", name="Synthetic", type="credit", subtype="credit card",
                           mask="1234", consumer_transactions_enabled=True))
        self.adapter = RobinhoodGoldCardCSV()

    async def asyncTearDown(self):
        self.patches.close()
        await self.engine.dispose()
        async with self.admin.begin() as c:
            await c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def preview(self, data=None, user="test"):
        async with self.sessions.begin() as db:
            await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            return await preview(db, user, "card", self.adapter, data or csv_bytes())

    async def apply(self, manifest, data=None):
        async with self.sessions.begin() as db:
            return await apply(db, "test", "card", self.adapter, data or csv_bytes(), None, manifest, manifest["digest"])

    async def test_apply_rerun_override_rollback_and_analytics(self):
        p = await self.preview()
        self.assertEqual(p["counts"], {"new": 4, "duplicate": 0, "ambiguous": 0, "skipped": 0})
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(StatementImportBatch)), 0)
        batch = await self.apply(p)
        self.assertEqual(batch["inserted"], 4)
        self.assertEqual((await self.apply(p))["inserted"], 0)
        fresh = await self.preview()
        self.assertEqual(fresh["counts"]["duplicate"], 4)
        self.assertEqual((await self.apply(fresh))["inserted"], 0)
        self.assertEqual(await analytics._active_analytics_rows(date(2026, 6, 1), date(2026, 6, 30)), [])
        async with self.sessions.begin() as db:
            self.assertEqual((await db.get(Item, "i")).transactions_cursor, "cursor-before")
            rows = (await db.execute(select(Transaction).order_by(Transaction.transaction_date))).scalars().all()
            self.assertEqual([t.transaction_type for t in rows], ["expense", "refund", "payment", "expense"])
            tid = rows[0].transaction_id
            db.add(ManualClassificationOverride(transaction_id=tid, transaction_type="adjustment", created_by="test", updated_by="test"))
            db.add(ManualCategoryOverride(transaction_id=tid, category="TRAVEL", created_by="test", updated_by="test"))
            (await db.get(Item, "i")).status = "active"
        await plaid.normalize_transactions(item_id="i")
        await plaid.classify_transactions()
        async with self.sessions() as db:
            t = await db.get(Transaction, tid)
            self.assertEqual(t.statement_kind, "purchase")
            self.assertIsNone(t.plaid_category)
            self.assertEqual(effective_classification(t, "adjustment")[0], "adjustment")
            self.assertEqual(effective_category(t, await db.get(ManualCategoryOverride, tid)), "TRAVEL")
        async with self.sessions.begin() as db:
            rp, _, _ = await rollback_preview(db, "test", batch["batch_id"])
            self.assertEqual(rp["override_rows"], 2)
            self.assertEqual(rp["blockers"], [])
            result = await rollback(db, "test", batch["batch_id"], rp["digest"], "Acceptance rollback")
            self.assertEqual(result["withdrawn"], 4)
        async with self.sessions.begin() as db:
            self.assertEqual((await rollback(db, "test", batch["batch_id"], rp["digest"], "Retry"))["withdrawn"], 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(Transaction)), 4)
            self.assertEqual(await db.scalar(select(func.count()).select_from(StatementImportRow)), 4)
            self.assertIsNotNone(await db.get(ManualClassificationOverride, tid))
        self.assertEqual(await analytics._active_analytics_rows(date(2026, 6, 1), date(2026, 6, 30)), [])
        with self.assertRaises(ImportBlocked):
            await self.apply(p)

    async def test_conflicts_and_stale_preview(self):
        p = await self.preview()
        async with self.sessions.begin() as db:
            db.add(RawTransaction(transaction_id="plaid-existing", item_id="i", account_id="card",
                transaction_date=date(2026, 6, 3), payload={"amount": 20, "iso_currency_code": "USD"}))
        with self.assertRaises(ImportBlocked):
            await self.apply(p)
        p = await self.preview()
        self.assertEqual(p["counts"]["ambiguous"], 1)
        with self.assertRaises(ImportBlocked):
            await self.apply(p)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(StatementImportBatch)), 0)
        data = csv_bytes(["2026-01-01,1:00 PM,Test,30,0,0,Posted,Purchase,Shop,Purchase"] * 2)
        self.assertEqual((await self.preview(data))["counts"]["ambiguous"], 2)

    async def test_overlap_blocks_cursor_and_source_collision(self):
        await self.apply(await self.preview())
        tx = {"transaction_id": "plaid-arrival", "account_id": "card", "date": date(2026, 6, 2),
              "amount": 20, "iso_currency_code": "USD"}
        with self.assertRaises(HTTPException):
            await plaid.persist_consumer_transactions("i", "cursor-before", [tx], [], [], "changed", 1)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "i")).transactions_cursor, "cursor-before")
            self.assertIsNone(await db.get(RawTransaction, "plaid-arrival"))
            ident = await db.scalar(select(RawTransaction.transaction_id))
        with self.assertRaises(HTTPException):
            await plaid.persist_consumer_transactions("i", "cursor-before", [], [], [{"transaction_id": ident}], "changed", 1)
        tx["transaction_id"] = ident
        with self.assertRaises(HTTPException):
            await plaid.persist_consumer_transactions("i", "cursor-before", [], [tx], [], "changed", 1)

    async def test_target_parse_errors_and_reexports(self):
        with self.assertRaises(ImportBlocked):
            await self.preview(user="wrong-user")
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = False
        with self.assertRaises(ImportBlocked):
            await self.preview()
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = True
        bad = csv_bytes(["2026-01-01,1:00 PM,Test,-30,0,0,Posted,Purchase,Shop,Purchase"])
        p = await self.preview(bad)
        self.assertIn("parsing_errors", p["blockers"])
        with self.assertRaises(ImportBlocked):
            await self.apply(p, bad)
        await self.apply(await self.preview())
        reexport = csv_bytes().replace(b"Test", b"Other")
        self.assertEqual((await self.preview(reexport))["counts"]["ambiguous"], 4)

    async def test_active_analytics_scoping_category_and_review(self):
        async with self.sessions.begin() as db:
            (await db.get(Item, "i")).status = "active"
        baseline = await analytics.monthly_spending(month="2026-06")
        batch = await self.apply(await self.preview())
        monthly = await analytics.monthly_spending(month="2026-06")
        self.assertEqual(monthly["gross_spending"], "30.00")
        self.assertEqual(monthly["refunds"], "5.00")
        self.assertEqual(monthly["net_spending"], "25.00")
        self.assertEqual(monthly["card_benefits"], "0.00")
        details = await analytics.analytics_transactions(month="2026-06", category="GROCERIES",
                      transaction_type="expense", limit=50, offset=0)
        self.assertEqual(details["total"], 1)
        tid = details["transactions"][0]["transaction_id"]
        await review.mutate_category(tid, "TRAVEL")
        changed = await analytics.monthly_spending(month="2026-06")
        self.assertEqual(changed["gross_spending"], monthly["gross_spending"])
        details = await analytics.analytics_transactions(month="2026-06", category="TRAVEL",
                      transaction_type="expense", limit=50, offset=0)
        self.assertEqual(details["total"], 1)
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = False
        self.assertEqual(await analytics.monthly_spending(month="2026-06"), baseline)
        self.assertEqual((await analytics.spending_breakdown(month="2026-06", group_by="account"))["groups"], [])
        self.assertEqual((await review.transactions_needing_review(limit=50, offset=0,
                         mode="credits_transfers", transaction_type="all"))["total"], 0)
        with self.assertRaises(HTTPException):
            await review.mutate_category(tid, "GROCERIES")
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).consumer_transactions_enabled = True
            rp, _, _ = await rollback_preview(db, "test", batch["batch_id"])
            await rollback(db, "test", batch["batch_id"], rp["digest"], "Synthetic rollback")
        self.assertEqual(await analytics.monthly_spending(month="2026-06"), baseline)
        self.assertEqual((await review.transactions_needing_review(limit=50, offset=0,
                         mode="credits_transfers", transaction_type="all"))["total"], 0)

    async def test_counterpart_review_preserves_existing_rows_and_rollback_gate(self):
        async with self.sessions.begin() as db:
            db.add(Item(item_id="other", user_id="test", institution_id="ins_other", institution_name="Other",
                        access_token="other-synthetic", status="active", transactions_cursor="other-cursor"))
            await db.flush()
            db.add(Account(account_id="checking", item_id="other", name="Checking", type="depository",
                           subtype="checking", consumer_transactions_enabled=True))
            db.add(RawTransaction(transaction_id="counterpart", item_id="other", account_id="checking",
                       transaction_date=date(2026, 6, 4), payload={"amount": 100, "iso_currency_code": "USD"}))
            await db.flush()
            db.add(Transaction(transaction_id="counterpart", account_id="checking", amount=-100,
                      transaction_date=date(2026, 6, 4), transaction_type="transfer", is_spending=False,
                      is_internal_transfer=False, plaid_category="TRANSFER_OUT"))
        p = await self.preview()
        self.assertEqual(p["payment_candidates"], [{"record": 3, "transaction_id": "counterpart"}])
        baseline = await analytics.monthly_spending(month="2026-06")
        batch = await self.apply(p)
        self.assertEqual(await analytics.monthly_spending(month="2026-06"), baseline)
        async with self.sessions() as db:
            other = await db.get(Item, "other")
            self.assertEqual((other.access_token, other.transactions_cursor), ("other-synthetic", "other-cursor"))
            self.assertFalse((await db.get(Transaction, "counterpart")).is_internal_transfer)
        await plaid.classify_transactions()
        async with self.sessions.begin() as db:
            self.assertTrue((await db.get(Transaction, "counterpart")).is_internal_transfer)
            rp, _, _ = await rollback_preview(db, "test", batch["batch_id"])
            self.assertIn("external_classifications_changed_requires_reconciliation", rp["blockers"])
            with self.assertRaises(ImportBlocked):
                await rollback(db, "test", batch["batch_id"], rp["digest"], "Unsafe rollback")

    async def test_settings_edit_currency_and_target_drift_block(self):
        p = await self.preview()
        edited = dict(p, through="2026-07-21")
        with self.assertRaises(ImportBlocked):
            await self.apply(edited)
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).type = "investment"
        with self.assertRaises(ImportBlocked):
            await self.apply(p)
        async with self.sessions.begin() as db:
            (await db.get(Account, "card")).type = "credit"
            (await db.get(Item, "i")).status = "disabled"
        with self.assertRaises(ImportBlocked):
            await self.apply(p)
        async with self.sessions.begin() as db:
            (await db.get(Item, "i")).status = "pending"
        from dataclasses import replace
        parsed = self.adapter.parse(csv_bytes())
        parsed.transactions[0] = replace(parsed.transactions[0], currency="CAD")
        with patch.object(self.adapter, "parse", return_value=parsed):
            p = await self.preview()
            self.assertIn("unsupported_currency", p["blockers"])
            with self.assertRaises(ImportBlocked):
                await self.apply(p)

    async def test_migration_with_existing_import_and_overrides(self):
        p = await self.preview()
        batch = await self.apply(p)
        async with self.sessions.begin() as db:
            tid = await db.scalar(select(Transaction.transaction_id))
            db.add(ManualClassificationOverride(transaction_id=tid, transaction_type="adjustment",
                   created_by="test", updated_by="test"))
        async with self.engine.begin() as c:
            await migrate_statement_imports(c)
            await migrate_statement_imports(c)
        async with self.sessions() as db:
            self.assertEqual((await db.get(StatementImportBatch, batch["batch_id"])).preview_digest, p["digest"])
            self.assertEqual((await db.get(ManualClassificationOverride, tid)).transaction_type, "adjustment")
            self.assertEqual(await db.scalar(select(func.count()).select_from(StatementImportRow)), 4)
            self.assertEqual((await db.get(RawTransaction, tid)).source, "statement")

    async def test_cli_database_dispatch_review_apply_and_rollback(self):
        from statement_imports.__main__ import database_command
        args = SimpleNamespace(command="preview", account_id="card", adapter="robinhood-gold-card", through=None)
        with patch("api.db.SessionLocal", self.sessions), patch("api.db.engine", self.engine):
            p = await database_command(args, csv_bytes())
            with tempfile.TemporaryDirectory() as directory:
                args.manifest = Path(directory) / "approved.json"
                args.manifest.write_text(json.dumps(p))
                args.command = "apply"
                args.confirm = p["digest"]
                batch = await database_command(args, csv_bytes())
            args.command = "rollback-preview"
            args.batch_id = batch["batch_id"]
            rp = await database_command(args, None)
            args.command = "rollback"
            args.confirm = rp["digest"]
            args.reason = "Synthetic CLI acceptance"
            self.assertEqual((await database_command(args, None))["withdrawn"], 4)

    async def test_concurrent_retries_and_atomic_failure(self):
        p = await self.preview()
        with patch("statement_imports.persistence.normalized_raw_values", side_effect=ValueError("synthetic failure")):
            with self.assertRaises(ValueError):
                await self.apply(p)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(StatementImportBatch)), 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(RawTransaction)), 0)
        results = await asyncio.gather(self.apply(p), self.apply(p))
        self.assertEqual(sorted(r["inserted"] for r in results), [0, 4])

    async def test_migration_preserves_legacy_data_and_is_idempotent(self):
        async with self.engine.begin() as c:
            await c.execute(text("ALTER TABLE raw_transactions DROP CONSTRAINT ck_raw_source"))
            await c.execute(text("ALTER TABLE raw_transactions DROP COLUMN statement_row_id"))
            await c.execute(text("ALTER TABLE raw_transactions DROP COLUMN source"))
            await c.execute(text("ALTER TABLE transactions DROP COLUMN statement_kind"))
            await c.execute(text("INSERT INTO raw_transactions (transaction_id,item_id,account_id,transaction_date,payload) "
                                 "VALUES ('legacy','i','card','2026-01-01','{\"amount\": 10}')"))
            await c.execute(text("INSERT INTO transactions (transaction_id,account_id,transaction_date,amount,transaction_type) "
                                 "VALUES ('legacy','card','2026-01-01',-10,'expense')"))
            await migrate_statement_imports(c)
            await migrate_statement_imports(c)
        async with self.sessions() as db:
            r = await db.get(RawTransaction, "legacy")
            self.assertEqual(r.source, "plaid")
            self.assertEqual(r.payload, {"amount": 10})
            self.assertIsNone(r.statement_row_id)
            self.assertEqual((await db.get(Transaction, "legacy")).transaction_type, "expense")
