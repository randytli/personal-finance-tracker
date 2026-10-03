"""Local-only regression checks for the reviewed M5 acceptance tools."""
import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from experiments.m5_cloud import cron_controller, cron_observer, cron_evidence


class CronControllerTests(unittest.TestCase):
    def test_all_cases_without_http(self):
        with TemporaryDirectory() as root:
            private = Path(root)
            (private / "m5_trigger_key_v1").write_text("s" * 64)
            (private / "m5_vercel_bypass").write_text("synthetic-bypass")
            with patch.object(cron_controller, "send", return_value={"status": 200, "label": "mock"}) as send:
                result = cron_controller.run(private, "https://synthetic.invalid/trigger")
        self.assertEqual(len(result["results"]), 8)
        self.assertEqual(send.call_count, 8)
        calls = send.call_args_list
        header = cron_controller.trigger_auth.HEADER
        self.assertNotIn(header, calls[0].args[1])
        self.assertNotIn("x-vercel-protection-bypass", calls[4].args[1])
        self.assertEqual(calls[5].args[1][header], calls[6].args[1][header])
        self.assertEqual(calls[7].kwargs["body"], b'{"kind":"backup"}')
        self.assertNotIn("synthetic-bypass", str(result))
        self.assertNotIn("s" * 64, str(result))


class CronReadToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_observer_readonly_progress_and_identity(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        row = dict(at=now, jobs_backends=1, jobs_busy=1, client_backends=2,
                   jobs_lock=[1], sync_lock=[], started=1, finished=1, running_runs=0)
        with TemporaryDirectory() as root:
            password = Path(root) / "password"
            password.write_text("synthetic-password")
            args = SimpleNamespace(password_file=password, limit_seconds=1,
                                   wait_finished=1, wait_started=0, label="local-only")
            connection = AsyncMock()
            connection.fetchval.side_effect = [cron_observer.ROLE, now]
            connection.fetchrow.return_value = row
            with patch.object(cron_observer.asyncpg, "connect", return_value=connection), patch.object(cron_observer.ssl, "create_default_context"):
                result = await cron_observer.observe(args)
            self.assertIsNotNone(result["condition_reached_after_s"])
            self.assertEqual(result["peaks"]["jobs_backends"], 1)
            connection.close.assert_awaited_once()
            self.assertTrue(connection.fetchrow.call_args.args[0].strip().startswith("select"))
            rejected = AsyncMock()
            rejected.fetchval.return_value = "wrong-role"
            with patch.object(cron_observer.asyncpg, "connect", return_value=rejected), patch.object(cron_observer.ssl, "create_default_context"):
                with self.assertRaisesRegex(RuntimeError, "identity rejected"):
                    await cron_observer.observe(args)
            rejected.close.assert_awaited_once()
            rejected.fetchrow.assert_not_awaited()

    async def test_export_only_declared_selects_and_closes(self):
        with TemporaryDirectory() as root:
            password = Path(root) / "password"
            password.write_text("synthetic-password")
            connection = AsyncMock()
            connection.fetch.return_value = [{"synthetic": True}]
            with patch.object(cron_evidence.asyncpg, "connect", return_value=connection), patch.object(cron_evidence.ssl, "create_default_context"):
                result = await cron_evidence.export(password)
        self.assertEqual(set(result), set(cron_evidence.QUERIES))
        self.assertEqual([call.args[0] for call in connection.fetch.call_args_list], list(cron_evidence.QUERIES.values()))
        self.assertTrue(all(query.startswith("select ") for query in cron_evidence.QUERIES.values()))
        connection.execute.assert_not_awaited()
        connection.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
