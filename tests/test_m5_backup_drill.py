"""M5 backup drill: envelope, store, retention and guarded full-chain tests.

Database tests need a disposable loopback PostgreSQL cluster and the
PFT_M5_BACKUP_SYNTHETIC_TEST=1 opt-in. Keys are generated per test and never
leave the temporary directory.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

import asyncpg
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from sqlalchemy.engine import make_url

from scripts import pft_m5_backup_drill as drill


def _names(start, days):
    return [f"pft-backup-{start + timedelta(days=d):%Y%m%dT%H%M%SZ}-{d:016x}.pftenc3"
            for d in range(days)]


class EnvelopeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pft-drill-"))
        self.key = X25519PrivateKey.generate()
        self.archive = self.dir / "archive"
        self.archive.write_bytes(os.urandom(3 * drill.CHUNK + 17))
        self.manifest = {"archive_sha256": drill.sha256_file(self.archive),
                         "archive_size": self.archive.stat().st_size, "schemas": ["public"]}

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.dir)], check=True)

    def sealed(self):
        bundle = self.dir / "bundle"
        drill.seal(self.archive, json.dumps(self.manifest).encode(), self.key.public_key(), bundle)
        return bundle

    def test_round_trip_needs_only_public_key_to_seal(self):
        bundle = self.sealed()
        self.assertNotIn(self.archive.read_bytes()[:64], bundle.read_bytes())
        out = self.dir / "out"
        self.assertEqual(drill.open_sealed(bundle, self.key, out), self.manifest)
        self.assertEqual(out.read_bytes(), self.archive.read_bytes())

    def test_wrong_key_tamper_and_truncation_publish_nothing(self):
        bundle = self.sealed()
        with self.assertRaisesRegex(drill.DrillError, "different recipient"):
            drill.open_sealed(bundle, X25519PrivateKey.generate(), self.dir / "a")
        data = bytearray(bundle.read_bytes())
        data[drill.HEADER + 100] ^= 1
        tampered = self.dir / "tampered"
        tampered.write_bytes(bytes(data))
        with self.assertRaisesRegex(drill.DrillError, "authentication failed"):
            drill.open_sealed(tampered, self.key, self.dir / "b")
        header = bytearray(bundle.read_bytes())
        header[len(drill.MAGIC) + 64] ^= 1  # nonce is authenticated header data
        (self.dir / "header").write_bytes(bytes(header))
        with self.assertRaisesRegex(drill.DrillError, "authentication failed"):
            drill.open_sealed(self.dir / "header", self.key, self.dir / "c")
        (self.dir / "short").write_bytes(bundle.read_bytes()[:-1])
        with self.assertRaisesRegex(drill.DrillError, "size"):
            drill.open_sealed(self.dir / "short", self.key, self.dir / "d")
        for name in "abcd":
            self.assertFalse((self.dir / name).exists())
        self.assertEqual([p for p in self.dir.iterdir() if p.name.startswith(".pft-open-")], [])

    def test_manifest_hash_mismatch_is_rejected_after_authentication(self):
        self.manifest["archive_sha256"] = "0" * 64
        with self.assertRaisesRegex(drill.DrillError, "does not match manifest"):
            drill.open_sealed(self.sealed(), self.key, self.dir / "out")
        self.assertFalse((self.dir / "out").exists())

    def test_existing_destinations_are_never_overwritten(self):
        bundle = self.sealed()
        with self.assertRaisesRegex(drill.DrillError, "already exists"):
            drill.seal(self.archive, b"{}", self.key.public_key(), bundle)
        (self.dir / "out").write_bytes(b"keep")
        with self.assertRaisesRegex(drill.DrillError, "already exists"):
            drill.open_sealed(bundle, self.key, self.dir / "out")
        self.assertEqual((self.dir / "out").read_bytes(), b"keep")


class StoreAndRetentionTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pft-store-"))
        self.store = drill.LocalDirectoryStore(self.dir)

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.dir)], check=True)

    def test_put_requires_readback_hash_and_unique_names(self):
        source = self.dir / "payload"
        source.write_bytes(b"sealed bytes")
        name = drill.object_name(datetime(2026, 10, 2, tzinfo=timezone.utc))
        with self.assertRaisesRegex(drill.DrillError, "readback"):
            self.store.put(name, source, "0" * 64)
        self.assertEqual(self.store.list(), [])
        self.store.put(name, source, drill.sha256_file(source))
        with self.assertRaisesRegex(drill.DrillError, "already exists"):
            self.store.put(name, source, drill.sha256_file(source))
        with self.assertRaisesRegex(drill.DrillError, "invalid object name"):
            self.store.put("../escape.pftenc3", source, drill.sha256_file(source))

    def test_retention_covers_local_policy(self):
        names = _names(datetime(2026, 1, 1, 3, tzinfo=timezone.utc), 200)
        keep = drill.retention_keep(names)
        stamps = sorted(n.split("-")[2] for n in keep)
        self.assertIn(names[-1], keep)
        self.assertTrue(set(names[-7:]) <= keep)          # 7 most recent days
        self.assertGreaterEqual(len(keep), 7 + 3)         # plus older weekly/monthly points
        self.assertLessEqual(len(keep), 7 + 4 + 3)
        newest = datetime.strptime(names[-1].split("-")[2], "%Y%m%dT%H%M%SZ")
        oldest = datetime.strptime(stamps[0], "%Y%m%dT%H%M%SZ")
        self.assertEqual((oldest.year, oldest.month), (newest.year, newest.month - 2))  # 3 months

    def test_prune_refuses_without_verified_newest_and_keeps_policy(self):
        source = self.dir / "payload"
        source.write_bytes(b"x")
        for name in _names(datetime(2026, 8, 1, 3, tzinfo=timezone.utc), 40):
            self.store.put(name, source, drill.sha256_file(source))
        with self.assertRaisesRegex(drill.DrillError, "verified newest"):
            drill.prune(self.store, "pft-backup-20990101T000000Z-0000000000000000.pftenc3")
        self.assertEqual(len(self.store.list()), 40)
        newest = self.store.list()[-1]
        removed = drill.prune(self.store, newest)
        self.assertTrue(removed)
        self.assertEqual(set(self.store.list()), drill.retention_keep(_names(
            datetime(2026, 8, 1, 3, tzinfo=timezone.utc), 40)))


class CatalogNormalizationTests(unittest.TestCase):
    def test_only_the_equivalent_array_cast_rewrite_is_normalized(self):
        source = ("t ck CHECK (((s)::text = ANY ((ARRAY['a'::character varying, "
                  "'b'::character varying])::text[])))")
        restored = ("t ck CHECK (((s)::text = ANY (ARRAY[('a'::character varying)::text, "
                    "('b'::character varying)::text])))")
        self.assertEqual(drill.canonical_ddl(source), drill.canonical_ddl(restored))
        changed = source.replace("'b'", "'c'")
        self.assertNotEqual(drill.canonical_ddl(changed), drill.canonical_ddl(restored))
        self.assertEqual(drill.canonical_ddl("idx ON t USING btree (x)"), "idx ON t USING btree (x)")


class ProfileGuardTests(unittest.TestCase):
    def test_rejects_non_disposable_targets(self):
        for url, role in (("postgresql://u@db:5432/pft_m5_x", "source"),
                          ("postgresql://u@127.0.0.1:5434/pft_m5_x", "source"),
                          ("postgresql://u@10.0.0.5:55439/pft_m5_x", "source"),
                          ("postgresql://u@127.0.0.1:55439/pft_production_backfill", "source"),
                          ("postgresql://u@127.0.0.1:55439/postgres", "target"),
                          ("postgresql://u@127.0.0.1:55439/pft_restore_m5_xyz", "target")):
            with self.subTest(url=url), self.assertRaises(drill.DrillError):
                drill._profile(url, role=role)
        with patch.dict(os.environ, {"PLAID_ENV": "production"}), self.assertRaises(drill.DrillError):
            drill._profile("postgresql://u@127.0.0.1:55439/pft_m5_x", role="source")
        drill._profile("postgresql://u@127.0.0.1:55439/pft_m5_x", role="source")


@unittest.skipUnless(os.environ.get("PFT_M5_BACKUP_SYNTHETIC_TEST") == "1", "isolated PostgreSQL opt-in")
class FullChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        from api import db as database
        from scripts.pft_m5_backup_fixture import seed
        base = make_url(os.environ["DATABASE_URL"])
        self.assertIn(base.host, drill.LOOPBACK)
        self.assertGreaterEqual(base.port, 55000)
        self.dir = Path(tempfile.mkdtemp(prefix="pft-chain-"))
        (self.dir / "store").mkdir()
        self.store = drill.LocalDirectoryStore(self.dir / "store")
        self.source = "pft_m5_backup_" + uuid.uuid4().hex[:12]
        self.target = "pft_restore_m5_" + uuid.uuid4().hex
        self.args = ["-h", base.host, "-p", str(base.port), "-U", base.username]
        subprocess.run([str(drill.BIN / "createdb"), *self.args, self.source], check=True)
        self.source_url = base.set(drivername="postgresql", database=self.source).render_as_string(False)
        self.target_url = base.set(drivername="postgresql", database=self.target).render_as_string(False)
        engine = create_async_engine(base.set(database=self.source))
        try:
            with patch.object(database, "engine", engine):
                await database.init_db()
            self.counts = await seed(engine, rows=600)
        finally:
            await engine.dispose()
        self.key = X25519PrivateKey.generate()
        connection = await asyncpg.connect(host=base.host, port=base.port, user=base.username,
                                           database=self.source)
        try:
            self.public_tables = await connection.fetchval(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        finally:
            await connection.close()

    async def asyncTearDown(self):
        for name in (self.target, self.source):
            subprocess.run([str(drill.BIN / "dropdb"), *self.args, "--if-exists", name],
                           check=True, stderr=subprocess.DEVNULL)
        subprocess.run(["rm", "-rf", str(self.dir)], check=True)

    async def execute(self, database, sql):
        url = make_url(self.source_url).set(database=database)
        connection = await asyncpg.connect(host=url.host, port=url.port, user=url.username,
                                           database=database)
        try:
            await connection.execute(sql)
        finally:
            await connection.close()

    async def test_backup_restore_fingerprints_match_snapshot_not_later_writes(self):
        created = await drill.create_backup(self.source_url, self.key.public_key(), self.store,
                                            work_dir=self.dir, app_commit="test")
        self.assertEqual(created["tables"], self.public_tables)
        self.assertEqual(created["empty_tables"], [])  # every application table is populated
        self.assertGreaterEqual(created["rows"], 2 * self.counts["raw"])
        # A write after the backup must not appear in the restore.
        await self.execute(self.source, "DELETE FROM manual_category_overrides")
        restored = await drill.restore_backup(self.store, created["object"]["name"], self.key,
                                              self.target_url, work_dir=self.dir)
        self.assertTrue(restored["equal"], restored["mismatches"])
        self.assertEqual(restored["rows"], created["rows"])
        # Comparison is not vacuous: a changed restored row is reported.
        await self.execute(self.target, "UPDATE accounts SET name='changed' WHERE account_id='account-0-0'")
        connection = await asyncpg.connect(host="127.0.0.1", port=make_url(self.target_url).port,
                                           user=make_url(self.target_url).username, database=self.target)
        try:
            await connection.execute("SET TIME ZONE 'UTC'")
            after = await drill.database_fingerprint(connection, ["public"])
        finally:
            await connection.close()
        with tempfile.TemporaryDirectory(dir=self.dir) as scratch:
            manifest = drill.open_sealed(self.store.get(created["object"]["name"], Path(scratch) / "b"),
                                         self.key, Path(scratch) / "a")
        self.assertEqual(drill.compare_fingerprints(manifest["fingerprint"], after), ["tables:public.accounts"])
        await self.execute(self.target, "DROP INDEX ix_raw_account_date")
        connection = await asyncpg.connect(host="127.0.0.1", port=make_url(self.target_url).port,
                                           user=make_url(self.target_url).username, database=self.target)
        try:
            after = await drill.database_fingerprint(connection, ["public"])
        finally:
            await connection.close()
        self.assertIn("catalog", drill.compare_fingerprints(manifest["fingerprint"], after))
        self.assertNotIn(self.source, created["object"]["name"])

    async def test_restore_refuses_existing_target_and_wrong_key(self):
        created = await drill.create_backup(self.source_url, self.key.public_key(), self.store,
                                            work_dir=self.dir)
        with self.assertRaisesRegex(drill.DrillError, "different recipient"):
            await drill.restore_backup(self.store, created["object"]["name"], X25519PrivateKey.generate(),
                                       self.target_url, work_dir=self.dir)
        subprocess.run([str(drill.BIN / "createdb"), *self.args, self.target], check=True)
        with self.assertRaisesRegex(drill.DrillError, "createdb failed"):
            await drill.restore_backup(self.store, created["object"]["name"], self.key,
                                       self.target_url, work_dir=self.dir)

    async def test_unselected_application_schema_fails_closed(self):
        await self.execute(self.source, "CREATE SCHEMA pft_ops; CREATE TABLE pft_ops.t (x int)")
        with self.assertRaisesRegex(drill.DrillError, "unselected non-provider schema"):
            await drill.create_backup(self.source_url, self.key.public_key(), self.store,
                                      work_dir=self.dir)
        self.assertEqual(self.store.list(), [])
        created = await drill.create_backup(self.source_url, self.key.public_key(), self.store,
                                            schemas=("public", "pft_ops"), work_dir=self.dir)
        self.assertEqual(created["tables"], self.public_tables + 1)


if __name__ == "__main__":
    unittest.main()
