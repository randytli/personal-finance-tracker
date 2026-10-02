"""age backup runner, GitHub release store and multi-format restore tool.

Pure tests always run. Tests marked "age" need PFT_AGE_BIN (a verified age
v1.3.x binary; age-keygen and age-plugin-batchpass next to it). Database
tests also need a disposable loopback cluster and
PFT_M5_BACKUP_SYNTHETIC_TEST=1. Every key pair is generated in a temporary
directory per test and deleted with it.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import uuid

from deploy.backup_runner import pft_backup_runner as runner
import release_store  # same module object the runner imported
from scripts import pft_backup_restore as restore_tool

AGE = os.environ.get("PFT_AGE_BIN", "")
PG_BIN = os.environ.get("PFT_PG_BIN_DIR", "/usr/lib/postgresql/16/bin")
needs_age = unittest.skipUnless(AGE and Path(AGE).is_file(), "PFT_AGE_BIN not set")
needs_db = unittest.skipUnless(AGE and os.environ.get("PFT_M5_BACKUP_SYNTHETIC_TEST") == "1",
                               "age + isolated PostgreSQL opt-in")


def keypair(directory, label):
    identity = Path(directory) / f"{label}.key"
    subprocess.run([str(Path(AGE).parent / "age-keygen"), "-o", str(identity)], check=True,
                   capture_output=True)
    recipient = subprocess.run([str(Path(AGE).parent / "age-keygen"), "-y", str(identity)], check=True,
                               capture_output=True, text=True).stdout.strip()
    return identity, recipient


def points(start, days):
    return [f"pft-backup-{start + timedelta(days=d):%Y%m%dT%H%M%SZ}-{d:016x}" for d in range(days)]


FAKE_RECIPIENTS = ["age1" + c * 58 for c in "qpz"]


class RecipientsAndPolicyTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, lines):
        path = self.dir / "recipients.txt"
        path.write_text("\n".join(lines) + "\n")
        return path

    def test_at_least_two_distinct_x25519_recipients(self):
        self.assertEqual(runner.read_recipients(self.write(["# daily", FAKE_RECIPIENTS[0], "",
                                                            "# emergency", FAKE_RECIPIENTS[1]])),
                         FAKE_RECIPIENTS[:2])
        for lines in ([FAKE_RECIPIENTS[0]], [FAKE_RECIPIENTS[0]] * 2,
                      [FAKE_RECIPIENTS[0], "ssh-ed25519 AAAA test"],
                      [FAKE_RECIPIENTS[0], "age1pq1" + "q" * 100], [FAKE_RECIPIENTS[0], "AGE-SECRET-KEY-1X"]):
            with self.subTest(lines=lines), self.assertRaises(runner.RunnerError):
                runner.read_recipients(self.write(lines))

    def test_connection_policy(self):
        self.assertEqual(runner.connection_policy({"PGHOST": "127.0.0.1", "PGPORT": "55439"}), "loopback-test")
        cert = self.dir / "ca.crt"
        cert.write_text("public CA")
        self.assertEqual(runner.connection_policy({"PGHOST": "aws-0-us-east-1.pooler.supabase.com",
                                                   "PGSSLMODE": "verify-full", "PGSSLROOTCERT": str(cert)}),
                         "verify-full")
        for env in ({"PGHOST": "127.0.0.1", "PGPORT": "5432"}, {"PGHOST": "db.example.com"},
                    {"PGHOST": "db.example.com", "PGSSLMODE": "require", "PGSSLROOTCERT": str(cert)},
                    {"PGHOST": "db.example.com", "PGSSLMODE": "verify-full", "PGSSLROOTCERT": "/missing"}):
            with self.subTest(env=env), self.assertRaises(runner.RunnerError):
                runner.connection_policy(env)


class RunnerBundleTests(unittest.TestCase):
    def test_sha256sums_match_runner_files(self):
        # The backup repository's workflow runs `sha256sum -c runner/SHA256SUMS`.
        listed = {}
        for line in (runner.HERE / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            listed[name] = digest
        from deploy.backup_runner import stage_backup_repo
        actual = {f"runner/{name}": hashlib.sha256((runner.HERE / name).read_bytes()).hexdigest()
                  for name in stage_backup_repo.RUNNER_FILES if name != "SHA256SUMS"}
        self.assertEqual(listed, actual, "regenerate deploy/backup_runner/SHA256SUMS")

    def test_stage_backup_repo_layout_and_fail_closed_recipients(self):
        from deploy.backup_runner import stage_backup_repo
        target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, target)
        (target / "README.md").write_text("initial commit")
        result = stage_backup_repo.stage(target, commit="abc123")
        self.assertIn(".github/workflows/pft-backup.yml", result["staged"])
        self.assertEqual(result["still_required_before_first_run"],
                         ["config/recipients.txt", "config/supabase-ca.crt"])
        self.assertEqual((target / "README.md").read_text(), "initial commit")
        self.assertEqual((target / "RESTORE.md").read_text(),
                         (runner.HERE.parents[1] / "docs" / "PFT_BACKUP_RESTORE_RUNBOOK.md").read_text())
        for line in (target / "runner" / "SHA256SUMS").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((target / name).read_bytes()).hexdigest(), digest)
        with self.assertRaises(runner.RunnerError):  # placeholders never pass as real keys
            runner.read_recipients(target / "config" / "recipients.txt.example")
        with self.assertRaisesRegex(stage_backup_repo.StageError, "refusing to overwrite"):
            stage_backup_repo.stage(target, commit="abc123")

    def test_workflow_pins_and_never_lives_in_github_workflows(self):
        text = (runner.HERE / "pft-backup.yml").read_text()
        self.assertIn("AGE_VERSION: v1.3.2", text)
        self.assertIn("sha256sum -c -", text)
        self.assertRegex(text, r"actions/checkout@[0-9a-f]{40}")
        self.assertRegex(text, r"postgres:17\.11-alpine@sha256:[0-9a-f]{64}")
        self.assertIn("contents: write", text)
        self.assertNotIn("secrets.", text.replace("secrets.PFT_BACKUP_PGPASSWORD", ""))
        self.assertFalse((Path(__file__).resolve().parents[1] / ".github" / "workflows" / "pft-backup.yml").exists())


class RetentionAndLocalStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / "store").mkdir()
        self.store = runner.LocalDirectoryStore(self.dir / "store")
        self.payload = self.dir / "x.age"
        self.payload.write_bytes(b"ciphertext")

    def test_retention_covers_local_7_4_3_policy(self):
        names = points(datetime(2026, 1, 1, 3, tzinfo=timezone.utc), 200)
        keep = runner.retention_keep(names)
        self.assertTrue(set(names[-7:]) <= keep)
        self.assertTrue(7 + 3 <= len(keep) <= 7 + 4 + 3)
        oldest = min(datetime.strptime(n.split("-")[2], "%Y%m%dT%H%M%SZ") for n in keep)
        self.assertEqual(oldest.month, 5)  # three calendar months back from July

    def test_put_is_atomic_and_prune_needs_verified_newest(self):
        names = points(datetime(2026, 8, 1, 3, tzinfo=timezone.utc), 40)
        for name in names:
            self.store.put(name, {"backup.dump.age": self.payload})
        with self.assertRaises(release_store.StoreError):
            self.store.put(names[0], {"backup.dump.age": self.payload})
        with self.assertRaises(release_store.StoreError):
            self.store.put("../escape", {"backup.dump.age": self.payload})
        with self.assertRaises(runner.RunnerError):
            runner.prune(self.store, "pft-backup-20990101T000000Z-0000000000000000")
        self.assertEqual(len(self.store.list()), 40)
        runner.prune(self.store, names[-1])
        self.assertEqual(set(self.store.list()), runner.retention_keep(names))
        with patch.object(release_store, "sha256_file", side_effect=["a" * 64, "b" * 64]):
            with self.assertRaisesRegex(release_store.StoreError, "readback"):
                self.store.put(runner.point_name(datetime.now(timezone.utc)), {"backup.dump.age": self.payload})
        self.assertEqual([p.name for p in (self.dir / "store").iterdir() if p.name.startswith(".")], [])


class FakeGitHub:
    """Minimal releases API plus a separate pre-signed 'storage' host."""

    def __init__(self, token, corrupt_uploads=False):
        self.token, self.corrupt, self.releases, self.blobs = token, corrupt_uploads, {}, {}
        self.storage_saw_auth, self.deleted_tags, self.next_id = [], [], 1
        fake = self

        class Storage(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                fake.storage_saw_auth.append("Authorization" in self.headers)
                data = fake.blobs[int(self.path.rsplit("/", 1)[1])]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class Api(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, code, body=None, headers=()):
                raw = json.dumps(body).encode() if body is not None else b""
                self.send_response(code)
                for key, value in headers:
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def authorized(self):
                if self.headers.get("Authorization") != f"Bearer {fake.token}":
                    self.reply(401, {"message": "bad credentials"})
                    return False
                return True

            def body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def do_GET(self):
                if not self.authorized():
                    return
                url = urlsplit(self.path)
                if url.path == "/repos/o/r/releases":
                    query = parse_qs(url.query)
                    size, page = int(query["per_page"][0]), int(query["page"][0])
                    ordered = sorted(fake.releases.values(), key=lambda r: r["id"])
                    self.reply(200, ordered[(page - 1) * size: page * size])
                elif url.path.startswith("/repos/o/r/releases/assets/"):
                    asset = url.path.rsplit("/", 1)[1]
                    self.reply(302, None, [("Location", f"http://127.0.0.1:{fake.storage.server_port}/blob/{asset}")])
                else:
                    self.reply(404, {})

            def do_POST(self):
                if not self.authorized():
                    return
                url = urlsplit(self.path)
                if url.path == "/repos/o/r/releases":
                    spec = json.loads(self.body())
                    rid, fake.next_id = fake.next_id, fake.next_id + 1
                    fake.releases[rid] = {"id": rid, "tag_name": spec["tag_name"], "draft": spec["draft"],
                                          "created_at": "2026-10-01T00:00:00Z", "assets": [],
                                          "upload_url": f"http://127.0.0.1:{fake.api.server_port}/upload/{rid}{{?name,label}}"}
                    self.reply(201, fake.releases[rid])
                elif url.path.startswith("/upload/"):
                    rid, data = int(url.path.rsplit("/", 1)[1]), self.body()
                    aid, fake.next_id = fake.next_id, fake.next_id + 1
                    fake.blobs[aid] = data[:-1] + b"X" if fake.corrupt else data
                    asset = {"id": aid, "name": parse_qs(url.query)["name"][0], "size": len(data),
                             "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                    fake.releases[rid]["assets"].append(asset)
                    self.reply(201, asset)
                else:
                    self.reply(404, {})

            def do_PATCH(self):
                if not self.authorized():
                    return
                rid = int(self.path.rsplit("/", 1)[1])
                fake.releases[rid].update(json.loads(self.body()))
                self.reply(200, fake.releases[rid])

            def do_DELETE(self):
                if not self.authorized():
                    return
                if "/git/refs/tags/" in self.path:
                    fake.deleted_tags.append(self.path.rsplit("/", 1)[1])
                else:
                    fake.releases.pop(int(self.path.rsplit("/", 1)[1]), None)
                self.reply(204)

        self.api = ThreadingHTTPServer(("127.0.0.1", 0), Api)
        self.storage = ThreadingHTTPServer(("127.0.0.1", 0), Storage)
        for server in (self.api, self.storage):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.api, self.storage):
            server.shutdown()
            server.server_close()

    def store(self, token=None):
        return release_store.GitHubReleaseStore(
            "o/r", token or self.token, api_url=f"http://127.0.0.1:{self.api.server_port}",
            upload_host=f"127.0.0.1:{self.api.server_port}")


class GitHubReleaseStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.token = uuid.uuid4().hex
        self.fake = FakeGitHub(self.token)
        self.addCleanup(self.fake.close)
        self.files = {}
        for asset in ("backup.dump.age", "manifest.json.age"):
            self.files[asset] = self.dir / asset
            self.files[asset].write_bytes(os.urandom(4096))

    def test_publish_only_after_readback_and_token_never_reaches_storage(self):
        store = self.fake.store()
        name = runner.point_name(datetime(2026, 10, 2, 8, 23, tzinfo=timezone.utc))
        result = store.put(name, self.files)
        self.assertEqual(set(result), set(self.files))
        self.assertEqual(store.list(), [name])
        self.assertEqual(self.fake.storage_saw_auth, [False, False])
        out = self.dir / "out"
        out.mkdir()
        got = store.get(name, out)
        for asset, path in got.items():
            self.assertEqual(path.read_bytes(), self.files[asset].read_bytes())
        self.assertNotIn(True, self.fake.storage_saw_auth)
        with self.assertRaises(release_store.StoreError):
            store.put(name, self.files)  # already exists
        store.delete(name)
        self.assertEqual((store.list(), self.fake.deleted_tags), ([], [name]))

    def test_readback_mismatch_leaves_no_point(self):
        self.fake.corrupt = True
        store = self.fake.store()
        with self.assertRaises(release_store.StoreError):
            store.put(runner.point_name(datetime.now(timezone.utc)), self.files)
        self.assertEqual((store.list(), self.fake.releases), ([], {}))

    def test_drafts_are_invisible_and_stale_ones_are_removed(self):
        store = self.fake.store()
        name = runner.point_name(datetime(2026, 9, 1, tzinfo=timezone.utc))
        with patch.object(store, "_download", side_effect=KeyboardInterrupt), \
             patch.object(store, "_json", wraps=store._json) as calls:
            # Simulate a crash where even the cleanup DELETE is lost.
            calls.side_effect = lambda method, path, **kw: (None if method == "DELETE"
                                                            else release_store.GitHubReleaseStore._json(store, method, path, **kw))
            with self.assertRaises(KeyboardInterrupt):
                store.put(name, self.files)
        self.assertEqual(store.list(), [])
        self.assertEqual(len(self.fake.releases), 1)
        self.assertEqual(store.remove_stale_drafts(now=datetime(2026, 10, 3, tzinfo=timezone.utc).timestamp()), [name])
        self.assertEqual(self.fake.releases, {})

    def test_pagination_wrong_token_and_untrusted_hosts(self):
        store = self.fake.store()
        for n in range(101):
            self.fake.releases[1000 + n] = {"id": 1000 + n, "tag_name": f"pft-backup-20260101T000000Z-{n:016x}",
                                            "draft": False, "assets": [], "created_at": "2026-01-01T00:00:00Z"}
        self.assertEqual(len(store.list()), 101)
        with self.assertRaisesRegex(release_store.StoreError, "401"):
            self.fake.store(token="wrong").list()
        with self.assertRaisesRegex(release_store.StoreError, "untrusted host"):
            store._request("GET", "https://evil.example.com/x")
        for bad in ("noslash", "o/r/x", ""):
            with self.subTest(bad=bad), self.assertRaises(release_store.StoreError):
                release_store.GitHubReleaseStore(bad, "t")


@needs_age
class AgeRecipientTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.daily, daily_pub = keypair(self.dir, "daily")
        self.emergency, emergency_pub = keypair(self.dir, "emergency")
        self.recipients = self.dir / "recipients.txt"
        self.recipients.write_text(f"# daily\n{daily_pub}\n# emergency\n{emergency_pub}\n")
        self.plain = self.dir / "plain"
        self.plain.write_bytes(os.urandom(200_000))
        self.sealed = self.dir / "plain.age"
        runner.Tools(age=AGE).age_encrypt(self.recipients, self.plain, self.sealed)

    def decrypt(self, *identities, source=None, env=None):
        out = self.dir / ("out-" + uuid.uuid4().hex)
        args = [a for i in identities for a in ("-i", str(i))]
        result = subprocess.run([AGE, "-d", *args, "-o", str(out), str(source or self.sealed)],
                                capture_output=True, env=env)
        return result.returncode, out.read_bytes() if out.exists() else None

    def test_each_key_alone_decrypts_so_losing_one_is_survivable(self):
        for identity in (self.daily, self.emergency):
            self.assertEqual(self.decrypt(identity), (0, self.plain.read_bytes()))
        stranger, _ = keypair(self.dir, "stranger")
        self.assertNotEqual(self.decrypt(stranger)[0], 0)

    def test_tampering_and_truncation_fail(self):
        data = bytearray(self.sealed.read_bytes())
        data[-100] ^= 1
        (self.dir / "tampered.age").write_bytes(bytes(data))
        (self.dir / "short.age").write_bytes(self.sealed.read_bytes()[:-10])
        for name in ("tampered.age", "short.age"):
            code, _ = self.decrypt(self.daily, source=self.dir / name)
            self.assertNotEqual(code, 0, name)

    def test_passphrase_protected_identity_file(self):
        protected = self.dir / "daily.key.age"
        env = dict(os.environ, PATH=f"{Path(AGE).parent}:{os.environ['PATH']}",
                   AGE_PASSPHRASE="synthetic test passphrase", AGE_PASSPHRASE_WORK_FACTOR="10")
        subprocess.run([AGE, "-e", "-j", "batchpass", "-o", str(protected), str(self.daily)],
                       check=True, env=env, capture_output=True)
        self.assertTrue(protected.read_bytes().startswith(b"age-encryption.org/v1\n"))
        self.assertNotIn(b"AGE-SECRET-KEY", protected.read_bytes())
        unlocked = subprocess.run([AGE, "-d", "-j", "batchpass", str(protected)], check=True, env=env,
                                  capture_output=True).stdout
        (self.dir / "unlocked.key").write_bytes(unlocked)
        self.assertEqual(self.decrypt(self.dir / "unlocked.key")[1], self.plain.read_bytes())


@needs_db
class FullChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import create_async_engine
        from api import db as database
        from scripts.pft_m5_backup_fixture import seed
        base = make_url(os.environ["DATABASE_URL"])
        self.assertIn(base.host, ("127.0.0.1", "localhost"))
        self.assertGreaterEqual(base.port, 55000)
        self.dir = Path(tempfile.mkdtemp(prefix="pft-age-chain-"))
        self.addCleanup(shutil.rmtree, self.dir)
        (self.dir / "store").mkdir()
        self.store = runner.LocalDirectoryStore(self.dir / "store")
        self.source = "pft_m5_backup_" + uuid.uuid4().hex[:12]
        self.target = "pft_restore_" + uuid.uuid4().hex[:16]
        self.pg_env = {"PATH": "/usr/bin:/bin", "PGHOST": base.host, "PGPORT": str(base.port),
                       "PGUSER": base.username, "PGDATABASE": self.source}
        subprocess.run([f"{PG_BIN}/createdb", self.source], env=self.pg_env, check=True)
        self.addCleanup(self.drop)
        engine = create_async_engine(base.set(database=self.source))
        try:
            with patch.object(database, "engine", engine):
                await database.init_db()
            await seed(engine, rows=400)
        finally:
            await engine.dispose()
        self.daily, daily_pub = keypair(self.dir, "daily")
        self.emergency, emergency_pub = keypair(self.dir, "emergency")
        self.recipients = self.dir / "recipients.txt"
        self.recipients.write_text(f"{daily_pub}\n{emergency_pub}\n")
        self.target_url = f"postgresql://{base.username}@{base.host}:{base.port}/{self.target}"

    def drop(self):
        for name in (self.target, self.source):
            subprocess.run([f"{PG_BIN}/dropdb", "--if-exists", name], env=self.pg_env, check=True,
                           capture_output=True)

    def psql(self, database, sql):
        subprocess.run([f"{PG_BIN}/psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", database, "-c", sql],
                       env=self.pg_env, check=True, capture_output=True)

    def backup(self, schemas=("public",)):
        return runner.create(store=self.store, tools=runner.Tools(pg_bin=PG_BIN, age=AGE, env=dict(self.pg_env)),
                             recipients_file=self.recipients, expected_database=self.source,
                             schemas=schemas, work_parent=self.dir, runner_commit="test")

    def download(self, point):
        folder = self.dir / ("download-" + uuid.uuid4().hex)
        folder.mkdir()
        self.store.get(point, folder)
        return folder

    def source_fingerprint(self):
        return restore_tool.fingerprint(dict(self.pg_env), ["public"], PG_BIN)

    async def test_age_chain_with_emergency_key_only_matches_snapshot(self):
        before = self.source_fingerprint()
        created = self.backup()
        self.assertEqual((created["tables"], created["recipients"]), (15, 2))
        stored = sorted((self.dir / "store" / created["point"]).iterdir())
        self.assertEqual([p.name for p in stored], ["backup.dump.age", "fingerprint.txt.age", "manifest.json.age"])
        for path in stored:
            self.assertTrue(path.read_bytes().startswith(b"age-encryption.org/v1\n"))
        self.psql(self.source, "DELETE FROM manual_category_overrides")  # after the snapshot
        result = restore_tool.restore(self.download(created["point"]), self.target_url,
                                      identities=[self.emergency], age=AGE, pg_bin=PG_BIN, work_parent=self.dir)
        self.assertTrue(result["equal"], result["mismatches"])
        self.assertEqual(result["restored_fingerprint"], before)
        self.psql(self.target, "UPDATE accounts SET name='changed' WHERE account_id='account-0-0'")
        self.psql(self.target, "DROP INDEX ix_raw_account_date")
        after = restore_tool.fingerprint(dict(self.pg_env, PGDATABASE=self.target), ["public"], PG_BIN)
        self.assertEqual(restore_tool.compare(before, after),
                         ["index|public.raw_transactions|ix_raw_account_date", "table|public.accounts"])

    async def test_write_committed_during_dump_is_in_neither_dump_nor_fingerprint(self):
        before = self.source_fingerprint()
        shim = self.dir / "pgbin"
        shim.mkdir()
        for tool in ("psql", "pg_restore", "createdb"):
            (shim / tool).symlink_to(Path(PG_BIN) / tool)
        # Runs after pg_export_snapshot() and before the real pg_dump starts.
        (shim / "pg_dump").write_text("#!/bin/sh\n"
                                      f'"{PG_BIN}/psql" -X -q -c "DELETE FROM manual_category_overrides"\n'
                                      f'exec "{PG_BIN}/pg_dump" "$@"\n')
        (shim / "pg_dump").chmod(0o700)
        created = runner.create(store=self.store, tools=runner.Tools(pg_bin=str(shim), age=AGE, env=dict(self.pg_env)),
                                recipients_file=self.recipients, expected_database=self.source,
                                work_parent=self.dir)
        self.assertNotEqual(self.source_fingerprint(), before)  # the write really committed
        result = restore_tool.restore(self.download(created["point"]), self.target_url,
                                      identities=[self.daily], age=AGE, pg_bin=PG_BIN, work_parent=self.dir)
        self.assertTrue(result["equal"], result["mismatches"])
        self.assertEqual(result["restored_fingerprint"], before)

    async def test_container_style_wrapper_mode(self):
        # The workflow runs psql through `docker run ... image`; `env` stands in
        # for that wrapper here, with the client on PATH instead of --pg-bin.
        env = dict(self.pg_env, PATH=f"{PG_BIN}:/usr/bin:/bin")
        created = runner.create(store=self.store, tools=runner.Tools(pg_wrapper="env", age=AGE, env=env),
                                recipients_file=self.recipients, expected_database=self.source,
                                work_parent=self.dir)
        result = restore_tool.restore(self.download(created["point"]), self.target_url,
                                      identities=[self.daily], age=AGE, pg_bin=PG_BIN, work_parent=self.dir)
        self.assertTrue(result["equal"], result["mismatches"])

    async def test_runbook_commands_without_pft_code(self):
        """docs/PFT_BACKUP_RESTORE_RUNBOOK.md steps, using only age, pg_restore, createdb and psql."""
        created = self.backup()
        folder = self.download(created["point"])
        work = self.dir / "runbook"
        work.mkdir()
        env = dict(self.pg_env, PATH=f"{PG_BIN}:/usr/bin:/bin")
        run = lambda *argv, **kw: subprocess.run(list(argv), env=env, check=True, capture_output=True, **kw)
        for asset in ("backup.dump", "manifest.json", "fingerprint.txt"):
            run(AGE, "-d", "-i", str(self.daily), "-o", str(work / asset), str(folder / (asset + ".age")))
        manifest = json.loads((work / "manifest.json").read_text())
        self.assertEqual(hashlib.sha256((work / "backup.dump").read_bytes()).hexdigest(), manifest["archive"]["sha256"])
        toc = run("pg_restore", "-l", str(work / "backup.dump")).stdout.decode()
        (work / "restore.list").write_text("".join(
            line + "\n" for line in toc.splitlines()
            if " SCHEMA - public " not in line and " COMMENT - SCHEMA public " not in line))
        run("createdb", self.target)
        run("pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-L", str(work / "restore.list"),
            "-d", self.target, str(work / "backup.dump"))
        restored = run("psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", "schemas={public}", "-d", self.target,
                       "-f", str(runner.HERE / "fingerprint.sql")).stdout.decode()
        self.assertEqual(restored, (work / "fingerprint.txt").read_text())

    async def test_wrong_database_unselected_schema_and_wrong_key_fail_closed(self):
        tools = runner.Tools(pg_bin=PG_BIN, age=AGE, env=dict(self.pg_env))
        with self.assertRaises(runner.RunnerError):
            runner.create(store=self.store, tools=tools, recipients_file=self.recipients,
                          expected_database="pft_production_backfill", work_parent=self.dir)
        self.psql(self.source, "CREATE SCHEMA pft_ops; CREATE TABLE pft_ops.trigger_nonces (nonce text primary key)")
        with self.assertRaisesRegex(runner.RunnerError, "unselected"):
            self.backup()
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.backup(schemas=("public", "pft_ops"))["tables"], 16)
        stranger, _ = keypair(self.dir, "stranger")
        with self.assertRaisesRegex(restore_tool.RestoreError, "age failed"):
            restore_tool.restore(self.download(self.store.list()[-1]), self.target_url, identities=[stranger],
                                 age=AGE, pg_bin=PG_BIN, work_parent=self.dir)
        subprocess.run([f"{PG_BIN}/createdb", self.target], env=self.pg_env, check=True)
        with self.assertRaisesRegex(restore_tool.RestoreError, "createdb failed"):
            restore_tool.restore(self.download(self.store.list()[-1]), self.target_url, identities=[self.daily],
                                 age=AGE, pg_bin=PG_BIN, work_parent=self.dir)

    async def test_windows_formats_local_dump_and_pftenc2(self):
        from api import backup, backup_crypto
        before = self.source_fingerprint()
        (self.dir / "expected.txt").write_text(before)
        backups = self.dir / "windows"
        backups.mkdir(mode=0o700)
        with patch.dict(os.environ, {"DATABASE_URL": f"postgresql://{self.pg_env['PGUSER']}:synthetic@"
                                                     f"{self.pg_env['PGHOST']}:{self.pg_env['PGPORT']}/{self.source}",
                                     "EXPECTED_DATABASE_NAME": self.source, "POSTGRES_DB": self.source,
                                     "PFT_BACKUP_TEST_MODE": "true", "PFT_BACKUP_DIR": str(backups),
                                     "PFT_APP_COMMIT": "test", "PLAID_ENV": "sandbox"}), \
             patch.object(backup, "connection", lambda: (self.source, ["-h", self.pg_env["PGHOST"], "-p",
                                                                       self.pg_env["PGPORT"], "-U", self.pg_env["PGUSER"]],
                                                         dict(os.environ))):
            # The local guard insists on pft_m3_tests_* names; only that check is bypassed here.
            backup.backup("daily")
        dump = next(backups.glob("pft-daily-*.dump"))
        local = restore_tool.restore(dump, self.target_url, pg_bin=PG_BIN,
                                     expected_fingerprint=self.dir / "expected.txt", work_parent=self.dir)
        self.assertEqual((local["format"], local["equal"]), ("local", True), local["mismatches"])
        encrypted = self.dir / "external.pftenc"
        with patch("getpass.getpass", return_value="synthetic external-copy password"):
            backup_crypto.encrypt(dump, encrypted)
            second = self.target + "_b"
            result = restore_tool.restore(encrypted, self.target_url.replace(self.target, second), pg_bin=PG_BIN,
                                          expected_fingerprint=self.dir / "expected.txt", work_parent=self.dir)
        subprocess.run([f"{PG_BIN}/dropdb", "--if-exists", second], env=self.pg_env, check=True)
        self.assertEqual((result["format"], result["equal"]), ("pftenc2", True), result["mismatches"])


if __name__ == "__main__":
    unittest.main()
