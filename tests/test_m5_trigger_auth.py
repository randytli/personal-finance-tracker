"""Signed scheduler-trigger authentication (api.trigger_auth).

Pure tests always run. SQL-signer and nonce-store tests need a disposable
loopback cluster and PFT_M5_TRIGGER_SYNTHETIC_TEST=1. Secrets are random per
test and never written to disk.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
import subprocess
import unittest
import uuid

from api import trigger_auth as auth

NOW = datetime(2026, 10, 2, 4, 30, tzinfo=timezone.utc)
AUD = "pft-jobs-synthetic"
PATH = "/trigger"
BODY = b'{"kind": "tick"}'  # pg_net's spacing differs from the canonical form


def signed(secret, *, kid="v1", ts=None, nonce=None, payload=None, audience=AUD, path=PATH):
    return {auth.HEADER: auth.sign(secret, audience=audience, key_id=kid,
                                   timestamp=int((ts or NOW).timestamp()),
                                   nonce=nonce or secrets.token_hex(16), method="POST",
                                   path=path, payload=payload or {"kind": "tick"})}


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.secret = secrets.token_hex(32).encode()
        self.keys = {"v1": self.secret}

    def check(self, headers, body=BODY, **overrides):
        options = dict(method="POST", path=PATH, body=body, keys=self.keys, audience=AUD,
                       expected_path=PATH, now=NOW)
        options.update(overrides)
        return auth.verify(headers, **options)

    def rejected(self, status, headers, body=BODY, **overrides):
        with self.assertRaises(auth.TriggerAuthError) as caught:
            self.check(headers, body, **overrides)
        self.assertEqual(caught.exception.status, status, caught.exception.reason)
        return caught.exception.reason

    def test_valid_signature_with_noncanonical_body_spacing(self):
        claim = self.check(signed(self.secret))
        self.assertEqual((claim.key_id, claim.kind, claim.timestamp), ("v1", "tick", NOW))
        upper = {auth.HEADER.upper(): signed(self.secret)[auth.HEADER]}
        self.check(upper)

    def test_missing_malformed_unknown_and_forged(self):
        self.rejected(401, {})
        self.rejected(401, {auth.HEADER: "Bearer something"})
        self.rejected(401, signed(self.secret, kid="v2"))
        self.rejected(401, signed(secrets.token_hex(32).encode()))
        duplicate = {auth.HEADER: signed(self.secret)[auth.HEADER],
                     auth.HEADER.title(): signed(self.secret)[auth.HEADER]}
        self.rejected(401, duplicate)

    def test_signature_binds_audience_path_method_and_body(self):
        self.rejected(401, signed(self.secret, audience="pft-jobs-production"))
        self.rejected(404, signed(self.secret), path="/other")
        self.rejected(404, signed(self.secret), method="GET")
        other_path = signed(self.secret, path="/other")
        self.rejected(401, other_path)
        self.rejected(401, signed(self.secret), body=b'{"kind": "backup"}')
        self.rejected(401, signed(self.secret), body=b"not json")
        self.rejected(413, signed(self.secret), body=b" " * (auth.MAX_BODY + 1))
        # A correctly signed but unsupported kind is still refused.
        self.rejected(400, signed(self.secret, payload={"kind": "backup"}), body=b'{"kind":"backup"}')

    def test_timestamp_window(self):
        self.check(signed(self.secret, ts=NOW - auth.WINDOW))
        self.check(signed(self.secret, ts=NOW + auth.WINDOW))
        self.rejected(401, signed(self.secret, ts=NOW - auth.WINDOW - timedelta(seconds=1)))
        self.rejected(401, signed(self.secret, ts=NOW + auth.WINDOW + timedelta(seconds=1)))

    def test_rotation_and_configuration_fail_closed(self):
        new = secrets.token_hex(32).encode()
        self.keys = {"v1": self.secret, "v2": new}
        self.check(signed(new, kid="v2"))
        self.check(signed(self.secret, kid="v1"))
        self.rejected(503, signed(self.secret), keys={})
        self.rejected(503, signed(b"short"), keys={"v1": b"short"})
        self.rejected(503, signed(self.secret), audience="")


class HandleTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.secret = secrets.token_hex(32).encode()
        self.store = auth.MemoryNonceStore()
        self.calls = 0

    async def run_once(self):
        self.calls += 1
        return {"status": "idle"}

    async def deliver(self, headers, now=NOW, body=BODY):
        return await auth.handle_trigger(method="POST", path=PATH, headers=headers, body=body,
                                         keys={"v1": self.secret}, audience=AUD,
                                         expected_path=PATH, nonce_store=self.store,
                                         run_once=self.run_once, now=now)

    async def test_replay_is_refused_and_forgery_never_runs_or_claims(self):
        headers = signed(self.secret)
        self.assertEqual(await self.deliver(headers), (200, {"status": "idle"}))
        self.assertEqual(await self.deliver(headers), (409, {"error": "replayed request"}))
        self.assertEqual(self.calls, 1)
        status, payload = await self.deliver(signed(secrets.token_hex(32).encode()))
        self.assertEqual((status, self.calls, len(self.store.seen)), (401, 1, 1))
        self.assertNotIn(self.secret.decode(), json.dumps(payload))

    async def test_nonce_expires_only_after_window(self):
        headers = signed(self.secret)
        await self.deliver(headers)
        status, _ = await self.deliver(headers, now=NOW + auth.WINDOW + timedelta(seconds=1))
        self.assertEqual(status, 401)  # stale, not re-runnable after expiry either
        self.assertEqual(self.calls, 1)


@unittest.skipUnless(os.environ.get("PFT_M5_TRIGGER_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import create_async_engine
        base = make_url(os.environ["DATABASE_URL"])
        self.assertIn(base.host, {"127.0.0.1", "localhost"})
        self.assertGreaterEqual(base.port, 55000)
        self.bin = Path(os.environ.get("PFT_PG_BIN_DIR", "/usr/lib/postgresql/16/bin"))
        self.args = ["--no-password", "-h", base.host, "-p", str(base.port), "-U", base.username]
        self.pg_env = {**os.environ, "PGPASSWORD": base.password or "", "PGCONNECT_TIMEOUT": "5"}
        self.name = "pft_m5_trigger_" + uuid.uuid4().hex[:12]
        subprocess.run([str(self.bin / "createdb"), *self.args, self.name], env=self.pg_env,
                       check=True, timeout=15)
        self.engine = create_async_engine(base.set(database=self.name))
        template = (Path(__file__).resolve().parents[1] / "experiments" / "m5_cloud"
                    / "trigger_cron.sql.template").read_text().replace("{crypto}", "public")
        connection = await self.engine.raw_connection()
        try:
            await connection.driver_connection.execute("CREATE EXTENSION pgcrypto")
            await connection.driver_connection.execute(template)
        finally:
            connection.close()

    async def asyncTearDown(self):
        await self.engine.dispose()
        subprocess.run([str(self.bin / "dropdb"), *self.args, "--if-exists", self.name],
                       env=self.pg_env, check=True, timeout=15)

    async def test_sql_signer_matches_python_verifier(self):
        from sqlalchemy import text
        secret = secrets.token_hex(32)
        async with self.engine.connect() as connection:
            header = await connection.scalar(text(
                "SELECT pft_ops.trigger_signature(:s, :a, 'v1', :p, 'tick')"),
                {"s": secret, "a": AUD, "p": PATH})
            other = await connection.scalar(text(
                "SELECT pft_ops.trigger_signature(:s, :a, 'v1', :p, 'tick')"),
                {"s": secret, "a": AUD, "p": PATH})
        claim = auth.verify({auth.HEADER: header}, method="POST", path=PATH, body=BODY,
                            keys={"v1": secret.encode()}, audience=AUD, expected_path=PATH)
        self.assertEqual(claim.kind, "tick")
        self.assertNotEqual(claim.nonce, auth._FIELD.fullmatch(other).group(3))
        with self.assertRaises(auth.TriggerAuthError):
            auth.verify({auth.HEADER: header}, method="POST", path=PATH, body=BODY,
                        keys={"v1": secret.encode()}, audience="pft-jobs-production",
                        expected_path=PATH)

    async def test_sql_nonce_store_is_single_use_and_bounded(self):
        from sqlalchemy import text
        store = auth.SqlNonceStore(self.engine)
        nonce = secrets.token_hex(16)
        self.assertTrue(await store.claim(nonce, NOW + auth.WINDOW, NOW))
        self.assertFalse(await store.claim(nonce, NOW + auth.WINDOW, NOW))
        later = NOW + auth.WINDOW + timedelta(seconds=1)
        self.assertTrue(await store.claim(secrets.token_hex(16), later + auth.WINDOW, later))
        async with self.engine.connect() as connection:
            remaining = await connection.scalar(text("SELECT count(*) FROM pft_ops.trigger_nonces"))
        self.assertEqual(remaining, 1)
        with self.assertRaises(ValueError):
            auth.SqlNonceStore(self.engine, table="x; DROP TABLE y")

    async def test_overlapping_valid_deliveries_are_serialised_by_jobs_lock(self):
        import asyncio
        from unittest.mock import patch
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from api import db as database
        from scripts.pft_m5_scheduler_draft import run_scheduler_once
        with patch.object(database, "engine", self.engine):
            await database.init_db()
        store, secret, started = auth.SqlNonceStore(self.engine), secrets.token_hex(32), asyncio.Event()
        syncs = []

        async def slow_sync(user_id, **kwargs):
            syncs.append(kwargs["trigger_source"])
            started.set()
            await asyncio.sleep(0.5)
            return {"status": "success"}

        async def no_check(*_):
            return None

        async def run_once():
            return await run_scheduler_once(
                "trigger-test-user", verify_capability=no_check,
                engine_factory=lambda: create_async_engine(self.engine.url, pool_size=4, max_overflow=0),
                verify_identity=no_check, sync=slow_sync, backup_fn=None)

        async def deliver():
            return await auth.handle_trigger(
                method="POST", path=PATH, headers=signed(secret.encode(), ts=datetime.now(timezone.utc)),
                body=BODY, keys={"v1": secret.encode()}, audience=AUD, expected_path=PATH,
                nonce_store=store, run_once=run_once)

        first = asyncio.create_task(deliver())
        await started.wait()
        second = await deliver()
        self.assertEqual(second, (200, {"status": "busy"}))
        self.assertEqual(await first, (200, {"status": "success"}))
        self.assertEqual(syncs, ["jobs"])  # the busy delivery never reached sync
        self.assertEqual(await deliver(), (200, {"status": "success"}))  # lock released


if __name__ == "__main__":
    unittest.main()
