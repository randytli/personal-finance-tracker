"""Restore any PFT backup format into a new local database and verify it.

Supported formats, detected from the input:

- ``age``: a backup point directory (as downloaded from the GitHub release
  store) containing ``backup.dump.age``, ``manifest.json.age`` and
  ``fingerprint.txt.age``. These are cloud backups from
  ``deploy/backup_runner``. Needs ``--identity`` (daily or emergency key file,
  passphrase-protected or not; age prompts for the passphrase).
- ``pftenc2``: an external encrypted copy made by ``api/backup_crypto.py``
  (Windows runtime, password + scrypt). Prompts for the password.
- ``local``: a plain Windows runtime dump ``pft-*.dump`` with its ``.json``
  manifest (``api/backup.py``).

All three formats stay supported through the transition described in the
backup design (until Windows backups stop at M8c, plus the retention of any
copy made before then).

The restore goes into a **new** loopback database ``pft_restore_*``. Existing
databases are never overwritten. The restored database is then fingerprinted
with ``deploy/backup_runner/fingerprint.sql``:

- age points carry their own snapshot fingerprint, which is compared
  automatically;
- for the Windows formats, pass ``--expected-fingerprint`` (a fingerprint.sql
  output of the source), or the restored fingerprint is only written out.

The independent no-code procedure is in docs/PFT_BACKUP_RESTORE_RUNBOOK.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
FINGERPRINT_SQL = ROOT / "deploy" / "backup_runner" / "fingerprint.sql"
TARGET_NAME = re.compile(r"pft_restore_[a-z0-9_]{1,50}")
AGE_ASSETS = ("backup.dump.age", "manifest.json.age", "fingerprint.txt.age")


class RestoreError(RuntimeError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def detect(source):
    source = Path(source)
    if source.is_dir():
        if all((source / name).is_file() for name in AGE_ASSETS):
            return "age"
        raise RestoreError("directory is not an age backup point")
    with source.open("rb") as stream:
        head = stream.read(8)
    if head == b"PFTENC2\n":
        return "pftenc2"
    if head.startswith(b"PGDMP") and source.with_suffix(".json").is_file():
        return "local"
    raise RestoreError("unrecognised backup format")


def _run(argv, env=None, check=True):
    result = subprocess.run(argv, env=env, capture_output=True, timeout=1800)
    if check and result.returncode:
        first = result.stderr.decode(errors="replace").strip().splitlines()[:1]
        raise RestoreError(f"{Path(argv[0]).name} failed: {' '.join(first)}")
    return result


def target_profile(url):
    parts = urlsplit(url)
    database = parts.path.lstrip("/")
    if parts.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise RestoreError("restore drills target a local database only")
    if not TARGET_NAME.fullmatch(database):
        raise RestoreError("target database must be a new pft_restore_* database")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "PGHOST": parts.hostname, "PGPORT": str(parts.port or 5432),
           "PGUSER": parts.username or "postgres", "PGDATABASE": database}
    if parts.password:
        env["PGPASSWORD"] = parts.password
    return database, env


def decrypt(fmt, source, work, *, identities=(), age="age"):
    """Return (archive path, schemas, embedded fingerprint text or None, summary)."""
    archive = work / "backup.dump"
    if fmt == "age":
        if not identities:
            raise RestoreError("age backups need --identity")
        id_args = [arg for identity in identities for arg in ("-i", str(identity))]
        for asset in AGE_ASSETS:
            # age authenticates every chunk; a wrong key, truncation or tampering fails here.
            _run([age, "--decrypt", *id_args, "-o", str(work / asset[:-4]), str(Path(source) / asset)],
                 env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        manifest = json.loads((work / "manifest.json").read_text())
        if manifest.get("format") != "pft-backup-age-v1":
            raise RestoreError("unsupported age manifest format")
        if (manifest["archive"]["sha256"] != sha256_file(archive)
                or manifest["archive"]["size"] != archive.stat().st_size
                or manifest["fingerprint"]["sha256"] != sha256_file(work / "fingerprint.txt")):
            raise RestoreError("archive or fingerprint does not match manifest")
        return archive, manifest["schemas"], (work / "fingerprint.txt").read_text(), {
            "created_at": manifest["created_at"], "server_version": manifest["server_version"]}
    if fmt == "pftenc2":
        from api import backup_crypto  # prompts for the external-copy password
        backup_crypto.decrypt(source, archive)
        manifest = json.loads(archive.with_suffix(".json").read_text())
        return archive, ["public"], None, {"created_at": manifest.get("created_at")}
    if fmt == "local":
        manifest = json.loads(Path(source).with_suffix(".json").read_text())
        if manifest["sha256"] != sha256_file(source) or manifest["size"] != Path(source).stat().st_size:
            raise RestoreError("backup checksum or size mismatch")
        shutil.copyfile(source, archive)
        return archive, ["public"], None, {"created_at": manifest.get("created_at")}
    raise RestoreError("unknown format")


def fingerprint(env, schemas, pg_bin=""):
    psql = str(Path(pg_bin) / "psql") if pg_bin else "psql"
    array = "{" + ",".join(schemas) + "}"
    return _run([psql, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", f"schemas={array}",
                 "-f", str(FINGERPRINT_SQL)], env=env).stdout.decode()


def compare(expected, actual):
    """Names of objects whose fingerprint lines differ (no row data involved)."""
    def keyed(text):
        out = {}
        for line in text.splitlines():
            if line:
                fields = line.split("|")
                width = 2 if fields[0] in ("table", "sequence") else 3
                out["|".join(fields[:width])] = line
        return out
    left, right = keyed(expected), keyed(actual)
    return sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k))


def restore(source, target_url, *, identities=(), age="age", pg_bin="", expected_fingerprint=None,
            work_parent=None):
    fmt = detect(source)
    database, env = target_profile(target_url)
    tool = (lambda name: str(Path(pg_bin) / name)) if pg_bin else (lambda name: name)
    work = Path(tempfile.mkdtemp(prefix="pft-restore-", dir=work_parent))
    try:
        os.chmod(work, 0o700)
        archive, schemas, embedded, summary = decrypt(fmt, source, work, identities=identities, age=age)
        toc = _run([tool("pg_restore"), "-l", str(archive)], env=env).stdout.decode()
        # A new database already has schema public: skip only its CREATE/COMMENT
        # entries instead of ever dropping it.
        listing = work / "restore.list"
        listing.write_text("\n".join(line for line in toc.splitlines() if not re.search(
            r"^\d+; \d+ \d+ (SCHEMA - public |COMMENT - SCHEMA public )", line)) + "\n")
        _run([tool("createdb"), database], env=env)  # fails if the target exists
        _run([tool("pg_restore"), "--exit-on-error", "--no-owner", "--no-privileges",
              "-L", str(listing), "-d", database, str(archive)], env=env)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    restored = fingerprint(env, schemas, pg_bin)
    expected = embedded if embedded is not None else (
        Path(expected_fingerprint).read_text() if expected_fingerprint else None)
    mismatches = compare(expected, restored) if expected is not None else None
    return {"format": fmt, "target_database": database, **summary,
            "tables": sum(1 for line in restored.splitlines() if line.startswith("table|")),
            "compared": expected is not None, "equal": mismatches == [] if expected is not None else None,
            "mismatches": mismatches, "restored_fingerprint": restored}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--identity", type=Path, action="append", default=[])
    parser.add_argument("--age", default=os.environ.get("PFT_AGE_BIN", "age"))
    parser.add_argument("--pg-bin", default=os.environ.get("PFT_PG_BIN_DIR", ""))
    parser.add_argument("--expected-fingerprint", type=Path)
    parser.add_argument("--fingerprint-out", type=Path)
    args = parser.parse_args()
    result = restore(args.source, args.target_url, identities=args.identity, age=args.age,
                     pg_bin=args.pg_bin, expected_fingerprint=args.expected_fingerprint)
    text = result.pop("restored_fingerprint")
    if args.fingerprint_out:
        fd = os.open(args.fingerprint_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(text)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["equal"] is False:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
