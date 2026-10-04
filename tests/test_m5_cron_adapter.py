"""M5 cron acceptance adapter: pure checks plus disposable-PostgreSQL deliveries.

The adapter runs in process through a minimal ASGI call; the Plaid client is
the database-driven synthetic FixtureClient. No network, no real SDK.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

from plaid.model.transactions_sync_request import TransactionsSyncRequest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from api import trigger_auth
from api.models import Account, Base, Item
from api.services import sync_all as service
from experiments.m5_cloud import cron_fixture
from experiments.m5_cloud import cron_jobs_app as cron_app
from experiments.m5_cloud.cron_fixture_client import FixtureClient, Plan

KEY = b"k" * 40
AUDIENCE = "pft-jobs-m5-test"
DATASET = "m5-" + "c" * 32
POOLER = "postgresql+asyncpg://pft_m5_jobs.acyghoemtdrilsdszolq:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres"


def sync_request(token, cursor=None):
    request = {"access_token": token}
    if cursor is not None:
        request["cursor"] = cursor
    return TransactionsSyncRequest(**request)


class FixtureClientTests(unittest.TestCase):
    def plan(self, **values):
        return Plan(**{"item_id": "a", "mode": "pages", "account_id": "account-a", "pages": 3,
                       "rows_per_page": 2, "generation": 1, **values})

    def test_pages_are_deterministic_and_published_generation_is_a_noop(self):
        client = FixtureClient({"synthetic-token-0": self.plan()})
        first = client.transactions_sync(sync_request("synthetic-token-0", "old"), _request_timeout=1).to_dict()
        again = client.transactions_sync(sync_request("synthetic-token-0", "old"), _request_timeout=1).to_dict()
        self.assertEqual(first, again)
        self.assertTrue(first["has_more"])
        cursor = first["next_cursor"]
        for _ in range(2):
            page = client.transactions_sync(sync_request("synthetic-token-0", cursor), _request_timeout=1).to_dict()
            cursor = page["next_cursor"]
        self.assertFalse(page["has_more"])
        done = client.transactions_sync(sync_request("synthetic-token-0", cursor), _request_timeout=1).to_dict()
        self.assertEqual((done["added"], done["next_cursor"]), ([], cursor))

    def test_mutation_failures_are_bounded_and_errors_are_plaid_shaped(self):
        client = FixtureClient({"synthetic-token-0": self.plan(mode="mutation", failures=1),
                                "synthetic-token-1": self.plan(item_id="b", mode="plaid_error")})
        first = client.transactions_sync(sync_request("synthetic-token-0"), _request_timeout=1).to_dict()
        with self.assertRaises(Exception) as caught:
            client.transactions_sync(sync_request("synthetic-token-0", first["next_cursor"]), _request_timeout=1)
        self.assertEqual(service._plaid_error(caught.exception).category, "pagination_mutation")
        client.transactions_sync(sync_request("synthetic-token-0", first["next_cursor"]), _request_timeout=1)
        with self.assertRaises(Exception) as caught:
            client.transactions_sync(sync_request("synthetic-token-1"), _request_timeout=1)
        self.assertEqual(service._plaid_error(caught.exception).category, "plaid_error")
        with self.assertRaisesRegex(RuntimeError, "Non-synthetic"):
            client.transactions_sync(sync_request("real-token"), _request_timeout=1)

    def test_plan_bounds(self):
        for values in ({"mode": "drop_tables"}, {"pages": 101}, {"rows_per_page": 501}, {"delay_s": 61}):
            with self.assertRaises(ValueError):
                self.plan(**values)


class SettingsAndPackagingTests(unittest.TestCase):
    def env(self, **overrides):
        return {"M5_CRON_ENABLED": "synthetic-20261002", "M5_CRON_DATABASE_URL": POOLER,
                "M5_TRIGGER_KEYS": "v1=" + "a" * 64, "M5_TRIGGER_AUDIENCE": AUDIENCE,
                "M5_CRON_DATASET_ID": DATASET, **overrides}

    def test_settings_pin_the_synthetic_pooler_and_forbid_plaid(self):
        config = cron_app.settings(self.env())
        self.assertEqual(config.keys, {"v1": b"a" * 64})
        self.assertTrue(config.require_backend_ssl)
        self.assertNotIn("a" * 64, repr(config))
        rejected = [{"M5_CRON_ENABLED": ""}, {"PLAID_SECRET": "x"}, {"PLAID_ENV": "production"},
                    {"M5_CRON_DATABASE_URL": POOLER.replace("pft_m5_jobs.", "postgres.")},
                    {"M5_CRON_DATABASE_URL": POOLER.replace("aws-0-us-east-1.pooler.supabase.com", "db.example.com")},
                    {"M5_CRON_DATABASE_URL": POOLER + "?sslmode=disable"}, {"M5_CRON_DATASET_ID": "prod"}]
        for override in rejected:
            with self.assertRaises(RuntimeError, msg=str(override)):
                cron_app.settings(self.env(**override))

    def test_bundle_has_one_entrypoint_and_no_financial_app(self):
        from scripts.pft_m5_stage_cron_bundle import stage
        with tempfile.TemporaryDirectory() as directory:
            result = stage(Path(directory) / "bundle")
            paths = {entry["path"] for entry in result["files"]}
        self.assertTrue({"main.py", "m5_cron_fixture.py", "api/trigger_auth.py", "api/jobs.py",
                         "requirements.txt", "vercel.json"} <= paths)
        self.assertFalse(paths & {"api/main.py", "api/sync_once.py", "api/migrate_once.py"})
        self.assertFalse(any(path.startswith((".env", "experiments/", "tests/")) for path in paths))

    def test_migration_rejects_non_synthetic_identifiers(self):
        for kwargs in ({"dataset_id": "prod"}, {"dataset_id": DATASET, "schema": "public; drop"}):
            with self.assertRaises(ValueError):
                cron_fixture.migration_sql(**kwargs)


async def asgi_post(app, path, headers, body):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
             "scheme": "https", "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
             "headers": [(name.lower().encode(), value.encode()) for name, value in headers]
             + [(b"content-length", str(len(body)).encode())],
             "client": ("127.0.0.1", 1), "server": ("test", 443)}
    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    messages = []

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return messages[0]["status"], json.loads(payload)


@unittest.skipUnless(os.environ.get("PFT_M5_TRIGGER_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class CronAdapterDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertEqual(default_engine.url.port, int(os.environ.get("PFT_M5_TRIGGER_TEST_PORT", "55439")))
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        suffix = uuid.uuid4().hex
        self.source, self.schema = "cron_src_" + suffix, "cron_" + suffix
        self.admin = create_async_engine(default_engine.url)
        async with self.admin.begin() as connection:
            await connection.execute(text(
                "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pft_m5_jobs') "
                "THEN CREATE ROLE pft_m5_jobs NOLOGIN; END IF; END $$"))
            await connection.execute(text("CREATE SCHEMA IF NOT EXISTS pft_m5_probe"))
            await connection.execute(text("CREATE TABLE IF NOT EXISTS pft_m5_probe.identity "
                                          "(singleton boolean PRIMARY KEY, project_ref text)"))
            await connection.execute(text("INSERT INTO pft_m5_probe.identity VALUES (true, :ref) "
                                          "ON CONFLICT DO NOTHING"), {"ref": cron_app.PROJECT_REF})
            await connection.execute(text(f'CREATE SCHEMA "{self.source}"'))
        source = create_async_engine(default_engine.url, connect_args={"server_settings": {"search_path": self.source}})
        async with source.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(source, expire_on_commit=False)
        async with sessions.begin() as db:
            for index in range(3):
                db.add(Item(item_id=f"item-{index}", user_id="synthetic-cloud-2610", institution_id=f"ins_{index}",
                            institution_name="Synthetic", status="active", access_token=f"synthetic-token-{index}",
                            transactions_cursor=f"start-{index}"))
                await db.flush()
                db.add(Account(account_id=f"account-{index}-0", item_id=f"item-{index}", name="Synthetic",
                               type="credit", consumer_transactions_enabled=True))
                db.add(Account(account_id=f"account-{index}-1", item_id=f"item-{index}", name="Synthetic",
                               type="depository", consumer_transactions_enabled=False))
        await source.dispose()
        async with self.admin.begin() as connection:
            raw = await connection.get_raw_connection()  # Multi-statement script: simple query protocol.
            await raw.driver_connection.execute(cron_fixture.migration_sql(
                DATASET, schema=self.schema, source=self.source))
            self.role = await connection.scalar(text("SELECT current_user"))
        self.config = cron_app.Settings(url=str(default_engine.url.render_as_string(hide_password=False)),
                                        keys={"v1": KEY}, audience=AUDIENCE, dataset_id=DATASET,
                                        database_role=self.role, require_backend_ssl=False)
        local = default_engine.url

        def engine_for(config):
            return create_async_engine(local, connect_args={"server_settings": {"search_path": self.schema}})

        self.patches = [patch.object(cron_app, "SCHEMA", self.schema),
                        patch.object(cron_app, "settings", return_value=self.config),
                        patch.object(cron_app, "engine_for", side_effect=engine_for)]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
            await connection.execute(text(f'DROP SCHEMA "{self.source}" CASCADE'))
        await self.admin.dispose()

    def headers(self, **overrides):
        signature = trigger_auth.sign(overrides.pop("secret", KEY), audience=AUDIENCE, key_id="v1",
                                      timestamp=int(time.time()), nonce=uuid.uuid4().hex, method="POST",
                                      path=cron_app.EXPECTED_PATH, payload={"kind": "tick"})
        return [(trigger_auth.HEADER, signature), ("content-type", "application/json"),
                ("x-pft-delivery-source", "test")]

    async def deliver(self, headers=None):
        return await asgi_post(cron_app.app, cron_app.EXPECTED_PATH, headers or self.headers(), b'{"kind":"tick"}')

    async def sql(self, statement, **params):
        async with self.admin.begin() as connection:
            result = await connection.execute(text(statement.replace("S.", f'"{self.schema}".')), params)
            return result.all() if result.returns_rows else None

    async def due(self, *items):
        await self.sql("UPDATE S.items SET last_sync_success_at = now() - interval '2 days' "
                       "WHERE item_id = ANY(:ids)", ids=list(items))

    async def test_migration_copies_fixture_and_grants_only_jobs(self):
        rows = await self.sql("SELECT user_id, count(*) FROM S.items GROUP BY user_id")
        self.assertEqual(rows, [("synthetic-cron", 3)])
        plans = await self.sql("SELECT item_id, mode, account_id FROM S.fixture_plan ORDER BY item_id")
        self.assertEqual(plans, [(f"item-{i}", "noop", f"account-{i}-0") for i in range(3)])
        privileges = dict(await self.sql(
            "SELECT p, has_table_privilege('pft_m5_jobs', :t, p) FROM unnest(ARRAY['SELECT','INSERT','UPDATE']) p",
            t=f'"{self.schema}".fixture_plan'))
        self.assertEqual(privileges, {"SELECT": True, "INSERT": False, "UPDATE": False})
        public = await self.sql("SELECT has_schema_privilege('public', :s, 'USAGE')", s=self.schema)
        self.assertEqual(public, [(False,)])

    async def test_label_schema_jobs_role_startup_and_synthetic_tick(self):
        from api import db as database
        from sqlalchemy.exc import DBAPIError
        from sqlalchemy.engine import make_url
        # Restore the private fixture (including ACLs) before exercising its role.
        # The public age restore test separately checks explicit re-grants when
        # pft_backup_restore intentionally uses --no-privileges.
        import subprocess
        from scripts import pft_backup_restore
        pg_bin = os.environ.get("PFT_PG_BIN_DIR", "/usr/lib/postgresql/16/bin")
        base = make_url(self.config.url)
        target = "pft_restore_cron_" + uuid.uuid4().hex[:12]
        env = {**os.environ, "PGHOST": base.host, "PGPORT": str(base.port),
               "PGUSER": base.username, "PGDATABASE": base.database,
               "PGPASSWORD": base.password or "", "PGCONNECT_TIMEOUT": "5"}
        def pg(tool, *args):
            return subprocess.run([str(Path(pg_bin) / tool), *args], env=env,
                                  capture_output=True, check=True, timeout=60)
        await self.sql("GRANT USAGE ON SCHEMA pft_m5_probe TO pft_m5_jobs")
        await self.sql("GRANT SELECT ON pft_m5_probe.identity TO pft_m5_jobs")
        await self.sql("INSERT INTO S.raw_transactions (transaction_id,item_id,account_id,transaction_date,payload,source,is_removed) VALUES ('cron-history','item-0','account-0-0','2026-10-01',CAST(:payload AS jsonb),'plaid',false)",
            payload=json.dumps({"transaction_id":"cron-history", "account_id":"account-0-0",
                "date":"2026-10-01", "amount":10, "name":"Synthetic equipment",
                "personal_finance_category":{"primary":"GENERAL_MERCHANDISE"}}))
        await self.sql("INSERT INTO S.transactions (transaction_id,account_id,transaction_date,amount,description,transaction_type,is_spending) VALUES ('cron-history','account-0-0','2026-10-01',-10,'Synthetic equipment','expense',true)")
        await self.sql("INSERT INTO S.transaction_label_definitions (label_id,user_id,name,normalized_name,is_system,created_by,updated_by) VALUES ('cron-history-active','synthetic-cron','Equipment','equipment',false,'test','test'),('cron-history-archived','synthetic-cron','Old','old',false,'test','test')")
        await self.sql("INSERT INTO S.manual_transaction_label_overrides (transaction_id,label,decision,created_by,updated_by) VALUES ('cron-history','cron-history-active','include','test','test'),('cron-history','cron-history-archived','include','test','test')")
        await self.sql("UPDATE S.transaction_label_definitions SET archived_at=now() WHERE label_id='cron-history-archived'")
        schemas = [self.schema, "pft_m5_probe"]
        before = pft_backup_restore.fingerprint(env, schemas, pg_bin)
        with tempfile.TemporaryDirectory() as directory:
            archive = str(Path(directory) / "cron.dump")
            pg("pg_dump", "-n", self.schema, "-n", "pft_m5_probe", "-Fc", "-f", archive)
            pg("createdb", target)
            self.addCleanup(lambda: pg("dropdb", "--if-exists", target))
            pg("pg_restore", "--exit-on-error", "-d", target, archive)
        self.assertEqual(pft_backup_restore.fingerprint(dict(env, PGDATABASE=target), schemas, pg_bin), before)
        login_role = "labels_cron_jobs_" + uuid.uuid4().hex[:12]
        await self.sql(f"CREATE ROLE {login_role} LOGIN PASSWORD 'synthetic'")
        await self.sql(f"GRANT pft_m5_jobs TO {login_role}")
        role_engine = create_async_engine(base.set(database=target, username=login_role, password="synthetic"),
            connect_args={"server_settings": {"search_path": self.schema}})
        try:
            with patch.object(database, "engine", role_engine):
                await database.verify_runtime_schema()
            async with role_engine.begin() as connection:
                self.assertEqual(await connection.scalar(text("SELECT count(*) FROM transaction_label_definitions")), 4)
                config = (await connection.execute(text("SELECT proconfig FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=:schema AND p.proname='pft_label_association_guard'"), {"schema": self.schema})).scalar_one()
                self.assertIn(f"search_path={self.schema}, pg_catalog", config)
                # Only the jobs role has schema access; fixture controls stay read-only.
                self.assertFalse(await connection.scalar(text("SELECT has_table_privilege(current_user,'fixture_plan','UPDATE')")))
            with self.assertRaises(DBAPIError):
                async with role_engine.begin() as connection:
                    await connection.execute(text("UPDATE fixture_plan SET generation=99"))
            # Execute a real tick using the restricted role, not the schema owner.
            restored_admin = create_async_engine(base.set(database=target))
            try:
                async with restored_admin.begin() as connection:
                    await connection.execute(text(f"UPDATE {self.schema}.fixture_plan SET mode='pages',pages=1,rows_per_page=2,generation=1 WHERE item_id='item-0'"))
                    await connection.execute(text(f"UPDATE {self.schema}.items SET last_sync_success_at=now()-interval '2 days' WHERE item_id='item-0'"))
            finally:
                await restored_admin.dispose()
            config = cron_app.Settings(url=self.config.url, keys={"v1": KEY}, audience=AUDIENCE,
                dataset_id=DATASET, database_role=login_role, require_backend_ssl=False)
            with patch.object(cron_app, "USER_ID", cron_fixture.USER_ID):
                result = await cron_app.run_delivery(role_engine, config,
                    received_at=datetime.now(timezone.utc), source="local-labels-integration")
            self.assertEqual((result["status"],result["synthetic_added_rows"]), ("success",2))
            async with role_engine.begin() as connection:
                self.assertEqual(await connection.scalar(text("SELECT count(*) FROM manual_transaction_label_overrides WHERE transaction_id='cron-history' AND decision='include'")), 2)
                self.assertTrue(await connection.scalar(text("SELECT archived_at IS NOT NULL FROM transaction_label_definitions WHERE label_id='cron-history-archived'")))
                tid = await connection.scalar(text("SELECT transaction_id FROM transactions LIMIT 1"))
                await connection.execute(text("INSERT INTO transaction_label_definitions (label_id,user_id,name,normalized_name,is_system,created_by,updated_by) VALUES ('cron-tech','synthetic-cron','Tech','tech',false,'test','test')"))
                await connection.execute(text("INSERT INTO manual_transaction_label_overrides (transaction_id,label,decision,created_by,updated_by) VALUES (:id,'cron-tech','include','test','test')"), {"id":tid})
            with self.assertRaises(DBAPIError):
                async with role_engine.begin() as connection:
                    await connection.execute(text("UPDATE transaction_label_definitions SET user_id='foreign-user' WHERE label_id='cron-tech'"))
        finally:
            await role_engine.dispose()
            await self.sql(f"DROP ROLE {login_role}")

    async def test_forged_and_replayed_deliveries_never_run(self):
        status, body = await self.deliver(self.headers(secret=b"x" * 40))
        self.assertEqual((status, body), (401, {"error": "bad signature", "handler_s": body["handler_s"]}))
        self.assertEqual(await self.sql("SELECT count(*) FROM S.deliveries"), [(0,)])
        headers = self.headers()
        status, body = await self.deliver(headers)
        self.assertEqual((status, body["status"]), (200, "idle"))
        status, body = await self.deliver(headers)
        self.assertEqual((status, body["error"]), (409, "replayed request"))
        rows = await self.sql("SELECT outcome, finished_at IS NOT NULL, source FROM S.deliveries")
        self.assertEqual(rows, [("idle", True, "test")])

    async def test_multipage_catch_up_publishes_each_due_item_once(self):
        await self.sql("UPDATE S.fixture_plan SET mode = 'pages', pages = 3, rows_per_page = 40, generation = 1")
        await self.due("item-0", "item-1", "item-2")
        status, body = await self.deliver()
        self.assertEqual((status, body["status"], body["synthetic_added_rows"]), (200, "success", 360))
        self.assertEqual(await self.sql("SELECT count(*) FROM S.raw_transactions"), [(360,)])
        cursors = await self.sql("SELECT transactions_cursor FROM S.items ORDER BY item_id")
        self.assertEqual(cursors, [(f"m5cron:item-{i}:g1:p3",) for i in range(3)])
        status, body = await self.deliver()
        self.assertEqual(body["status"], "idle")  # Not due again for 24 h.

    async def test_retry_and_partial_failure_are_durable(self):
        await self.sql("UPDATE S.fixture_plan SET mode = 'mutation', pages = 2, rows_per_page = 5, "
                       "generation = 1, failures = 1 WHERE item_id = 'item-0'")
        await self.sql("UPDATE S.fixture_plan SET mode = 'plaid_error' WHERE item_id = 'item-1'")
        await self.due("item-0", "item-1")
        status, body = await self.deliver()
        self.assertEqual((status, body["status"]), (200, "partial"))
        rows = await self.sql("SELECT item_id, status, error_category, retry_count FROM S.sync_item_runs "
                              "ORDER BY item_id")
        self.assertEqual(rows, [("item-0", "success", None, 1), ("item-1", "failed", "plaid_error", 0)])
        retry = await self.sql("SELECT next_sync_retry_at - now() FROM S.items WHERE item_id = 'item-1'")
        self.assertGreater(retry[0][0], timedelta(minutes=14))

    async def test_application_deadline_fails_the_run_without_publication(self):
        await self.sql("UPDATE S.fixture_plan SET mode = 'slow', pages = 3, rows_per_page = 5, generation = 1, "
                       "delay_s = 0.6 WHERE item_id = 'item-0'")
        await self.due("item-0")
        with patch.object(service, "MAX_RUN_SECONDS", 1):
            # The service raises after finalizing; the platform turns it into a 500.
            with self.assertRaises(TimeoutError):
                await self.deliver()
        rows = await self.sql("SELECT r.status, r.error_category, i.error_category FROM S.sync_runs r "
                              "JOIN S.sync_item_runs i USING (run_id)")
        self.assertEqual(rows, [("failed", "run_deadline", "run_deadline")])
        delivery = await self.sql("SELECT outcome, error_type, finished_at IS NOT NULL FROM S.deliveries")
        self.assertEqual(delivery, [(None, "TimeoutError", True)])
        self.assertEqual(await self.sql("SELECT count(*) FROM S.raw_transactions"), [(0,)])
        await asyncio.sleep(.7)  # Let the abandoned synthetic SDK thread finish.

    async def test_hang_request_is_one_shot(self):
        await self.sql("UPDATE S.fixture_plan SET mode = 'pages', pages = 1, rows_per_page = 3, generation = 1 "
                       "WHERE item_id = 'item-0'")
        await self.sql("UPDATE S.fixture_manifest SET hang_publication_s = 1")
        await self.due("item-0")
        started = time.monotonic()
        status, body = await self.deliver()
        self.assertGreaterEqual(time.monotonic() - started, 1)
        self.assertEqual((status, body["status"]), (200, "success"))
        self.assertEqual(await self.sql("SELECT hang_publication_s FROM S.fixture_manifest"), [(0,)])
        self.assertEqual(await self.sql("SELECT hang_publication_s FROM S.deliveries"), [(1,)])

    async def test_overlapping_valid_deliveries_run_once(self):
        await self.sql("UPDATE S.fixture_plan SET mode = 'slow', pages = 1, rows_per_page = 2, generation = 1, "
                       "delay_s = 0.5 WHERE item_id = 'item-0'")
        await self.due("item-0")
        results = await asyncio.gather(self.deliver(), self.deliver())
        self.assertEqual(sorted(body["status"] for _, body in results), ["busy", "success"])
        self.assertEqual(await self.sql("SELECT count(*) FROM S.sync_runs"), [(1,)])
        peaks = await self.sql("SELECT engine_checkout_peak FROM S.deliveries ORDER BY engine_checkout_peak")
        self.assertTrue(all(peak >= 1 for (peak,) in peaks))
