"""M4 scheduling tests use only disposable PostgreSQL schemas and mock syncs."""

import asyncio
import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine

from api.jobs import request_sync, tick
from api.models import Account, Base, Item, SyncItemRun, SyncRun, SyncRuntimeState
from api.services import sync_all as service
from api.services.sync_state import acquire_session_lock
from api.migrations import migrate_sync_runs
from tests.test_sync_all import Client, page, plaid_error, tx


@unittest.skipUnless(os.environ.get("PFT_M4_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class JobsDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertEqual(default_engine.url.port, 55439)
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "jobs_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(default_engine.url)
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(default_engine.url, connect_args={
            "server_settings": {"search_path": self.schema}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            for ident in ("a", "b"):
                db.add(Item(item_id=ident, user_id="synthetic-user", institution_id="ins_" + ident,
                            institution_name="Synthetic", status="active", access_token="mock",
                            transactions_cursor="start"))
                await db.flush()
                db.add(Account(account_id="account-" + ident, item_id=ident, name="Synthetic",
                               type="credit", consumer_transactions_enabled=True))
        self.clock = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

    async def asyncTearDown(self):
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def poll(self, sync, *, now=None, backup_fn=None):
        return await tick("synthetic-user", now=now or self.clock, engine=self.engine,
                          session_factory=self.sessions, sync=sync, backup_fn=backup_fn)

    async def request(self, ids=None):
        return await request_sync("synthetic-user", ids, session_factory=self.sessions)

    async def test_startup_daily_sleep_resume_and_backup_independence(self):
        calls = []

        async def sync(user_id, **kwargs):
            if not kwargs["item_ids"]:
                return {"status": "idle"}
            calls.append(kwargs["item_ids"])
            async with self.sessions.begin() as db:
                await db.execute(update(Item).where(Item.item_id.in_(kwargs["item_ids"]))
                                 .values(last_sync_success_at=self.clock))
            return {"status": "success"}

        backups = []
        self.assertEqual((await self.poll(sync, backup_fn=lambda kind: backups.append(kind)))["status"],
                         "success")
        self.assertEqual(calls, [["a", "b"]])
        self.assertEqual(backups, ["daily"])
        self.assertEqual((await self.poll(sync))["status"], "idle")
        self.clock += timedelta(hours=23, minutes=59)
        self.assertEqual((await self.poll(sync))["status"], "idle")
        self.clock += timedelta(minutes=1)
        await self.poll(sync)
        self.assertEqual(calls, [["a", "b"], ["a", "b"]])
        self.clock += timedelta(days=3)
        await self.poll(sync)
        self.assertEqual(calls, [["a", "b"]] * 3)  # one catch-up, not three

    async def test_retry_backoff_and_manual_bypass_of_due_time(self):
        from api.services.sync_all import _schedule_result

        async with self.sessions.begin() as db:
            await db.execute(update(Item).values(last_sync_success_at=self.clock))
        calls = []

        async def sync(user_id, **kwargs):
            if not kwargs["item_ids"]:
                return {"status": "idle"}
            calls.append(kwargs["item_ids"])
            async with self.sessions.begin() as db:
                for ident in kwargs["item_ids"]:
                    item = await db.get(Item, ident, with_for_update=True)
                    for key, value in _schedule_result(item, {"status": "waiting",
                                                       "error_category": "not_ready"}, self.clock).items():
                        setattr(item, key, value)
            return {"status": "waiting"}

        await self.request(["a"])
        await self.poll(sync)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).next_sync_retry_at,
                             self.clock + timedelta(minutes=15))
        self.assertEqual((await self.poll(sync))["status"], "idle")
        self.clock += timedelta(days=1)
        await self.poll(sync)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).next_sync_retry_at,
                             self.clock + timedelta(hours=1))
        self.assertEqual(calls, [["a"], ["a", "b"]])
        await self.request(["a"])
        await self.poll(sync)
        self.assertEqual(calls[-1], ["a"])  # manual bypasses retry due time

    async def test_backup_failure_does_not_block_sync_or_claim_success(self):
        calls = []

        async def sync(user_id, **kwargs):
            calls.append(kwargs["item_ids"])
            return {"status": "success"}

        def failed_backup(kind):
            raise OSError("synthetic backup failure")

        self.assertEqual((await self.poll(sync, backup_fn=failed_backup))["status"], "success")
        self.assertEqual(calls, [["a", "b"]])
        async with self.sessions() as db:
            self.assertIsNone((await db.get(SyncRuntimeState, "synthetic-user")).last_backup_at)

    async def test_dedup_midrun_and_restart(self):
        first = await self.request(["a"])
        self.assertEqual((await self.request(["b"]))["requested_sequence"],
                         first["requested_sequence"])
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def sync(user_id, **kwargs):
            calls.append(kwargs["item_ids"])
            started.set()
            await release.wait()
            return {"status": "success"}

        running = asyncio.create_task(self.poll(sync))
        await started.wait()
        second = await self.request(["b"])
        self.assertEqual(second["requested_sequence"], first["requested_sequence"] + 1)
        self.assertEqual((await self.request(["b"]))["requested_sequence"],
                         second["requested_sequence"])
        self.assertEqual((await self.poll(sync))["status"], "busy")
        release.set()
        await running
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual((state.handled_sequence, state.requested_sequence), (1, 2))
        await self.poll(sync)  # a new jobs process sees the persisted pending request
        self.assertEqual(calls, [["a", "b"], ["b"]])

    async def test_lost_jobs_lock_keeps_request_for_restart(self):
        await self.request(["a"])

        async def sync(user_id, **kwargs):
            async with self.admin.begin() as admin:
                pid = await admin.scalar(text(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
                    "AND objid::bigint=(hashtextextended(:key,0)&4294967295)"),
                    {"key": "pft-jobs:synthetic-user"})
                self.assertIsNotNone(pid)
                await admin.scalar(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            return {"status": "success"}

        with self.assertRaises(RuntimeError):
            await self.poll(sync)
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual(state.handled_sequence, 0)
            self.assertEqual(state.running_sequence, 1)
        await self.poll(lambda user_id, **kwargs: asyncio.sleep(0, result={"status": "success"}))
        async with self.sessions() as db:
            self.assertEqual((await db.get(SyncRuntimeState, "synthetic-user")).handled_sequence, 1)

    def real_sync(self, client):
        async def sync(user_id, **kwargs):
            with patch.object(service, "utcnow", return_value=self.clock):
                return await service.sync_all(user_id, client=client, **kwargs)
        return sync

    async def test_recent_success_does_not_delay_due_retry(self):
        async with self.sessions.begin() as db:
            await db.execute(update(Item).values(last_sync_success_at=self.clock))
        await self.request(["a"])
        client = Client({"mock": [plaid_error("PRODUCT_NOT_READY"), page("retried")]})
        self.assertEqual((await self.poll(self.real_sync(client)))["status"], "waiting")
        self.clock += timedelta(minutes=14)
        self.assertEqual((await self.poll(self.real_sync(client)))["status"], "idle")
        self.clock += timedelta(minutes=1)
        self.assertEqual((await self.poll(self.real_sync(client)))["status"], "success")
        self.assertEqual(len(client.sync_requests), 2)

    async def test_concurrent_initial_requests_coalesce_without_creation_race(self):
        responses = await asyncio.gather(*[self.request([ident]) for ident in ["a", "b"] * 8])
        self.assertEqual({r["requested_sequence"] for r in responses}, {1})
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual(state.requested_item_ids, ["a", "b"])

    async def test_busy_sync_lock_leaves_clicks_coalesced(self):
        await self.request(["a"])
        async with self.admin.connect() as other:
            acquired, _ = await acquire_session_lock(other, "pft-sync:synthetic-user")
            self.assertTrue(acquired)
            try:
                self.assertEqual((await self.poll(self.real_sync(Client({}))))["status"], "busy")
                self.assertEqual((await self.request(["b"]))["requested_sequence"], 1)
            finally:
                await other.scalar(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"),
                                   {"key": "pft-sync:synthetic-user"})
        result = await self.poll(self.real_sync(Client({"mock": [page("a-done"), page("b-done")]})))
        self.assertEqual(set(result["items"]), {"a", "b"})
        async with self.sessions() as db:
            self.assertEqual((await db.get(SyncRuntimeState, "synthetic-user")).handled_sequence, 1)

    async def test_crash_after_commit_does_not_replay_and_preserves_midrun_request(self):
        await self.request(["a"])
        original = service._fetch_item

        async def receive_request(*args):
            result = await original(*args)
            await self.request(["b"])
            return result

        async def crash_after_sync(user_id, **kwargs):
            await self.real_sync(Client({"mock": [page("committed-a")]}))(user_id, **kwargs)
            raise asyncio.CancelledError()

        with patch.object(service, "_fetch_item", side_effect=receive_request):
            with self.assertRaises(asyncio.CancelledError):
                await self.poll(crash_after_sync)
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual((state.handled_sequence, state.requested_sequence), (1, 2))
            self.assertIsNone(state.running_sequence)
            self.assertIsNotNone(state.last_published_run_id)
        await self.poll(self.real_sync(Client({"mock": [page("committed-b")]})))
        async with self.sessions() as db:
            runs = (await db.execute(select(SyncRun).order_by(SyncRun.started_at, SyncRun.request_sequence))).scalars().all()
            self.assertEqual([r.request_sequence for r in runs], [1, 2])
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "committed-a")
            self.assertEqual((await db.get(Item, "b")).transactions_cursor, "committed-b")

    async def test_exception_records_backoff_and_finishes_manual_request(self):
        async with self.sessions.begin() as db:
            await db.execute(update(Item).values(last_sync_success_at=self.clock))
        await self.request(["a"])
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            await self.poll(self.real_sync(Client({"mock": [RuntimeError("synthetic")]})))
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual(state.handled_sequence, 1)
            self.assertIsNone(state.running_sequence)
            self.assertEqual((await db.get(Item, "a")).next_sync_retry_at,
                             self.clock + timedelta(minutes=15))
        self.clock += timedelta(minutes=1)
        self.assertEqual((await self.poll(self.real_sync(Client({}))))["status"], "idle")

    async def test_idle_restart_reconciles_interrupted_run(self):
        async with self.sessions.begin() as db:
            await db.execute(update(Item).values(sync_paused=True))
            db.add(SyncRun(run_id="crashed", user_id="synthetic-user", trigger_source="jobs",
                           started_at=self.clock, status="running"))
            await db.flush()
            db.add(SyncItemRun(run_id="crashed", item_id="a", started_at=self.clock,
                               status="running", phase="fetch"))
        self.assertEqual((await self.poll(self.real_sync(Client({}))))["status"], "idle")
        async with self.sessions() as db:
            self.assertEqual((await db.get(SyncRun, "crashed")).status, "interrupted")
            self.assertEqual((await db.get(SyncItemRun, ("crashed", "a"))).status, "interrupted")

    async def test_scheduled_scope_rechecked_after_backup_or_other_sync(self):
        client = Client({})

        async def concurrent_success(user_id, **kwargs):
            async with self.sessions.begin() as db:
                await db.execute(update(Item).values(last_sync_success_at=self.clock))
            return await self.real_sync(client)(user_id, **kwargs)

        self.assertEqual((await self.poll(concurrent_success))["status"], "idle")
        self.assertEqual(client.sync_requests, [])

    async def test_lost_jobs_owner_cannot_publish_with_live_sync_lock(self):
        await self.request(["a"])
        original = service._fetch_item

        async def lose_jobs_owner(*args):
            result = await original(*args)
            async with self.admin.begin() as db:
                pid = await db.scalar(text(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
                    "AND objid::bigint=(hashtextextended(:key,0)&4294967295)"),
                    {"key": "pft-jobs:synthetic-user"})
                self.assertIsNotNone(pid)
                await db.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            return result

        with patch.object(service, "_fetch_item", side_effect=lose_jobs_owner):
            with self.assertRaises(RuntimeError):
                await self.poll(self.real_sync(Client({"mock": [page("discarded")]})))
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "start")
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual(state.handled_sequence, 0)
            self.assertIsNone(state.last_published_run_id)
        self.assertEqual((await self.poll(self.real_sync(Client({"mock": [page("recovered")]}))))["status"], "success")

    async def test_lost_owner_during_backup_stops_old_worker_before_sync(self):
        entered = asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()

        def backup(kind):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise TimeoutError("test backup was not released")

        client = Client({})
        task = asyncio.create_task(self.poll(self.real_sync(client), backup_fn=backup))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            async with self.admin.begin() as db:
                pid = await db.scalar(text(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
                    "AND objid::bigint=(hashtextextended(:key,0)&4294967295)"),
                    {"key": "pft-jobs:synthetic-user"})
                self.assertIsNotNone(pid)
                await db.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        finally:
            release.set()
        with self.assertRaises(RuntimeError):
            await task
        async with self.sessions() as db:
            self.assertIsNone((await db.get(SyncRuntimeState, "synthetic-user")).last_backup_at)
        self.assertEqual(client.sync_requests, [])

    async def test_cancelled_lock_acquisition_does_not_leak_pooled_lock(self):
        key = "pft-jobs:synthetic-user"
        async with self.engine.connect() as owner:
            with patch.object(AsyncConnection, "commit", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    await acquire_session_lock(owner, key)
        async with self.admin.connect() as other:
            self.assertTrue(await other.scalar(text(
                "SELECT pg_try_advisory_lock(hashtextextended(:key,0))"), {"key": key}))
            await other.scalar(text("SELECT pg_advisory_unlock(hashtextextended(:key,0))"), {"key": key})

    async def test_global_rollback_records_retry_without_publication(self):
        await self.request(["a"])
        with patch.object(service, "classify_active_transactions", side_effect=RuntimeError("synthetic")):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                await self.poll(self.real_sync(Client({"mock": [page("discarded")]})))
        async with self.sessions() as db:
            item = await db.get(Item, "a")
            self.assertEqual(item.transactions_cursor, "start")
            self.assertIsNone(item.last_sync_success_at)
            self.assertEqual(item.next_sync_retry_at, self.clock + timedelta(minutes=15))
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertIsNone(state.last_published_run_id)
            self.assertEqual(state.handled_sequence, 1)

    async def test_required_metadata_reauthorization_pauses_item(self):
        await self.request(["a"])
        client = Client({"mock": [page("discard", added=[tx("new", "unknown")])]},
                        accounts=[plaid_error("ITEM_LOGIN_REQUIRED")])
        self.assertEqual((await self.poll(self.real_sync(client)))["status"], "blocked")
        async with self.sessions() as db:
            item = await db.get(Item, "a")
            self.assertTrue(item.sync_paused)
            self.assertIsNone(item.next_sync_retry_at)
            self.assertEqual(item.transactions_cursor, "start")

    async def test_m4_upgrade_preserves_m2_state_and_is_idempotent(self):
        async with self.sessions.begin() as db:
            db.add(SyncRuntimeState(user_id="synthetic-user", requested_sequence=7, handled_sequence=5))
        async with self.engine.begin() as connection:
            for column in ("requested_item_ids", "running_sequence", "running_item_ids"):
                await connection.execute(text(f"ALTER TABLE sync_runtime_state DROP COLUMN {column}"))
            await connection.execute(text("ALTER TABLE items DROP COLUMN sync_retry_count"))
            await connection.execute(text("ALTER TABLE sync_runs DROP COLUMN request_sequence"))
            await migrate_sync_runs(connection)
            await migrate_sync_runs(connection)
        async with self.sessions() as db:
            state = await db.get(SyncRuntimeState, "synthetic-user")
            self.assertEqual((state.requested_sequence, state.handled_sequence), (7, 5))
            self.assertIsNone(state.running_sequence)
            item = await db.get(Item, "a")
            self.assertEqual((item.transactions_cursor, item.sync_retry_count), ("start", 0))
