"""M2 publication tests use disposable PostgreSQL schemas and mocked Plaid only."""

import asyncio
import json
import os
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import plaid
from urllib3.exceptions import ReadTimeoutError
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSessionTransaction, async_sessionmaker, create_async_engine

from api.models import (Account, Base, Item, RawTransaction, StatementImportBatch,
                        StatementImportRow, SyncItemRun, SyncRun, SyncRuntimeState, Transaction)
from api.migrations import migrate_sync_runs
from api.services import sync_all as service


class Response:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


def page(cursor, *, added=(), modified=(), removed=(), more=False, status="HISTORICAL_UPDATE_COMPLETE"):
    return {"added": list(added), "modified": list(modified), "removed": list(removed),
            "next_cursor": cursor, "has_more": more, "transactions_update_status": status}


def tx(ident, account, amount=10):
    return {"transaction_id": ident, "account_id": account, "date": date(2026, 8, 1),
            "amount": amount, "name": "Synthetic", "merchant_name": "Synthetic",
            "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}}


def plaid_error(code):
    error = plaid.ApiException(status=400, reason="synthetic")
    error.body = json.dumps({"error_code": code, "request_id": "test-request-1"})
    return error


class Client:
    def __init__(self, pages, accounts=None):
        self.pages = {key: list(values) for key, values in pages.items()}
        self.accounts = list(accounts or [])
        self.sync_requests = []
        self.account_requests = []

    def transactions_sync(self, request, *, _request_timeout):
        data = request.to_dict()
        self.sync_requests.append((data, _request_timeout))
        value = self.pages[data["access_token"]].pop(0)
        if isinstance(value, Exception):
            raise value
        return Response(value)

    def accounts_get(self, request, *, _request_timeout):
        self.account_requests.append((request.to_dict(), _request_timeout))
        value = self.accounts.pop(0)
        if isinstance(value, Exception):
            raise value
        return Response({"accounts": value})


@unittest.skipUnless(os.environ.get("PFT_SYNC_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class SyncAllDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.db import engine as default_engine
        self.assertEqual(default_engine.url.port, 55439)
        self.assertIn(default_engine.url.host, {"127.0.0.1", "localhost"})
        self.assertNotEqual(os.environ.get("PLAID_ENV"), "production")
        self.schema = "sync_test_" + uuid.uuid4().hex
        self.admin = create_async_engine(default_engine.url)
        async with self.admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_async_engine(default_engine.url, connect_args={
            "server_settings": {"search_path": self.schema}})
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.sessions.begin() as db:
            for item_id, status in (("a", "active"), ("b", "active"), ("p", "pending")):
                db.add(Item(item_id=item_id, user_id="synthetic-user", institution_id="ins_" + item_id,
                            institution_name="Synthetic", status=status, access_token="token-" + item_id,
                            transactions_cursor="start-" + item_id))
                await db.flush()
                db.add(Account(account_id="account-" + item_id, item_id=item_id, name="Synthetic",
                               type="credit", consumer_transactions_enabled=True))

    async def asyncTearDown(self):
        await self.engine.dispose()
        async with self.admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        await self.admin.dispose()

    async def run_sync(self, client, **kwargs):
        return await service.sync_all("synthetic-user", client=client, session_factory=self.sessions,
                                      engine=self.engine, **kwargs)

    async def state(self):
        async with self.sessions() as db:
            items = {row.item_id: row for row in (await db.execute(select(Item))).scalars()}
            runs = (await db.execute(select(SyncRun).order_by(SyncRun.started_at))).scalars().all()
            item_runs = (await db.execute(select(SyncItemRun))).scalars().all()
            marker = await db.get(SyncRuntimeState, "synthetic-user")
            return items, runs, item_runs, marker

    async def test_multi_page_noop_repeat_removal_and_active_only_publication(self):
        client = Client({"token-a": [
            page("middle", added=[tx("new-a", "account-a")], more=True),
            page("end-a", modified=[tx("new-a", "account-a", 12)]),
        ], "token-b": [page("end-b", added=[tx("new-b", "account-b")])]})
        result = await self.run_sync(client)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["published"])
        self.assertEqual(len(client.account_requests), 0)
        self.assertEqual(client.sync_requests[0][0]["cursor"], "start-a")
        self.assertEqual(client.sync_requests[1][0]["cursor"], "middle")
        self.assertTrue(all(timeout == service.REQUEST_TIMEOUT for _, timeout in client.sync_requests))
        items, runs, item_runs, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "end-a")
        self.assertEqual(items["b"].transactions_cursor, "end-b")
        self.assertEqual(items["p"].transactions_cursor, "start-p")
        self.assertEqual(marker.last_published_run_id, result["run_id"])
        self.assertEqual(runs[0].classification_status, "success")
        self.assertIsNotNone(runs[0].classification_duration_ms)
        self.assertEqual(sum(row.added_count for row in item_runs), 2)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Transaction, "new-a")).amount, -12)
        no_op = await self.run_sync(Client({"token-a": [page("end-a")],
                                           "token-b": [page("end-b")]}))
        self.assertEqual(no_op["status"], "success")
        self.assertNotEqual(no_op["run_id"], result["run_id"])
        _, _, _, marker = await self.state()
        self.assertEqual(marker.last_published_run_id, no_op["run_id"])
        removed = await self.run_sync(Client({"token-a": [page("after-remove", removed=[
            {"transaction_id": "new-a"}])], "token-b": [page("end-b")]}))
        self.assertEqual(removed["status"], "success")
        async with self.sessions() as db:
            self.assertTrue((await db.get(RawTransaction, "new-a")).is_removed)
            self.assertIsNotNone(await db.get(Transaction, "new-a"))

    async def test_statement_conflict_rolls_back_only_its_item_and_other_item_publishes(self):
        async with self.sessions.begin() as db:
            db.add(StatementImportBatch(batch_id="batch", user_id="synthetic-user", item_id="a",
                                        account_id="account-a", adapter="synthetic", adapter_version="1",
                                        file_sha256="fake", preview_digest="fake", manifest={},
                                        status="applied", applied_by="test"))
            await db.flush()
            db.add(StatementImportRow(row_id="row", batch_id="batch", source_record=1,
                                      source_line_end=1, fingerprint="fake", disposition="insert",
                                      canonical={}, source_evidence={}))
            await db.flush()
            db.add(RawTransaction(transaction_id="statement-id", item_id="a", account_id="account-a",
                                  transaction_date=date(2026, 8, 1), payload={"amount": "-10", "kind": "purchase"},
                                  source="statement", statement_row_id="row"))
            await db.flush()
            db.add(Transaction(transaction_id="statement-id", account_id="account-a",
                               transaction_date=date(2026, 8, 1), amount=-10,
                               statement_kind="purchase"))
        client = Client({"token-a": [page("bad-cursor", added=[tx("statement-id", "account-a")])],
                         "token-b": [page("good-cursor", added=[tx("new-b", "account-b")])]})
        result = await self.run_sync(client)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"]["a"]["status"], "blocked")
        items, runs, item_runs, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "start-a")
        self.assertEqual(items["b"].transactions_cursor, "good-cursor")
        self.assertEqual(marker.last_published_run_id, result["run_id"])
        self.assertEqual(runs[0].status, "partial")
        self.assertEqual(next(row for row in item_runs if row.item_id == "a").added_count, 0)
        async with self.sessions() as db:
            self.assertEqual((await db.get(RawTransaction, "statement-id")).source, "statement")
            self.assertEqual((await db.get(Transaction, "statement-id")).transaction_type, "expense")

    async def test_unknown_account_repairs_once_and_refetches_original_cursor(self):
        unknown = tx("new", "new-account")
        client = Client({"token-a": [page("discard", added=[unknown]),
                                    page("end", added=[unknown])]},
                        accounts=[[{"account_id": "new-account", "name": "New", "type": "credit",
                                   "subtype": "credit card", "mask": "1234"}]])
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(client.account_requests), 1)
        self.assertEqual([entry[0]["cursor"] for entry in client.sync_requests], ["start-a", "start-a"])
        async with self.sessions() as db:
            self.assertTrue((await db.get(Account, "new-account")).consumer_transactions_enabled)
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "end")
            self.assertIsNotNone(await db.get(Transaction, "new"))

    async def test_failed_repair_leaves_metadata_and_cursor_unchanged(self):
        client = Client({"token-a": [page("discard", added=[tx("new", "unknown")])]},
                        accounts=[plaid_error("INTERNAL_SERVER_ERROR")])
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["published"])
        self.assertEqual(len(client.account_requests), 1)
        items, runs, item_runs, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "start-a")
        self.assertIsNone(marker)
        self.assertEqual(runs[0].classification_status, "not_run")
        self.assertEqual(item_runs[0].error_category, "metadata_refresh_failed")
        async with self.sessions() as db:
            self.assertIsNone(await db.get(Account, "unknown"))

    async def test_metadata_type_drift_rolls_back_repair_and_preserves_scope(self):
        client = Client({"token-a": [page("discard", added=[tx("new", "new-account")]),
                                    page("end", added=[tx("new", "new-account")])]},
                        accounts=[[{"account_id": "account-a", "name": "Changed", "type": "investment"},
                                   {"account_id": "new-account", "name": "New", "type": "credit"}]])
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["items"]["a"]["error_category"], "account_type_drift")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "start-a")
            self.assertEqual((await db.get(Account, "account-a")).type, "credit")
            self.assertIsNone(await db.get(Account, "new-account"))

    async def test_network_failure_isolated_and_retry_count_bounded(self):
        client = Client({"token-a": [ReadTimeoutError(None, "/transactions/sync", "synthetic timeout")
                                    for _ in range(3)],
                         "token-b": [page("end-b", added=[tx("new-b", "account-b")])]})
        result = await self.run_sync(client)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"]["a"]["error_category"], "network")
        self.assertEqual(len([request for request, _ in client.sync_requests
                              if request["access_token"] == "token-a"]), 3)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "start-a")
            self.assertEqual((await db.get(Item, "b")).transactions_cursor, "end-b")

    async def test_replayed_added_batch_does_not_claim_a_new_data_change(self):
        first = await self.run_sync(Client({"token-a": [page("end", added=[tx("same", "account-a")])]}),
                                    item_ids=["a"])
        items, _, _, _ = await self.state()
        first_change = items["a"].last_sync_change_at
        replay = await self.run_sync(Client({"token-a": [page("end-again", added=[tx("same", "account-a")])]}),
                                     item_ids=["a"])
        self.assertEqual(replay["status"], "success")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).last_sync_change_at, first_change)
            self.assertEqual((await db.get(SyncItemRun, (replay["run_id"], "a"))).added_count, 1)
            self.assertEqual((await db.get(SyncRuntimeState, "synthetic-user")).last_published_run_id,
                             replay["run_id"])
            self.assertEqual((await db.get(SyncRun, first["run_id"])).status, "success")

    async def test_pagination_mutation_discards_pages_and_retries_from_original_cursor(self):
        client = Client({"token-a": [page("middle", added=[tx("discarded", "account-a")], more=True),
                                    plaid_error("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"),
                                    page("end", added=[tx("kept", "account-a")])]})
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["status"], "success")
        self.assertEqual([entry[0]["cursor"] for entry in client.sync_requests],
                         ["start-a", "middle", "start-a"])
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "discarded"))
            self.assertIsNotNone(await db.get(RawTransaction, "kept"))
            row = await db.get(SyncItemRun, (result["run_id"], "a"))
            self.assertEqual(row.retry_count, 1)

    async def test_not_ready_and_stale_cursor_never_publish(self):
        waiting = await self.run_sync(Client({"token-a": [
            page("provisional", added=[tx("deferred", "account-a")], more=True),
            page("not-ready", status="NOT_READY")]}),
                                      item_ids=["a"])
        self.assertEqual(waiting["status"], "waiting")
        self.assertFalse(waiting["published"])
        items, _, _, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "start-a")
        self.assertIsNone(marker)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "deferred"))
        original = service._fetch_item

        async def change_cursor(client, snapshot, deadline):
            buffer = await original(client, snapshot, deadline)
            async with self.sessions.begin() as db:
                await db.execute(update(Item).where(Item.item_id == "a").values(transactions_cursor="other"))
            return buffer

        with patch.object(service, "_fetch_item", side_effect=change_cursor):
            stale = await self.run_sync(Client({"token-a": [page("end", added=[tx("new", "account-a")])]}),
                                        item_ids=["a"])
        self.assertEqual(stale["status"], "blocked")
        self.assertEqual(stale["items"]["a"]["error_category"], "stale_item")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "other")
            self.assertIsNone(await db.get(RawTransaction, "new"))

    async def test_concurrent_scope_change_rejects_buffer(self):
        original = service._fetch_item

        async def change_scope(client, snapshot, deadline):
            buffer = await original(client, snapshot, deadline)
            async with self.sessions.begin() as db:
                await db.execute(update(Account).where(Account.account_id == "account-a")
                                 .values(consumer_transactions_enabled=False))
            return buffer

        with patch.object(service, "_fetch_item", side_effect=change_scope):
            result = await self.run_sync(Client({"token-a": [page("end", added=[tx("new", "account-a")])]}),
                                         item_ids=["a"])
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["items"]["a"]["error_category"], "stale_scope")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "start-a")
            self.assertIsNone(await db.get(RawTransaction, "new"))

    async def test_global_failure_rolls_back_every_item_and_marker(self):
        async def fail(*args):
            raise RuntimeError("synthetic classifier crash")

        client = Client({"token-a": [page("end-a", added=[tx("new-a", "account-a")])],
                         "token-b": [page("end-b", added=[tx("new-b", "account-b")])]})
        with patch.object(service, "classify_active_transactions", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "classifier crash"):
                await self.run_sync(client)
        items, runs, item_runs, marker = await self.state()
        self.assertEqual((items["a"].transactions_cursor, items["b"].transactions_cursor),
                         ("start-a", "start-b"))
        self.assertIsNone(marker)
        self.assertEqual(runs[0].status, "failed")
        self.assertTrue(all(row.added_count == 0 for row in item_runs))
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "new-a"))
            self.assertIsNone(await db.get(RawTransaction, "new-b"))

    async def test_unexpected_normalization_error_aborts_all_items(self):
        original = service.normalize_item_transactions

        async def normalize(db, user_id, item_id):
            if item_id == "a":
                raise TypeError("synthetic normalization failure")
            return await original(db, user_id, item_id)

        with patch.object(service, "normalize_item_transactions", side_effect=normalize):
            with self.assertRaisesRegex(TypeError, "normalization failure"):
                await self.run_sync(Client({
                    "token-a": [page("end-a", added=[tx("new-a", "account-a")])],
                    "token-b": [page("end-b", added=[tx("new-b", "account-b")])] }))
        items, runs, item_runs, marker = await self.state()
        self.assertEqual((items["a"].transactions_cursor, items["b"].transactions_cursor),
                         ("start-a", "start-b"))
        self.assertEqual(runs[0].status, "failed")
        self.assertIsNone(marker)
        self.assertTrue(all(row.added_count == 0 for row in item_runs))
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "new-a"))
            self.assertIsNone(await db.get(RawTransaction, "new-b"))

    async def test_crash_before_commit_is_reconciled_and_after_commit_state_is_authoritative(self):
        async def crash(*args):
            raise asyncio.CancelledError()

        with patch.object(service, "classify_active_transactions", side_effect=crash):
            with self.assertRaises(asyncio.CancelledError):
                await self.run_sync(Client({"token-a": [page("end-a", added=[tx("lost", "account-a")])]}),
                                    item_ids=["a"])
        _, runs, _, marker = await self.state()
        self.assertEqual(runs[0].status, "running")
        self.assertIsNone(marker)
        success = await self.run_sync(Client({"token-a": [page("end-a", added=[tx("kept", "account-a")])]}),
                                      item_ids=["a"])
        self.assertEqual(success["status"], "success")
        _, runs, _, marker = await self.state()
        self.assertEqual(runs[0].status, "interrupted")
        async with self.sessions() as db:
            abandoned = await db.get(SyncItemRun, (runs[0].run_id, "a"))
            self.assertEqual(abandoned.status, "interrupted")
            self.assertIsNotNone(abandoned.finished_at)
        self.assertEqual(marker.last_published_run_id, success["run_id"])
        # Simulate a lost acknowledgement after commit; diagnostics cannot overwrite it.
        await service._finalize_failure(self.sessions, success["run_id"], {}, "ack_lost")
        async with self.sessions() as db:
            self.assertEqual((await db.get(SyncRun, success["run_id"])).status, "success")
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "end-a")

    async def test_input_failure_rolls_back_writes_and_cursor_inside_item_savepoint(self):
        async with self.sessions.begin() as db:
            db.add(RawTransaction(transaction_id="invalid-old", item_id="b", account_id="account-b",
                                  transaction_date=date(2026, 8, 1), payload={"amount": "invalid"}))
        result = await self.run_sync(Client({
            "token-a": [page("end-a", added=[tx("kept", "account-a")])],
            "token-b": [page("discard-b", added=[tx("rolled-back", "account-b")])],
        }))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["items"]["b"]["error_category"], "normalization_input")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "b")).transactions_cursor, "start-b")
            self.assertIsNone(await db.get(RawTransaction, "rolled-back"))
            self.assertIsNone(await db.get(Transaction, "rolled-back"))
            self.assertIsNotNone(await db.get(Transaction, "kept"))
            self.assertEqual((await db.get(SyncItemRun, (result["run_id"], "b"))).added_count, 0)

    async def test_unknown_account_after_repair_does_not_trigger_second_repair(self):
        client = Client({"token-a": [page("discard", added=[tx("first", "unknown-1")]),
                                    page("discard-again", added=[tx("second", "unknown-2")])]},
                        accounts=[[{"account_id": "unknown-1", "name": "New", "type": "credit"}]])
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["items"]["a"]["error_category"], "unknown_account")
        self.assertEqual(len(client.account_requests), 1)
        async with self.sessions() as db:
            self.assertEqual((await db.get(Item, "a")).transactions_cursor, "start-a")
            self.assertIsNone(await db.get(Account, "unknown-1"))
            self.assertIsNone(await db.get(SyncRuntimeState, "synthetic-user"))

    async def test_actual_post_commit_acknowledgement_exception_preserves_publication(self):
        original_exit = AsyncSessionTransaction.__aexit__
        outer_commits = 0

        async def lose_ack(transaction, *args):
            nonlocal outer_commits
            result = await original_exit(transaction, *args)
            if not transaction.nested and args[0] is None:
                outer_commits += 1
                if outer_commits == 3:  # Selection, run creation, then publication.
                    raise RuntimeError("synthetic acknowledgement lost")
            return result

        with patch.object(AsyncSessionTransaction, "__aexit__", new=lose_ack):
            with self.assertRaisesRegex(RuntimeError, "acknowledgement lost"):
                await self.run_sync(Client({"token-a": [page("committed", added=[tx("kept", "account-a")])]}),
                                    item_ids=["a"])
        items, runs, item_runs, marker = await self.state()
        self.assertEqual(runs[0].status, "success")
        self.assertEqual(item_runs[0].status, "success")
        self.assertEqual(marker.last_published_run_id, runs[0].run_id)
        self.assertEqual(items["a"].transactions_cursor, "committed")

    async def test_lost_lock_connection_aborts_publication(self):
        original = service._fetch_item

        async def disconnect_owner(client, snapshot, deadline):
            buffer = await original(client, snapshot, deadline)
            async with self.sessions() as db:
                pid = await db.scalar(text(
                    "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted "
                    "AND database=(SELECT oid FROM pg_database WHERE datname=current_database()) "
                    "AND classid::bigint=((hashtextextended(:key,0)>>32)&4294967295) "
                    "AND objid::bigint=(hashtextextended(:key,0)&4294967295)"),
                    {"key": "pft-sync:synthetic-user"})
                self.assertIsNotNone(pid)
                await db.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
            return buffer

        with patch.object(service, "_fetch_item", side_effect=disconnect_owner):
            with self.assertRaises(Exception):
                await self.run_sync(Client({"token-a": [page("lost", added=[tx("lost", "account-a")])]}),
                                    item_ids=["a"])
        items, runs, _, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "start-a")
        self.assertIsNone(marker)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "lost"))
        await self.run_sync(Client({"token-a": [page("recovered")]}), item_ids=["a"])
        async with self.sessions() as db:
            self.assertEqual((await db.get(SyncRun, runs[0].run_id)).status, "interrupted")

    async def test_existing_history_without_cursor_blocks_before_plaid(self):
        async with self.sessions.begin() as db:
            await db.execute(update(Item).where(Item.item_id == "a").values(transactions_cursor=None))
            db.add(RawTransaction(transaction_id="old", item_id="a", account_id="account-a",
                                  transaction_date=date(2026, 8, 1), payload={"amount": 10}))
        client = Client({})
        result = await self.run_sync(client, item_ids=["a"])
        self.assertEqual(result["items"]["a"]["error_category"], "missing_cursor")
        self.assertEqual(client.sync_requests, [])

    async def test_publication_deadline_cancels_classification_and_rolls_back(self):
        async def slow_classification(*args):
            await asyncio.sleep(10)

        with (patch.object(service, "MAX_RUN_SECONDS", 0.5),
              patch.object(service, "classify_active_transactions", side_effect=slow_classification)):
            with self.assertRaises(TimeoutError):
                await self.run_sync(Client({"token-a": [page("uncommitted", added=[tx("late", "account-a")])]}),
                                    item_ids=["a"])
        items, runs, _, marker = await self.state()
        self.assertEqual(items["a"].transactions_cursor, "start-a")
        self.assertEqual(runs[0].status, "failed")
        self.assertIsNone(marker)
        async with self.sessions() as db:
            self.assertIsNone(await db.get(RawTransaction, "late"))

    async def test_dedicated_sync_lock_prevents_parallel_run_and_idle_creates_no_marker(self):
        async with self.engine.connect() as connection:
            await connection.scalar(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
                                    {"key": "pft-sync:synthetic-user"})
            await connection.commit()
            result = await self.run_sync(Client({}))
            self.assertEqual(result["status"], "busy")
            await connection.scalar(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                                    {"key": "pft-sync:synthetic-user"})
            await connection.commit()
        async with self.sessions.begin() as db:
            await db.execute(update(Item).where(Item.status == "active").values(sync_paused=True))
        idle = await self.run_sync(Client({}))
        self.assertEqual(idle["status"], "idle")
        _, runs, _, marker = await self.state()
        self.assertEqual(runs, [])
        self.assertIsNone(marker)

    async def test_jobs_retry_backoff_and_action_blocker_are_persisted(self):
        clock = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
        for delay in (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=6),
                      timedelta(hours=6)):
            with patch.object(service, "utcnow", return_value=clock):
                result = await self.run_sync(Client({"token-a": [plaid_error("PRODUCT_NOT_READY")]}),
                                             item_ids=["a"], trigger_source="jobs")
            self.assertEqual(result["status"], "waiting")
            async with self.sessions() as db:
                item = await db.get(Item, "a")
                self.assertEqual(item.next_sync_retry_at, clock + delay)
                self.assertFalse(item.sync_paused)
            clock += delay
        with patch.object(service, "utcnow", return_value=clock):
            result = await self.run_sync(Client({"token-a": [plaid_error("ITEM_LOGIN_REQUIRED")]}),
                                         item_ids=["a"], trigger_source="jobs")
        self.assertEqual(result["status"], "blocked")
        async with self.sessions() as db:
            item = await db.get(Item, "a")
            self.assertTrue(item.sync_paused)
            self.assertIsNone(item.next_sync_retry_at)

    async def test_migration_preserves_existing_cursor_and_is_idempotent(self):
        async with self.engine.begin() as connection:
            for table in ("sync_runtime_state", "sync_item_runs", "sync_runs"):
                await connection.execute(text(f"DROP TABLE {table}"))
            for name in ("sync_paused", "last_sync_attempt_at", "last_sync_success_at",
                         "last_sync_change_at", "next_sync_retry_at"):
                await connection.execute(text(f"ALTER TABLE items DROP COLUMN {name}"))
            await migrate_sync_runs(connection)
            await migrate_sync_runs(connection)
            self.assertEqual(await connection.scalar(text(
                "SELECT transactions_cursor FROM items WHERE item_id='a'")), "start-a")
            self.assertEqual(await connection.scalar(text(
                "SELECT count(*) FROM items WHERE sync_paused=false")), 3)

    async def test_full_active_classification_cost_on_synthetic_history(self):
        async with self.sessions.begin() as db:
            for index in range(500):
                item_id = "a" if index % 2 == 0 else "b"
                transaction_id = "history-" + str(index)
                db.add(RawTransaction(transaction_id=transaction_id, item_id=item_id,
                                      account_id="account-" + item_id,
                                      transaction_date=date(2026, 8, 1),
                                      payload={"amount": 1, "name": "Synthetic",
                                               "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"}}))
            await db.flush()
            for index in range(500):
                item_id = "a" if index % 2 == 0 else "b"
                db.add(Transaction(transaction_id="history-" + str(index),
                                   account_id="account-" + item_id,
                                   transaction_date=date(2026, 8, 1), amount=-1,
                                   description="Synthetic", plaid_category="GENERAL_MERCHANDISE"))
            db.add(RawTransaction(transaction_id="pending-history", item_id="p",
                                  account_id="account-p", transaction_date=date(2026, 8, 1),
                                  payload={"amount": 1, "name": "Synthetic"}))
            await db.flush()
            db.add(Transaction(transaction_id="pending-history", account_id="account-p",
                               transaction_date=date(2026, 8, 1), amount=-1))
        result = await self.run_sync(Client({"token-a": [page("end-a")]}), item_ids=["a"])
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["classification_duration_ms"])
        async with self.sessions() as db:
            run = await db.get(SyncRun, result["run_id"])
            self.assertEqual(run.classified_count, 500)
            self.assertIsNone((await db.get(Transaction, "pending-history")).transaction_type)
        print(f"M2 synthetic full-active classification: 500 rows, "
              f"{result['classification_duration_ms']} ms")
