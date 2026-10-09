"""M5 recovery tests: a real child process is SIGKILLed, so no handler or finally runs.

Uses only disposable PostgreSQL schemas and the mocked Plaid client from test_sync_all.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSessionTransaction, async_sessionmaker, create_async_engine

from api.jobs import request_sync, tick
from api.models import Account, Base, Item, RawTransaction, SyncItemRun, SyncRun, SyncRuntimeState
from api.services import sync_all as service
from tests.test_sync_all import Client, page, tx

USER = "synthetic-user"
ROOT = Path(__file__).resolve().parents[1]
LOCK_HELD = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND granted "
    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
    "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
    "AND objid::bigint=(hashtextextended(:key,0)&4294967295))")


def child_engine(schema):
    from api.db import engine as default_engine
    return create_async_engine(default_engine.url, connect_args={
        "server_settings": {"search_path": schema}})


async def child_main(schema, scenario, marker):
    """Runs one jobs tick that stops at a chosen point; the parent kills this process."""
    engine = child_engine(schema)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    client = Client({"token-a": [page("lost-a", added=[tx("lost-a", "account-a")])],
                     "token-b": [page("lost-b", added=[tx("lost-b", "account-b")])]})
    publishing = False
    original_classify = service.classify_active_transactions
    original_exit = AsyncSessionTransaction.__aexit__

    async def classify(db, user_id):
        nonlocal publishing
        result = await original_classify(db, user_id)
        publishing = True
        if scenario == "kill_in_publication":
            # Uncommitted publication writes and row locks are now held.
            Path(marker).write_text("ready")
            await asyncio.sleep(60)
        return result

    async def exit_after_commit(transaction, *args):
        result = await original_exit(transaction, *args)
        if publishing and not transaction.nested and args[0] is None:
            os._exit(9)  # Publication committed; the process dies before anything else.
        return result

    async def sync(user_id, **kwargs):
        return await service.sync_all(user_id, client=client, **kwargs)

    with patch.object(service, "classify_active_transactions", side_effect=classify), \
         patch.object(AsyncSessionTransaction, "__aexit__", new=exit_after_commit):
        await tick(USER, engine=engine, session_factory=sessions, sync=sync)


@unittest.skipUnless(os.environ.get("PFT_SYNC_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class HardTerminationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertEqual(default_engine.url.port, 55439)
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "recovery_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(default_engine.url)
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = child_engine(self.schema)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            for ident in ("a", "b"):
                db.add(Item(item_id=ident, user_id=USER, institution_id="ins_" + ident,
                            institution_name="Synthetic", status="active", access_token="token-" + ident,
                            transactions_cursor="start-" + ident))
                await db.flush()
                db.add(Account(account_id="account-" + ident, item_id=ident, name="Synthetic",
                               type="credit", consumer_transactions_enabled=True))

    async def asyncTearDown(self):
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def kill_child(self, scenario):
        """Start a tick in a child process and end it without running any cleanup."""
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready"
            log = open(Path(directory) / "stderr", "w+b")
            child = subprocess.Popen(
                [sys.executable, "-m", "tests.test_m5_sync_recovery", "child", self.schema, scenario,
                 str(marker)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=log)
            try:
                if scenario == "kill_in_publication":
                    deadline = time.monotonic() + 30
                    while not marker.exists():
                        if child.poll() is not None:
                            log.seek(0)
                            self.fail("child exited early: " + log.read().decode()[-2000:])
                        self.assertLess(time.monotonic(), deadline, "child never reached publication")
                        await asyncio.sleep(0.05)
                    os.kill(child.pid, signal.SIGKILL)
                code = await asyncio.to_thread(child.wait, 30)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                log.close()
        self.assertIn(code, {-signal.SIGKILL, 9})
        # PostgreSQL ends the dead client's session; no application code released the locks.
        released_after = None
        started = time.monotonic()
        while time.monotonic() - started < 10:
            async with self.admin.connect() as db:
                held = [await db.scalar(LOCK_HELD, {"key": key + USER})
                        for key in ("pft-sync:", "pft-jobs:")]
            if not any(held):
                released_after = time.monotonic() - started
                break
            await asyncio.sleep(0.05)
        self.assertIsNotNone(released_after, "advisory locks outlived the killed session")

    async def runs(self):
        async with self.sessions() as db:
            return (await db.execute(select(SyncRun).order_by(SyncRun.started_at))).scalars().all()

    async def state(self):
        async with self.sessions() as db:
            return await db.get(SyncRuntimeState, USER)

    async def item(self, ident):
        async with self.sessions() as db:
            return await db.get(Item, ident)

    async def assert_nothing_published(self):
        async with self.sessions() as db:
            for ident in ("a", "b"):
                self.assertEqual((await db.get(Item, ident)).transactions_cursor, "start-" + ident)
                self.assertIsNone(await db.get(RawTransaction, "lost-" + ident))
            marker = await db.get(SyncRuntimeState, USER)
            self.assertIsNone(marker.last_published_run_id if marker else None)

    async def poll(self, client):
        async def sync(user_id, **kwargs):
            return await service.sync_all(user_id, client=client, **kwargs)
        return await tick(USER, engine=self.engine, session_factory=self.sessions, sync=sync)

    async def test_killed_manual_run_is_reconciled_backed_off_and_replayed_once(self):
        await request_sync(USER, ["a", "b"], session_factory=self.sessions)
        await self.kill_child("kill_in_publication")
        runs = await self.runs()
        self.assertEqual([run.status for run in runs], ["running"])  # Nothing finalized it.
        await self.assert_nothing_published()

        # Next tick: reconcile under the lock, then replay the same manual request.
        before = datetime.now(timezone.utc)
        replay = Client({"token-a": [page("done-a", added=[tx("kept-a", "account-a")])],
                         "token-b": [page("done-b")]})
        result = await self.poll(replay)
        self.assertEqual(result["status"], "success")
        runs = await self.runs()
        self.assertEqual([(run.status, run.error_category) for run in runs],
                         [("interrupted", "interrupted"), ("success", None)])
        self.assertEqual({run.request_sequence for run in runs}, {1})
        async with self.sessions() as db:
            item_runs = (await db.execute(select(SyncItemRun).where(
                SyncItemRun.run_id == runs[0].run_id))).scalars().all()
            self.assertEqual({(row.status, row.error_category) for row in item_runs},
                             {("interrupted", "interrupted")})
        state = await self.state()
        self.assertEqual((state.handled_sequence, state.running_sequence), (1, None))
        self.assertEqual(state.last_published_run_id, runs[1].run_id)
        self.assertEqual((await self.item("a")).transactions_cursor, "done-a")
        # Success after the interruption clears the backoff the reconciliation recorded.
        self.assertEqual(((await self.item("a")).sync_retry_count, (await self.item("a")).next_sync_retry_at),
                         (0, None))
        self.assertGreaterEqual((await self.item("a")).last_sync_success_at, before)

    async def test_second_kill_of_same_manual_request_finishes_it(self):
        await request_sync(USER, ["a"], session_factory=self.sessions)
        await self.kill_child("kill_in_publication")
        await self.kill_child("kill_in_publication")  # The replay is killed too.
        self.assertEqual([run.status for run in await self.runs()], ["interrupted", "running"])
        unused = Client({})
        result = await self.poll(unused)
        # Reconciliation finished request 1; item a is backed off, so nothing is due.
        self.assertEqual(result["status"], "idle")
        self.assertEqual(unused.sync_requests, [])
        self.assertEqual([run.status for run in await self.runs()], ["interrupted", "interrupted"])
        state = await self.state()
        self.assertEqual((state.handled_sequence, state.running_sequence), (1, None))
        item = await self.item("a")
        self.assertEqual(item.sync_retry_count, 2)
        self.assertGreater(item.next_sync_retry_at, datetime.now(timezone.utc) + timedelta(minutes=50))
        await self.assert_nothing_published()
        # A new click is a new request and runs immediately.
        await request_sync(USER, ["a"], session_factory=self.sessions)
        self.assertEqual((await self.poll(Client({"token-a": [page("done-a")]})))["status"], "success")

    async def test_killed_scheduled_run_backs_off_instead_of_rerunning_each_tick(self):
        await self.kill_child("kill_in_publication")
        self.assertEqual([run.trigger_source for run in await self.runs()], ["jobs"])
        unused = Client({})
        self.assertEqual((await self.poll(unused))["status"], "idle")
        self.assertEqual(unused.sync_requests, [])
        for ident in ("a", "b"):
            item = await self.item(ident)
            self.assertEqual(item.sync_retry_count, 1)
            self.assertGreater(item.next_sync_retry_at, datetime.now(timezone.utc) + timedelta(minutes=14))
        await self.assert_nothing_published()
        # Once the retry is due, the next tick runs normally.
        later = datetime.now(timezone.utc) + timedelta(minutes=16)
        async def sync(user_id, **kwargs):
            with patch.object(service, "utcnow", return_value=later):
                return await service.sync_all(user_id, client=Client({
                    "token-a": [page("done-a")], "token-b": [page("done-b")]}), **kwargs)
        result = await tick(USER, now=later, engine=self.engine, session_factory=self.sessions, sync=sync)
        self.assertEqual(result["status"], "success")

    async def test_kill_right_after_commit_keeps_publication_and_does_not_replay(self):
        async with self.sessions.begin() as db:  # Keep b out of the scheduled poll below.
            await db.execute(update(Item).where(Item.item_id == "b")
                             .values(last_sync_success_at=datetime.now(timezone.utc)))
        await request_sync(USER, ["a"], session_factory=self.sessions)
        await self.kill_child("kill_after_commit")
        runs = await self.runs()
        self.assertEqual([(run.status, run.request_sequence) for run in runs], [("success", 1)])
        state = await self.state()
        self.assertEqual((state.handled_sequence, state.running_sequence), (1, None))
        self.assertEqual(state.last_published_run_id, runs[0].run_id)
        self.assertEqual((await self.item("a")).transactions_cursor, "lost-a")
        unused = Client({})
        self.assertEqual((await self.poll(unused))["status"], "idle")
        self.assertEqual(unused.sync_requests, [])

    async def test_cooperative_cancel_finalizes_now_and_request_is_replayed(self):
        await request_sync(USER, ["a"], session_factory=self.sessions)
        entered = asyncio.Event()

        async def hang(db, user_id):
            entered.set()
            await asyncio.sleep(60)

        with patch.object(service, "classify_active_transactions", side_effect=hang):
            task = asyncio.create_task(self.poll(Client({"token-a": [page("lost-a", added=[
                tx("lost-a", "account-a")])]})))
            await asyncio.wait_for(entered.wait(), 10)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        runs = await self.runs()
        self.assertEqual([(run.status, run.error_category) for run in runs], [("interrupted", "cancelled")])
        async with self.admin.connect() as db:
            for key in ("pft-sync:", "pft-jobs:"):
                self.assertFalse(await db.scalar(LOCK_HELD, {"key": key + USER}))
        await self.assert_nothing_published()
        result = await self.poll(Client({"token-a": [page("done-a")]}))
        self.assertEqual(result["status"], "success")
        state = await self.state()
        self.assertEqual((state.handled_sequence, state.running_sequence), (1, None))

    async def test_cancel_while_lock_connection_is_gone_leaves_reconciliation_to_next_owner(self):
        await request_sync(USER, ["a"], session_factory=self.sessions)
        entered = asyncio.Event()

        async def hang(db, user_id):
            entered.set()
            await asyncio.sleep(60)

        with patch.object(service, "classify_active_transactions", side_effect=hang):
            task = asyncio.create_task(self.poll(Client({"token-a": [page("lost-a")]})))
            await asyncio.wait_for(entered.wait(), 10)
            async with self.admin.begin() as db:
                for key in ("pft-sync:", "pft-jobs:"):
                    await db.execute(text(
                        "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype='advisory' "
                        "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
                        "AND objid::bigint=(hashtextextended(:key,0)&4294967295)"), {"key": key + USER})
            task.cancel()
            with self.assertRaises(BaseException):
                await task
        # Without the lock this process must not decide the run.
        self.assertEqual([run.status for run in await self.runs()], ["running"])
        result = await self.poll(Client({"token-a": [page("done-a")]}))
        self.assertEqual(result["status"], "success")
        self.assertEqual([run.status for run in await self.runs()], ["interrupted", "success"])


if __name__ == "__main__" and sys.argv[1:2] == ["child"]:
    asyncio.run(child_main(*sys.argv[2:5]))
