"""Packet and cleanup checks: mocks only, no database or provider access."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI, HTTPException
from experiments.m5_cloud.pool_probe_support import register
from scripts.pft_m5_prepare_cloud_packet import closure, stage_packet


class PacketTests(unittest.TestCase):
    def test_roles_are_separate_and_templates_stay_outside_upload(self):
        with tempfile.TemporaryDirectory(prefix="pft-m5-packet-test-") as parent:
            target = Path(parent) / "packet"
            stage_packet(target)
            self.assertTrue((target / "jobs/api/jobs.py").is_file())
            self.assertFalse((target / "reader/api/jobs.py").exists())
            for role in ("reader", "jobs"):
                self.assertFalse((target / role / "api/main.py").exists())
                self.assertFalse(list((target / role).rglob("*.env*")))
                self.assertIn(f"config.role != {role!r}", (target / role / "main.py").read_text())
                self.assertTrue((target / f"{role}.env.template").exists())
            route = target / "web-probe/app/api/probe/route.js"
            self.assertTrue((route.parent / "../../probe-handler.mjs").resolve().is_file())
            with self.assertRaises(RuntimeError):
                stage_packet(target)

    def test_reader_closure_excludes_scheduler_backup_and_plaid_routes(self):
        reader = {path.name for path in closure("reader")}
        self.assertTrue({"analytics.py", "review.py"} <= reader)
        self.assertTrue(reader.isdisjoint({"jobs.py", "sync_all.py", "backup.py", "plaid.py"}))


class PoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_bounds_never_construct_engine(self):
        app = FastAPI()
        def engine(*_):
            raise AssertionError("Must not construct")
        register(app, lambda: None, None, engine)
        with self.assertRaises(HTTPException) as error:
            await app.routes[-1].endpoint(reads=21, config=object())
        self.assertEqual(error.exception.status_code, 422)

    async def test_failure_joins_siblings_before_disposal(self):
        app = FastAPI()
        active = 0
        disposed = False
        entered = asyncio.Event()
        class Connection:
            async def __aenter__(self):
                nonlocal active
                active += 1
                if active == 2:
                    entered.set()
                return self
            async def __aexit__(self, *_):
                nonlocal active
                active -= 1
        class Engine:
            def connect(self):
                return Connection()
            async def dispose(self):
                nonlocal disposed
                self_test.assertEqual(active, 0)
                disposed = True
        self_test = self
        first = True
        async def identity(*_):
            nonlocal first
            if first:
                first = False
                await entered.wait()
                raise RuntimeError("synthetic failure")
            await asyncio.Event().wait()
        register(app, lambda: None, identity, lambda *_: Engine())
        with self.assertRaises(ExceptionGroup):
            await app.routes[-1].endpoint(reads=2, concurrency=2, config=object())
        self.assertTrue(disposed)


if __name__ == "__main__":
    unittest.main()
