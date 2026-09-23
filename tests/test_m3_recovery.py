"""Populated recovery and schema gates on disposable PostgreSQL databases."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from datetime import date
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from api import backup, backup_crypto, db as database
from api.models import (Item, Account, RawTransaction, Transaction, StatementImportBatch,
                        StatementImportRow, ManualCategoryOverride, ManualClassificationOverride,
                        ManualTransactionLabelOverride, ManualBenefitCategoryOverride)
from api.routes import analytics, plaid


@unittest.skipUnless(os.environ.get("PFT_M3_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class RecoveryDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = database.engine.url
        self.assertEqual(url.port, 55439)
        self.assertIn(url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.source = "pft_m3_tests_" + uuid.uuid4().hex
        self.target = "pft_restore_" + uuid.uuid4().hex
        self.args = ["-h", url.host, "-p", str(url.port), "-U", url.username]
        self.env = os.environ.copy()
        self.env["PGPASSWORD"] = url.password or "synthetic"
        subprocess.run([str(backup.BIN / "createdb"), *self.args, self.source], env=self.env, check=True)
        self.url = url.set(database=self.source, password=url.password or "synthetic")
        self.engine = create_async_engine(self.url)
        with patch.object(database, "engine", self.engine):
            await database.init_db()

    async def asyncTearDown(self):
        await self.engine.dispose()
        for name in (self.target, self.source):
            subprocess.run([str(backup.BIN / "dropdb"), *self.args, "--if-exists", name],
                           env=self.env, check=True, stderr=subprocess.DEVNULL)

    async def snapshot(self, engine):
        result = {}
        async with engine.connect() as connection:
            tables = (await connection.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            ))).scalars().all()
            for table in tables:
                # Names come from our disposable database catalog, never external input.
                quoted = engine.dialect.identifier_preparer.quote(table)
                rows = (await connection.execute(text(
                    f'SELECT to_jsonb(t)::text FROM {quoted} t ORDER BY to_jsonb(t)::text COLLATE "C"'
                ))).scalars().all()
                result[table] = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())
        return result

    async def test_populated_encrypted_backup_recovers_without_source_files(self):
        recovery_key = Fernet.generate_key()
        token = plaid.ENCRYPTED_TOKEN_PREFIX + Fernet(recovery_key).encrypt(b"synthetic-token").decode()
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with sessions.begin() as session:
            session.add(Item(item_id="i", user_id="local-sandbox-user", institution_id="ins_synthetic",
                             institution_name="Synthetic", status="active", access_token=token,
                             transactions_cursor="synthetic-cursor"))
            await session.flush()
            session.add(Account(account_id="a", item_id="i", name="Synthetic", type="credit",
                                consumer_transactions_enabled=True))
            await session.flush()
            session.add(StatementImportBatch(batch_id="b", user_id="local-sandbox-user", item_id="i",
                account_id="a", adapter="synthetic", adapter_version="1", file_sha256="synthetic",
                preview_digest="synthetic", manifest={"evidence": "synthetic"}, status="applied", applied_by="test"))
            await session.flush()
            session.add(StatementImportRow(row_id="s", batch_id="b", source_record=1, source_line_end=1,
                fingerprint="synthetic", disposition="new", canonical={"amount": "-25.00"},
                source_evidence={"line": "synthetic-only"}))
            await session.flush()
            for tid, source, amount, removed in (("purchase", "statement", -25, False),
                                                  ("removed", "plaid", -99, True),
                                                  ("benefit", "plaid", 5, False)):
                session.add(RawTransaction(transaction_id=tid, item_id="i", account_id="a",
                    transaction_date=date(2026, 8, 1), payload={"synthetic": True}, source=source,
                    statement_row_id="s" if source == "statement" else None, is_removed=removed))
                await session.flush()
                session.add(Transaction(transaction_id=tid, account_id="a", transaction_date=date(2026, 8, 1),
                    amount=amount, description="Synthetic", statement_kind="Purchase" if source == "statement" else None,
                    transaction_type="card_benefit" if amount > 0 else "expense", is_spending=amount < 0))
            await session.flush()
            session.add_all([
                ManualCategoryOverride(transaction_id="purchase", category="GENERAL_MERCHANDISE", created_by="test", updated_by="test"),
                ManualClassificationOverride(transaction_id="purchase", transaction_type="expense", created_by="test", updated_by="test"),
                ManualTransactionLabelOverride(transaction_id="purchase", label="MEMBERSHIP", decision="include", created_by="test", updated_by="test"),
                ManualBenefitCategoryOverride(transaction_id="benefit", benefit_category="DINING_CREDIT", created_by="test", updated_by="test"),
            ])
        before = await self.snapshot(self.engine)
        with patch.object(analytics, "SessionLocal", sessions), patch.dict(os.environ, {"PLAID_PILOT_USER_ID": "local-sandbox-user"}):
            monthly = await analytics.monthly_spending("2026-08")
        self.assertEqual(monthly["net_spending"], "20.00")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "DATABASE_URL": self.url.render_as_string(hide_password=False),
            "EXPECTED_DATABASE_NAME": self.source, "POSTGRES_DB": self.source,
            "PFT_BACKUP_TEST_MODE": "true", "PFT_BACKUP_DIR": directory, "PFT_APP_COMMIT": "test",
        }):
            backup.backup("daily")
            archive = next(Path(directory).glob("*.dump"))
            encrypted = Path(directory) / "external.pftenc"
            with patch("getpass.getpass", return_value="synthetic recovery password"):
                backup_crypto.encrypt(archive, encrypted)
                archive.unlink()
                archive.with_suffix(".json").unlink()
                recovered = Path(directory) / "recovered.dump"
                backup_crypto.decrypt(encrypted, recovered)
            backup.restore(recovered, self.target)
        restored = create_async_engine(self.url.set(database=self.target), connect_args={
            "server_settings": {"default_transaction_read_only": "on"}})
        try:
            self.assertEqual(before, await self.snapshot(restored))
            with patch.object(database, "engine", restored):
                await database.verify_runtime_schema()
            with patch.object(analytics, "SessionLocal", async_sessionmaker(restored)), \
                 patch.dict(os.environ, {"PLAID_PILOT_USER_ID": "local-sandbox-user"}):
                self.assertEqual(monthly, await analytics.monthly_spending("2026-08"))
            async with restored.connect() as connection:
                restored_token = await connection.scalar(text("SELECT access_token FROM items WHERE item_id='i'"))
            self.assertEqual(Fernet(recovery_key).decrypt(restored_token.removeprefix(
                plaid.ENCRYPTED_TOKEN_PREFIX).encode()), b"synthetic-token")
            # Backing up and restoring must not mutate the source snapshot.
            self.assertEqual(before, await self.snapshot(self.engine))
        finally:
            await restored.dispose()

    async def test_schema_check_rejects_missing_override_table_and_m2_column(self):
        with patch.object(database, "engine", self.engine):
            await database.verify_runtime_schema()
            async with self.engine.begin() as connection:
                await connection.execute(text("DROP TABLE manual_category_overrides"))
                await connection.execute(text("ALTER TABLE items DROP COLUMN last_sync_success_at"))
            with self.assertRaisesRegex(RuntimeError, "items.last_sync_success_at"):
                await database.verify_runtime_schema()
            with self.assertRaisesRegex(RuntimeError, "manual_category_overrides"):
                await database.verify_runtime_schema()
