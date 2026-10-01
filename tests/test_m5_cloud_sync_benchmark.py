"""Guard and synthetic SDK checks; no provider, Plaid or database calls."""
from types import SimpleNamespace
import unittest
import json
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from experiments.m5_cloud import sync_benchmark_support as bench


class BenchmarkGuardTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, options, *, role="jobs", enabled=True, project="acyghoemtdrilsdszolq"):
        config = SimpleNamespace(role=role, project_ref=project)
        async def capability():
            return config
        app = FastAPI()
        bench.register(app, capability, None, None, "synthetic-instance")
        async def receive():
            return {"type":"http.request","body":json.dumps(options).encode(),"more_body":False}
        request = Request({"type":"http","headers":[]},receive)
        endpoint = next(route.endpoint for route in app.routes if route.path=="/probe/sync-benchmark")
        env = {"M5_BENCHMARK_ENABLED": "synthetic-20261001" if enabled else ""}
        with patch.dict("os.environ", env), patch.object(bench, "engine_for") as factory:
            try:
                response = await endpoint(request,config)
            except HTTPException as exc:
                status = exc.status_code
            else:
                status = response.status_code
            factory.assert_not_called()
        return status

    async def test_reader_disabled_and_wrong_project_rejected_before_db(self):
        self.assertEqual(await self.request({"scale":2610},role="reader"),403)
        self.assertEqual(await self.request({"scale":2610},enabled=False),403)
        self.assertEqual(await self.request({"scale":2610},project="a"*20),403)

    async def test_request_cannot_widen_scope_or_workload(self):
        for options in ({"scale":35601}, {"scale":True}, {"scale":2610,"schema":"public"},
                {"scale":2610,"action":"seed"}, {"scale":35600,"action":"cancel_fetch"},
                {"scale":2610,"action":[]}, {"scale":2610,"query":"select 1"}):
            with self.subTest(options=options):
                self.assertEqual(await self.request(options),422)

    def test_synthetic_client_preserves_noop_cursor_and_rejects_other_tokens(self):
        request = SimpleNamespace(to_dict=lambda:{"access_token":"synthetic-token-0","cursor":"unchanged"})
        client = bench.SyntheticClient(2610,"noop")
        value = client.transactions_sync(request,_request_timeout=(5,20))
        self.assertEqual(value["next_cursor"],"unchanged")
        self.assertEqual(value["added"],[])
        self.assertEqual(value["modified"],[])
        self.assertEqual(value["removed"],[])
        with self.assertRaises(RuntimeError):
            client.transactions_sync(SimpleNamespace(to_dict=lambda:{"access_token":"other"}),_request_timeout=(5,20))


class BenchmarkWorkloadTests(unittest.TestCase):
    def test_append_one_is_accepted_at_both_scales_but_negatives_stay_at_2610(self):
        for scale in (2610, 35600):
            self.assertEqual(bench.parse_options(json.dumps({"scale": scale, "action": "append_one"}).encode()),
                             (scale, "append_one"))
        self.assertEqual(bench.parse_options(b'{"scale": 2610}'), (2610, "noop"))
        with self.assertRaises(ValueError):
            bench.parse_options(b'{"scale": 35600, "action": "timeout_publication"}')

    def test_append_one_adds_one_new_row_per_item_and_advances_cursor(self):
        client = bench.SyntheticClient(35600, "append_one")
        seen = set()
        for i in range(5):
            request = SimpleNamespace(to_dict=lambda i=i: {"access_token": f"synthetic-token-{i}", "cursor": "start"})
            value = client.transactions_sync(request, _request_timeout=(5, 20))
            self.assertEqual(len(value["added"]), 1)
            self.assertEqual(value["added"][0]["account_id"], f"account-{i}-0")
            self.assertEqual((value["modified"], value["removed"]), ([], []))
            self.assertNotEqual(value["next_cursor"], "start")
            seen.add(value["added"][0]["transaction_id"])
            seen.add(value["next_cursor"])
        other = bench.SyntheticClient(35600, "append_one").transactions_sync(
            SimpleNamespace(to_dict=lambda: {"access_token": "synthetic-token-0", "cursor": "start"}),
            _request_timeout=(5, 20))
        self.assertEqual(len(seen), 10)
        self.assertNotIn(other["added"][0]["transaction_id"], seen)

    def test_fixture_rows_allow_only_executed_appends_and_noop_needs_exact_scale(self):
        self.assertTrue(bench.fixture_rows_accepted(2610, "noop", 2610, 0))
        self.assertFalse(bench.fixture_rows_accepted(2610, "noop", 2615, 1))
        self.assertTrue(bench.fixture_rows_accepted(2610, "append_one", 2615, 1))
        self.assertTrue(bench.fixture_rows_accepted(2610, "timeout_publication", 2625, 3))
        self.assertFalse(bench.fixture_rows_accepted(2610, "append_one", 2620, 1))
        self.assertFalse(bench.fixture_rows_accepted(35600, "append_one", 35599, 0))


class WireCounterTests(unittest.TestCase):
    def fake_connection(self):
        received = []
        protocol = SimpleNamespace(buffer_updated=received.append)
        transport = SimpleNamespace(_ssl_protocol=protocol)
        return SimpleNamespace(_connection=SimpleNamespace(_transport=transport)), protocol, received

    def test_counts_tls_bytes_by_phase_and_still_delivers_them(self):
        metrics = SimpleNamespace(phase="setup")
        counter = bench.WireCounter(metrics)
        connection, protocol, received = self.fake_connection()
        counter.track(connection)
        protocol.buffer_updated(100)
        metrics.phase = "sync"
        protocol.buffer_updated(40)
        protocol.buffer_updated(2)
        self.assertEqual(received, [100, 40, 2])
        self.assertEqual(dict(counter.bytes), {"setup": 100, "sync": 42})
        self.assertEqual((counter.tracked, counter.untracked), (1, 0))

    def test_unknown_transport_is_reported_not_counted_as_zero(self):
        counter = bench.WireCounter(SimpleNamespace(phase="sync"))
        counter.track(SimpleNamespace(_connection=SimpleNamespace(_transport=object())))
        self.assertEqual((counter.tracked, counter.untracked), (0, 1))


class AppendVerificationTests(unittest.TestCase):
    def states(self):
        before = {"raw_rows": 2610, "normalized_rows": 2610, "raw_hash": "r", "normalized_hash": "n",
                  "classification_codes": "etf" * 3}
        after = dict(before, raw_rows=2615, normalized_rows=2615)
        snap_before = {"cursors_and_success": [["item-0", "c0", None, None], ["item-1", "c1", None, None]],
                       "publication_marker": [{"last_published_run_id": "old", "published_at": "t0"}]}
        snap_after = {"cursors_and_success": [["item-0", "c0b", "t1", "t1"], ["item-1", "c1b", "t1", "t1"]],
                      "publication_marker": [{"last_published_run_id": "run", "published_at": "t1"}]}
        return before, after, snap_before, snap_after

    def test_successful_append_passes_every_positive_check(self):
        result = bench.verify_append(*self.states(), "run")
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["classification_changed_positions"], [])
        self.assertEqual(result["classification_digest_before"], result["classification_digest_after"])

    def test_each_positive_check_fails_independently(self):
        cases = {
            "rows_increased_by_append": lambda b, a, sb, sa: a.update(raw_rows=2616),
            "every_cursor_advanced": lambda b, a, sb, sa: sa["cursors_and_success"][1].__setitem__(1, "c1"),
            "publication_marker_advanced": lambda b, a, sb, sa: sa["publication_marker"][0].update(
                last_published_run_id="old"),
            "existing_raw_rows_unchanged": lambda b, a, sb, sa: a.update(raw_hash="x"),
            "existing_normalized_rows_unchanged": lambda b, a, sb, sa: a.update(normalized_hash="x"),
        }
        for check, mutate in cases.items():
            with self.subTest(check=check):
                states = self.states()
                mutate(*states)
                result = bench.verify_append(*states, "run")
                self.assertFalse(result["passed"])
                self.assertFalse(result["checks"][check])

    def test_changed_classifications_are_listed_without_failing(self):
        before, after, snap_before, snap_after = self.states()
        after["classification_codes"] = "etf" + "rff" + "etf"
        result = bench.verify_append(before, after, snap_before, snap_after, "run")
        self.assertTrue(result["passed"])
        self.assertEqual(result["classification_changed_positions"], [1])
        self.assertNotEqual(result["classification_digest_before"], result["classification_digest_after"])
        self.assertEqual(bench.decode_classification("rff"), ("refund", False, False))
        self.assertEqual(bench.decode_classification("---"), (None, None, None))
