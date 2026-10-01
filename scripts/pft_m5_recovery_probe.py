"""Local synthetic dump/encrypt/decrypt/restore measurement, no external upload.

Uses the unique schema retained by pft_m5_benchmark. Never calls the guarded
Production backup adapter or relaxes its checks. Keeps artifacts in private /tmp.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.pft_m5_benchmark import URL

BIN = Path("/usr/lib/postgresql/16/bin")
CONNECTION = ["-h", "127.0.0.1", "-p", "55439", "-U", "pft_m5"]


async def fingerprints(database, schema):
    engine = create_async_engine(URL.replace("pft_m5_synthetic", database))
    try:
        async with engine.connect() as connection:
            assert await connection.scalar(text("select current_database()")) == database
            tables = list((await connection.execute(text(
                "select tablename from pg_tables where schemaname=:s order by tablename"),
                {"s": schema})).scalars())
            result = {}
            for table in tables:
                # Catalog-owned identifiers escaped as SQL identifiers.
                ident = '"' + table.replace('"', '""') + '"'
                rows = list((await connection.execute(text(
                    f'SELECT to_jsonb(t)::text FROM "{schema}".{ident} t ORDER BY to_jsonb(t)::text'
                ))).scalars())
                result[table] = {"count": len(rows), "sha256": hashlib.sha256(
                    json.dumps(rows).encode()).hexdigest()}
            return result
    finally:
        await engine.dispose()


def run(args):
    if os.environ.get("PLAID_ENV", "").lower() == "production":
        raise RuntimeError("Refusing Production environment")
    if not re.fullmatch(r"m5_[a-f0-9]{32}", args.schema):
        raise RuntimeError("Requires a generated M5 synthetic schema")
    if not args.directory.resolve().is_relative_to(Path("/tmp")):
        raise RuntimeError("Probe artifacts must stay in /tmp")
    args.directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(args.directory, 0o700)
    timings = {}
    def command(stage, argv):
        start = time.perf_counter()
        subprocess.run([str(BIN / argv[0]), *argv[1:]], check=True, timeout=120,
                       env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, capture_output=True)
        timings[stage] = time.perf_counter() - start

    archive = args.directory / "source.dump"
    command("dump_s", ["pg_dump", *CONNECTION, "-d", "pft_m5_synthetic", "-n", args.schema,
                        "-Fc", "-f", str(archive)])
    from api import backup_crypto
    manifest = {"format": "pg_dump-custom", "database": "pft_m5_synthetic", "kind": "synthetic",
                "size": archive.stat().st_size, "sha256": backup_crypto.digest(archive)}
    archive.with_suffix(".json").write_text(json.dumps(manifest))
    encrypted = args.directory / "bundle.pftenc"
    recovered = args.directory / "recovered.dump"
    for name, action, source, target in (
        ("encrypt_s", backup_crypto.encrypt, archive, encrypted),
        ("decrypt_s", backup_crypto.decrypt, encrypted, recovered)):
        start = time.perf_counter()
        with patch("getpass.getpass", return_value="synthetic-only-disposable-password"):
            action(source, target)
        timings[name] = time.perf_counter() - start
    assert backup_crypto.digest(archive) == backup_crypto.digest(recovered)
    target = "pft_restore_m5_" + uuid.uuid4().hex
    command("create_restore_db_s", ["createdb", *CONNECTION, target])
    command("restore_s", ["pg_restore", *CONNECTION, "-d", target, "--exit-on-error", str(recovered)])
    source_rows = asyncio.run(fingerprints("pft_m5_synthetic", args.schema))
    restored_rows = asyncio.run(fingerprints(target, args.schema))
    assert source_rows == restored_rows
    # Verify schema/constraints/indexes/sequences/defaults as well as every table's rows.
    for name, database in (("source", "pft_m5_synthetic"), ("restored", target)):
        command(name + "_schema_s", ["pg_dump", *CONNECTION, "-d", database, "-n", args.schema,
            "--schema-only", "-f", str(args.directory / (name + ".sql"))])
    def canonical(name):
        value = "\n".join(line for line in (args.directory / (name + ".sql")).read_text().splitlines()
                          if not line.startswith(("\\restrict ", "\\unrestrict ")))
        # PostgreSQL rewrites literal varchar[] -> text[] casts during restore.
        # Normalize only this explicit equivalent representation; keep all other DDL.
        literal = r"'[^']*'::character varying"
        pattern = r"\(ARRAY\[(" + literal + r"(?:, " + literal + r")*)\]\)::text\[\]"
        return re.sub(pattern, lambda match: "ARRAY[" + ", ".join(
            "(" + item + ")::text" for item in match.group(1).split(", ")) + "]", value)
    assert canonical("source") == canonical("restored")
    result = {"kind": "local_synthetic_recovery_no_upload", "timings": timings,
              "archive_bytes": archive.stat().st_size, "encrypted_bytes": encrypted.stat().st_size,
              "artifact_bytes": sum(p.stat().st_size for p in args.directory.iterdir()),
              "tables": source_rows, "schema_equal_after_literal_cast_normalization": True, "rows_equal": True,
              "restore_database": target}
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "tables"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
