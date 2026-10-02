"""M5 independent-backup drill prototype; local disposable clusters only.

Chain: snapshot-consistent fingerprint + pg_dump -> public-key envelope ->
store upload with readback -> retention -> download -> decrypt -> restore to a
new database -> fingerprint comparison against the manifest.

This is not a Production adapter. ``api/backup.py`` and its guards are
unchanged and this module never calls them. Source and target connections are
restricted to loopback disposable clusters. The unattended side needs only the
recipient's *public* key; decryption needs the separately held private key.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import tempfile

import asyncpg
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.engine import make_url

from scripts.pft_m6_fingerprint import fingerprint

BIN = Path(os.environ.get("PFT_PG_BIN_DIR", "/usr/lib/postgresql/16/bin"))
MAGIC = b"PFTENC3\n"
HEADER = len(MAGIC) + 32 + 32 + 12 + 8
CHUNK = 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
INFO = b"pft-backup-envelope-v3"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SOURCE_NAME = re.compile(r"pft_m5_[a-z0-9_]{1,50}")
TARGET_NAME = re.compile(r"pft_restore_m5_[a-f0-9]{32}")
OBJECT_NAME = re.compile(r"pft-backup-(\d{8}T\d{6}Z)-([a-f0-9]{16})\.pftenc3")
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
# Supabase-managed schemas that an application dump must not include or restore
# over (plan §15.1). This list is NOT verified against a real project; the drill
# fails closed on any schema that is neither selected nor listed here.
PROVIDER_SCHEMAS = {"auth", "storage", "extensions", "graphql", "graphql_public", "realtime",
                    "_realtime", "supabase_functions", "supabase_migrations", "vault", "pgsodium",
                    "pgsodium_masks", "net", "cron", "pgbouncer", "_analytics"}


class DrillError(RuntimeError):
    pass


# ---------------------------------------------------------------- connections

def _profile(url, *, role):
    """Loopback-only disposable profile. role is 'source' or 'target'."""
    parsed = make_url(url)
    if os.environ.get("PLAID_ENV", "").lower() == "production":
        raise DrillError("refusing Production environment")
    if parsed.host not in LOOPBACK or not parsed.port or parsed.port < 55000:
        raise DrillError("drill connections must be loopback disposable clusters (port >= 55000)")
    pattern = SOURCE_NAME if role == "source" else TARGET_NAME
    if not parsed.database or not pattern.fullmatch(parsed.database):
        raise DrillError(f"{role} database name is not a drill database")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "PGPASSWORD": parsed.password or "",
           "PGCONNECT_TIMEOUT": "10"}
    args = ["-h", parsed.host, "-p", str(parsed.port), "-U", parsed.username or "postgres"]
    return parsed, args, env


async def _connect(parsed):
    connection = await asyncpg.connect(host=parsed.host, port=parsed.port, user=parsed.username,
                                       password=parsed.password, database=parsed.database,
                                       server_settings={"application_name": "pft_m5_backup_drill"})
    # jsonb renders timestamptz in the session zone; canonicalize source and restore.
    await connection.execute("SET TIME ZONE 'UTC'")
    return connection


def _run(argv, env, **kwargs):
    try:
        return subprocess.run(argv, env=env, check=True, timeout=600, capture_output=True, **kwargs)
    except subprocess.CalledProcessError as exc:
        # stderr of pg tools carries no row data; keep only the first line.
        first = (exc.stderr or b"").decode(errors="replace").strip().splitlines()[:1]
        raise DrillError(f"{Path(argv[0]).name} failed: {' '.join(first)}") from None


# ---------------------------------------------------------------- fingerprints

async def database_fingerprint(connection, schemas):
    """Counts and hashes only: rows per table, sequences, constraint/index DDL."""
    result = {"tables": {}, "sequences": {}, "catalog_sha256": None}
    tables = await connection.fetch(
        "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY($1::text[]) "
        "ORDER BY schemaname, tablename", sorted(schemas))
    for row in tables:
        name = f"{row['schemaname']}.{row['tablename']}"
        quoted = ".".join('"' + part.replace('"', '""') + '"'
                          for part in (row["schemaname"], row["tablename"]))
        # Names come from the catalog, then are quoted.
        values = [json.loads(value[0]) for value in await connection.fetch(
            f"SELECT to_jsonb(t)::text FROM {quoted} t")]
        result["tables"][name] = {"count": len(values), "sha256": fingerprint(values)}
    for row in await connection.fetch(
            "SELECT schemaname, sequencename FROM pg_sequences WHERE schemaname = ANY($1::text[]) "
            "ORDER BY 1, 2", sorted(schemas)):
        quoted = ".".join('"' + part.replace('"', '""') + '"'
                          for part in (row["schemaname"], row["sequencename"]))
        state = await connection.fetchrow(f"SELECT last_value, is_called FROM {quoted}")
        result["sequences"][f"{row['schemaname']}.{row['sequencename']}"] = [
            int(state["last_value"]), bool(state["is_called"])]
    catalog = await connection.fetch("""
        SELECT n.nspname || '.' || c.relname || ' ' || x.conname || ' ' || pg_get_constraintdef(x.oid)
        FROM pg_constraint x JOIN pg_class c ON c.oid = x.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = ANY($1::text[])
        UNION ALL
        SELECT schemaname || '.' || tablename || ' ' || indexdef FROM pg_indexes
        WHERE schemaname = ANY($1::text[])
        UNION ALL
        SELECT table_schema || '.' || table_name || '.' || column_name || ' ' || data_type || ' '
               || is_nullable || ' ' || coalesce(column_default, '')
        FROM information_schema.columns WHERE table_schema = ANY($1::text[])
    """, sorted(schemas))
    result["catalog_sha256"] = hashlib.sha256(
        "\n".join(sorted(canonical_ddl(row[0]) for row in catalog)).encode()).hexdigest()
    return result


_LITERAL = r"'[^']*'::character varying"
_VARCHAR_ARRAY = re.compile(r"\(ARRAY\[(" + _LITERAL + r"(?:, " + _LITERAL + r")*)\]\)::text\[\]")


def canonical_ddl(line):
    """PostgreSQL rewrites ``(ARRAY['a'::varchar, ...])::text[]`` in CHECK
    constraints to ``ARRAY[('a'::varchar)::text, ...]`` on restore. Normalize
    only that equivalent form (as scripts/pft_m5_recovery_probe.py does)."""
    return _VARCHAR_ARRAY.sub(lambda match: "ARRAY[" + ", ".join(
        "(" + item + ")::text" for item in match.group(1).split(", ")) + "]", line)


def compare_fingerprints(expected, actual):
    """Return a sorted list of mismatch descriptions; empty means equal."""
    problems = []
    for section in ("tables", "sequences"):
        for name in sorted(set(expected[section]) | set(actual[section])):
            if expected[section].get(name) != actual[section].get(name):
                problems.append(f"{section}:{name}")
    if expected["catalog_sha256"] != actual["catalog_sha256"]:
        problems.append("catalog")
    return problems


async def _schema_selection(connection, schemas):
    present = {row[0] for row in await connection.fetch("SELECT nspname FROM pg_namespace")}
    present = {name for name in present - SYSTEM_SCHEMAS
               if not name.startswith(("pg_temp_", "pg_toast_temp_"))}
    unknown = present - set(schemas) - PROVIDER_SCHEMAS
    if unknown:
        # Coverage must never silently shrink when a new application schema appears.
        raise DrillError("unselected non-provider schema(s): " + ", ".join(sorted(unknown)))
    missing = set(schemas) - present
    if missing:
        raise DrillError("selected schema(s) missing: " + ", ".join(sorted(missing)))


# ---------------------------------------------------------------- envelope

def key_id(public_key):
    raw = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).digest()


def _derive(shared, ephemeral_raw, recipient_raw):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=ephemeral_raw + recipient_raw,
                info=INFO).derive(shared)


def seal(plaintext_path, manifest_bytes, recipient, destination):
    """Encrypt manifest + archive to an X25519 recipient (ephemeral-static ECDH,
    HKDF-SHA256, AES-256-GCM, header authenticated as AAD)."""
    destination = Path(destination)
    if destination.exists():
        raise DrillError("encrypted destination already exists")
    if len(manifest_bytes) > MAX_MANIFEST:
        raise DrillError("manifest too large")
    ephemeral = X25519PrivateKey.generate()
    ephemeral_raw = ephemeral.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw)
    recipient_raw = recipient.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    nonce = os.urandom(12)
    size = 4 + len(manifest_bytes) + Path(plaintext_path).stat().st_size
    header = MAGIC + key_id(recipient) + ephemeral_raw + nonce + struct.pack(">Q", size)
    encoder = Cipher(algorithms.AES(_derive(ephemeral.exchange(recipient), ephemeral_raw,
                                            recipient_raw)), modes.GCM(nonce)).encryptor()
    encoder.authenticate_additional_data(header)
    with tempfile.TemporaryDirectory(prefix=".pft-seal-", dir=destination.parent) as staging:
        temporary = Path(staging) / "bundle"
        with open(plaintext_path, "rb") as data, temporary.open("xb") as output:
            os.chmod(temporary, 0o600)
            output.write(header)
            output.write(encoder.update(struct.pack(">I", len(manifest_bytes)) + manifest_bytes))
            for block in iter(lambda: data.read(CHUNK), b""):
                output.write(encoder.update(block))
            output.write(encoder.finalize() + encoder.tag)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
    return sha256_file(destination)


def open_sealed(source, private_key, destination):
    """Authenticate and decrypt; returns the parsed manifest. Plaintext is only
    published after the GCM tag and the manifest's archive hash both verify."""
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise DrillError("decrypt destination already exists")
    with source.open("rb") as data:
        header = data.read(HEADER)
        if len(header) != HEADER or not header.startswith(MAGIC):
            raise DrillError("not a PFTENC3 bundle")
        offset = len(MAGIC)
        wanted, ephemeral_raw = header[offset:offset + 32], header[offset + 32:offset + 64]
        nonce, size = header[offset + 64:offset + 76], struct.unpack(">Q", header[-8:])[0]
        public = private_key.public_key()
        if wanted != key_id(public):
            raise DrillError("bundle was sealed to a different recipient key")
        if size < 4 or source.stat().st_size != HEADER + size + 16:
            raise DrillError("invalid encrypted bundle size")
        data.seek(-16, 2)
        tag = data.read(16)
        data.seek(HEADER)
        recipient_raw = public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        shared = private_key.exchange(X25519PublicKey.from_public_bytes(ephemeral_raw))
        decoder = Cipher(algorithms.AES(_derive(shared, ephemeral_raw, recipient_raw)),
                         modes.GCM(nonce, tag)).decryptor()
        decoder.authenticate_additional_data(header)
        manifest_size = struct.unpack(">I", decoder.update(data.read(4)))[0]
        if manifest_size > MAX_MANIFEST or manifest_size > size - 4:
            # Only reachable with a modified header or ciphertext.
            raise DrillError("bundle authentication failed")
        manifest_bytes = decoder.update(data.read(manifest_size))
        with tempfile.TemporaryDirectory(prefix=".pft-open-", dir=destination.parent) as staging:
            temporary = Path(staging) / "archive"
            digest = hashlib.sha256()
            with temporary.open("xb") as output:
                os.chmod(temporary, 0o600)
                remaining = size - 4 - manifest_size
                while remaining:
                    block = data.read(min(CHUNK, remaining))
                    if not block:
                        raise DrillError("truncated encrypted bundle")
                    plain = decoder.update(block)
                    digest.update(plain)
                    output.write(plain)
                    remaining -= len(block)
                try:
                    tail = decoder.finalize()
                except Exception:
                    raise DrillError("bundle authentication failed") from None
                digest.update(tail)
                output.write(tail)
                output.flush()
                os.fsync(output.fileno())
            manifest = json.loads(manifest_bytes)
            if (manifest["archive_sha256"] != digest.hexdigest()
                    or manifest["archive_size"] != temporary.stat().st_size):
                raise DrillError("archive hash or size does not match manifest")
            os.link(temporary, destination)
    return manifest


def load_private_key(path, passphrase=None):
    data = Path(path).read_bytes()
    try:
        key = serialization.load_pem_private_key(data, password=passphrase)
    except TypeError:
        key = serialization.load_pem_private_key(
            data, password=getpass.getpass("Backup private-key passphrase: ").encode())
    if not isinstance(key, X25519PrivateKey):
        raise DrillError("backup private key must be X25519")
    return key


def load_public_key(path):
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, X25519PublicKey):
        raise DrillError("backup recipient key must be X25519")
    return key


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------- store

class LocalDirectoryStore:
    """Stand-in for the independent object store: put with readback, list,
    get and delete. A real provider adapter must keep these semantics: success
    is recorded only after the stored bytes are read back and hash-verified."""

    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir() or self.root.is_symlink():
            raise DrillError("store root must be an existing real directory")

    def put(self, name, path, expected_sha256):
        if not OBJECT_NAME.fullmatch(name):
            raise DrillError("invalid object name")
        final = self.root / name
        if final.exists():
            raise DrillError("object already exists")
        fd, temp = tempfile.mkstemp(prefix=".upload-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as output, open(path, "rb") as data:
                for block in iter(lambda: data.read(CHUNK), b""):
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())
            os.link(temp, final)
        finally:
            os.unlink(temp)
        if sha256_file(final) != expected_sha256:
            final.unlink()
            raise DrillError("readback hash mismatch")
        return {"name": name, "sha256": expected_sha256, "size": final.stat().st_size}

    def list(self):
        return sorted(p.name for p in self.root.iterdir() if OBJECT_NAME.fullmatch(p.name))

    def get(self, name, destination):
        if not OBJECT_NAME.fullmatch(name):
            raise DrillError("invalid object name")
        destination = Path(destination)
        with open(self.root / name, "rb") as data, destination.open("xb") as output:
            for block in iter(lambda: data.read(CHUNK), b""):
                output.write(block)
        return destination

    def delete(self, name):
        if not OBJECT_NAME.fullmatch(name):
            raise DrillError("invalid object name")
        (self.root / name).unlink()


def object_name(now):
    # No financial identifiers, database names or kinds in object names.
    return f"pft-backup-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}.pftenc3"


def retention_keep(names, *, daily=7, weekly=4, monthly=3):
    """Grandfather-father-son over object timestamps; never fewer points than the
    local runtime's 7 daily + 4 weekly + 3 monthly policy. Returns names to keep."""
    stamped = sorted(((datetime.strptime(OBJECT_NAME.fullmatch(n).group(1), "%Y%m%dT%H%M%SZ"), n)
                      for n in names if OBJECT_NAME.fullmatch(n)), reverse=True)
    keep, days, weeks, months = set(), [], [], []
    for stamp, name in stamped:
        day, week, month = stamp.date(), stamp.isocalendar()[:2], (stamp.year, stamp.month)
        if day not in days and len(days) < daily:
            days.append(day)
            keep.add(name)
        if week not in weeks and len(weeks) < weekly:
            weeks.append(week)
            keep.add(name)
        if month not in months and len(months) < monthly:
            months.append(month)
            keep.add(name)
    return keep


def prune(store, verified_newest):
    """Delete only after a newer point was uploaded and read back."""
    names = store.list()
    if verified_newest not in names:
        raise DrillError("refusing to prune without a verified newest point")
    keep = retention_keep(names) | {verified_newest}
    removed = [name for name in names if name not in keep]
    for name in removed:
        store.delete(name)
    return removed


# ---------------------------------------------------------------- create / restore

async def create_backup(source_url, recipient, store, *, schemas=("public",), work_dir,
                        app_commit="unknown", now=None):
    parsed, args, env = _profile(source_url, role="source")
    now = now or datetime.now(timezone.utc)
    work_dir = Path(work_dir)
    connection = await _connect(parsed)
    try:
        await _schema_selection(connection, schemas)
        transaction = connection.transaction(isolation="repeatable_read", readonly=True)
        await transaction.start()
        try:
            snapshot = await connection.fetchval("SELECT pg_export_snapshot()")
            server = await connection.fetchval("SHOW server_version")
            source_fp = await database_fingerprint(connection, schemas)
            with tempfile.TemporaryDirectory(prefix=".pft-dump-", dir=work_dir) as staging:
                os.chmod(staging, 0o700)
                archive = Path(staging) / "archive.dump"
                schema_args = [arg for name in schemas for arg in ("-n", name)]
                # pg_dump imports the exported snapshot, so the archive and the
                # fingerprint describe exactly the same committed state.
                _run([str(BIN / "pg_dump"), *args, "-d", parsed.database, "-Fc",
                      f"--snapshot={snapshot}", *schema_args, "-f", str(archive)], env)
                toc = _run([str(BIN / "pg_restore"), "-l", str(archive)], env).stdout.decode()
                covered = {f"{m.group(1)}.{m.group(2)}" for m in re.finditer(
                    r"TABLE DATA (\S+) (\S+) ", toc)}
                if set(source_fp["tables"]) - covered:
                    raise DrillError("archive is missing table data for: "
                                     + ", ".join(sorted(set(source_fp["tables"]) - covered)))
                client = _run([str(BIN / "pg_dump"), "--version"], env).stdout.decode().strip()
                manifest = {"format": "pft-backup-v3", "pg_format": "pg_dump-custom",
                            "created_at": now.isoformat(), "source_database": parsed.database,
                            "schemas": list(schemas), "server_version": server,
                            "client_version": client, "application_commit": app_commit,
                            "archive_size": archive.stat().st_size,
                            "archive_sha256": sha256_file(archive), "fingerprint": source_fp}
                sealed = Path(staging) / "bundle.pftenc3"
                sealed_sha = seal(archive, json.dumps(manifest, sort_keys=True).encode(),
                                  recipient, sealed)
                name = object_name(now)
                stored = store.put(name, sealed, sealed_sha)
        finally:
            await transaction.rollback()
    finally:
        await connection.close()
    removed = prune(store, name)
    return {"object": stored, "pruned": removed, "archive_size": manifest["archive_size"],
            "tables": len(source_fp["tables"]),
            "empty_tables": sorted(n for n, t in source_fp["tables"].items() if not t["count"]),
            "rows": sum(t["count"] for t in source_fp["tables"].values())}


async def restore_backup(store, name, private_key, target_url, *, work_dir):
    parsed, args, env = _profile(target_url, role="target")
    work_dir = Path(work_dir)
    with tempfile.TemporaryDirectory(prefix=".pft-restore-", dir=work_dir) as staging:
        os.chmod(staging, 0o700)
        downloaded = store.get(name, Path(staging) / "bundle.pftenc3")
        archive = Path(staging) / "archive.dump"
        manifest = open_sealed(downloaded, private_key, archive)
        if manifest["source_database"] == parsed.database:
            raise DrillError("restore target equals the backup's source database")
        toc = _run([str(BIN / "pg_restore"), "-l", str(archive)], env).stdout.decode()
        # A new database (and a new managed project) already has schema public.
        # Skip only its CREATE/COMMENT entries; never DROP SCHEMA public.
        listing = Path(staging) / "restore.list"
        listing.write_text("\n".join(line for line in toc.splitlines() if not re.search(
            r"^\d+; \d+ \d+ (SCHEMA - public |COMMENT - SCHEMA public )", line)) + "\n")
        # createdb fails when the target exists: never restore over a database.
        _run([str(BIN / "createdb"), *args, parsed.database], env)
        _run([str(BIN / "pg_restore"), *args, "--exit-on-error", "--no-owner", "--no-privileges",
              "-L", str(listing), "-d", parsed.database, str(archive)], env)
    connection = await _connect(parsed)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            restored_fp = await database_fingerprint(connection, manifest["schemas"])
    finally:
        await connection.close()
    problems = compare_fingerprints(manifest["fingerprint"], restored_fp)
    return {"object": name, "target_database": parsed.database, "equal": not problems,
            "mismatches": problems, "manifest_created_at": manifest["created_at"],
            "tables": len(restored_fp["tables"]),
            "rows": sum(t["count"] for t in restored_fp["tables"].values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--source-url", required=True)
    create.add_argument("--recipient", type=Path, required=True, help="X25519 public key PEM")
    create.add_argument("--store", type=Path, required=True)
    create.add_argument("--work-dir", type=Path, required=True)
    create.add_argument("--schema", action="append", dest="schemas")
    restore = sub.add_parser("restore")
    restore.add_argument("--store", type=Path, required=True)
    restore.add_argument("--object", required=True)
    restore.add_argument("--private-key", type=Path, required=True)
    restore.add_argument("--target-url", required=True)
    restore.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    store = LocalDirectoryStore(args.store)
    if args.command == "create":
        result = asyncio.run(create_backup(args.source_url, load_public_key(args.recipient), store,
                                           schemas=tuple(args.schemas or ("public",)),
                                           work_dir=args.work_dir,
                                           app_commit=os.environ.get("PFT_APP_COMMIT", "unknown")))
    else:
        result = asyncio.run(restore_backup(store, args.object, load_private_key(args.private_key),
                                            args.target_url, work_dir=args.work_dir))
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "restore" and not result["equal"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
