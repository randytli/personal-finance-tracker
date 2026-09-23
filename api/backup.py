"""Manual M3 backup and isolated restore commands. Scheduling belongs to M4."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
from datetime import datetime, timezone

from sqlalchemy.engine import make_url

BIN = Path(os.environ.get("PFT_PG_BIN_DIR", "/usr/lib/postgresql/16/bin"))
RETENTION = {"daily": 7, "weekly": 4, "monthly": 3, "extra": 1000000}


def connection():
    url = make_url(os.environ["DATABASE_URL"])
    expected = os.environ["EXPECTED_DATABASE_NAME"]
    if not expected or url.database != expected or os.environ.get("POSTGRES_DB") != expected:
        raise RuntimeError("database identity mismatch")
    isolated_test = (os.environ.get("PFT_BACKUP_TEST_MODE") == "true"
                     and os.environ.get("PLAID_ENV") != "production"
                     and expected.startswith("pft_m3_tests_"))
    if not isolated_test and (url.host != "db" or url.port not in (None, 5432)):
        raise RuntimeError("runtime backup must use the internal db service")
    if not url.username or not url.password:
        raise RuntimeError("database credentials are missing")
    env = os.environ.copy()
    env["PGPASSWORD"] = url.password
    args = ["-h", url.host, "-p", str(url.port or 5432), "-U", url.username]
    return url.database, args, env


def run(command, env, stdout=None):
    subprocess.run(command, env=env, stdout=stdout, check=True, timeout=1800,
                   stderr=subprocess.PIPE)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(kind):
    if kind not in RETENTION:
        raise ValueError("invalid backup kind")
    dbname, args, env = connection()
    directory = Path(os.environ["PFT_BACKUP_DIR"])
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError("backup directory must already exist and be a real directory")
    if directory.stat().st_mode & 0o077 and os.environ.get("PFT_BACKUP_HOST_ACL_VERIFIED") != "true":
        raise RuntimeError("backup directory must be private (mode 0700)")
    now = datetime.now(timezone.utc)
    stem = f"pft-{kind}-{now:%Y%m%dT%H%M%S%fZ}"
    final = directory / (stem + ".dump")
    manifest = directory / (stem + ".json")
    fd, temp_name = tempfile.mkstemp(prefix=".pft-incomplete-", dir=directory)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as output:
            run([str(BIN / "pg_dump"), *args, "-Fc", "-d", dbname], env, output)
            output.flush()
            os.fsync(output.fileno())
        run([str(BIN / "pg_restore"), "-l", str(temp)], env,
            subprocess.DEVNULL)
        with tempfile.TemporaryFile() as schema:
            run([str(BIN / "pg_restore"), "--schema-only", "-f", "-", str(temp)], env, schema)
            schema.seek(0)
            canonical_schema = b"".join(line for line in schema
                                        if not line.startswith((b"\\restrict ", b"\\unrestrict ")))
            schema_sha = hashlib.sha256(canonical_schema).hexdigest()
        metadata = {"format": "pg_dump-custom", "database": dbname,
                    "created_at": now.isoformat(), "kind": kind,
                    "size": temp.stat().st_size, "sha256": digest(temp),
                    "schema_sha256": schema_sha,
                    "application_commit": os.environ["PFT_APP_COMMIT"]}
        temp.replace(final)
        metadata_temp = directory / (stem + ".json.tmp")
        try:
            with metadata_temp.open("x") as output:
                os.chmod(metadata_temp, 0o600)
                output.write(json.dumps(metadata, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
            metadata_temp.replace(manifest)
            # A power loss must not remove old recovery points before the new
            # archive and manifest directory entries are durable.
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            metadata_temp.unlink(missing_ok=True)
        for group, keep in RETENTION.items():
            old = sorted(directory.glob(f"pft-{group}-*.json"), reverse=True)
            for entry in old[keep:]:
                dump = entry.with_suffix(".dump")
                if dump.exists():
                    dump.unlink()
                entry.unlink()
        return metadata
    finally:
        temp.unlink(missing_ok=True)


def restore(archive, target):
    source, args, env = connection()
    if target == source or not target.startswith("pft_restore_") or not target.replace("_", "").isalnum():
        raise RuntimeError("restore target must be a new pft_restore_* database")
    archive = Path(archive).resolve(strict=True)
    metadata = json.loads(archive.with_suffix(".json").read_text())
    if metadata["sha256"] != digest(archive) or metadata["size"] != archive.stat().st_size:
        raise RuntimeError("backup checksum or size mismatch")
    run([str(BIN / "pg_restore"), "-l", str(archive)], env, subprocess.DEVNULL)
    # createdb fails if the target already exists; no --clean or source mutation.
    run([str(BIN / "createdb"), *args, target], env)
    run([str(BIN / "pg_restore"), *args, "--exit-on-error", "--no-owner",
         "--no-privileges", "-d", target, str(archive)], env)
    return {"restored_database": target, "source_database": source,
            "sha256": metadata["sha256"]}


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--kind", choices=RETENTION, default="daily")
    recovery = sub.add_parser("restore")
    recovery.add_argument("archive")
    recovery.add_argument("target")
    sub.add_parser("worker")
    args = parser.parse_args()
    if args.command == "worker":
        # M3 container is ready for manual backup commands. No scheduler or sync.
        import asyncio
        from api.db import verify_runtime_schema
        async def check():
            connection()
            await verify_runtime_schema()
        asyncio.run(check())
        signal.pause()
    elif args.command == "create":
        print(json.dumps(backup(args.kind), sort_keys=True))
    else:
        print(json.dumps(restore(args.archive, args.target), sort_keys=True))


if __name__ == "__main__":
    main()
