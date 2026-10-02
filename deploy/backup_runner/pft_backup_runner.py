"""PFT independent backup runner (GitHub Actions or local drill). Stdlib only.

One run:
1. checks connection policy, schema coverage and recipients;
2. runs ``snapshot_dump.sql`` through psql: identity check, exported REPEATABLE
   READ snapshot, ``pg_dump --snapshot``, fingerprint of the same snapshot;
3. writes a manifest and encrypts dump, manifest and fingerprint with the age
   CLI to **every** recipient in the recipients file (at least two: daily and
   emergency keys);
4. uploads the point to the store, which reads every asset back before the
   point becomes visible;
5. prunes old points (7 daily / 4 weekly / 3 monthly) only after that.

The runner holds no decryption key, no Plaid secret and no Fernet key. It
never writes to financial tables. Plaintext exists only in a private
temporary directory that is removed on every exit path.
"""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_store import (GitHubReleaseStore, LocalDirectoryStore, POINT_NAME,  # noqa: E402
                           StoreError, sha256_file)

HERE = Path(__file__).resolve().parent
FORMAT = "pft-backup-age-v1"
ASSETS = ("backup.dump", "manifest.json", "fingerprint.txt")
X25519_RECIPIENT = re.compile(r"age1[02-9ac-hj-np-z]{58}")
SCHEMA = re.compile(r"[a-z_][a-z0-9_]{0,62}")
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
# Supabase-managed schemas: never dumped or restored over (plan §15.1). This list
# is NOT yet verified against a real project; unknown schemas fail closed.
PROVIDER_SCHEMAS = {"auth", "storage", "extensions", "graphql", "graphql_public", "realtime",
                    "_realtime", "supabase_functions", "supabase_migrations", "vault", "pgsodium",
                    "pgsodium_masks", "net", "cron", "pgbouncer", "_analytics"}


class RunnerError(RuntimeError):
    pass


def read_recipients(path, minimum=2):
    """age X25519 recipients, one per line, '#' comments allowed."""
    found = []
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not X25519_RECIPIENT.fullmatch(line):
            raise RunnerError("recipients file may contain only age X25519 public keys")
        if line in found:
            raise RunnerError("duplicate recipient")
        found.append(line)
    if len(found) < minimum:
        raise RunnerError(f"at least {minimum} recipients required (daily and emergency keys)")
    return found


def connection_policy(env):
    """Remote sources need verified TLS; plaintext is allowed only for loopback
    disposable test clusters on a non-default port."""
    host, port = env.get("PGHOST", ""), int(env.get("PGPORT") or 5432)
    try:
        loopback = host in ("localhost",) or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if loopback:
        if port < 55000:
            raise RunnerError("loopback sources must be disposable clusters (port >= 55000)")
        return "loopback-test"
    if env.get("PGSSLMODE") != "verify-full" or not env.get("PGSSLROOTCERT"):
        raise RunnerError("remote sources require PGSSLMODE=verify-full and PGSSLROOTCERT")
    if not Path(env["PGSSLROOTCERT"]).is_file():
        raise RunnerError("PGSSLROOTCERT file is missing")
    return "verify-full"


class Tools:
    """psql/pg_dump/pg_restore, optionally through a container wrapper, and age."""

    def __init__(self, *, pg_wrapper="", pg_bin="", age="age", env=None):
        self.wrapper = shlex.split(pg_wrapper)
        self.pg_bin = pg_bin
        self.age = age
        self.env = env if env is not None else os.environ.copy()

    def pg(self, name, *args, extra_env=None, check=True):
        program = name if self.wrapper or not self.pg_bin else str(Path(self.pg_bin) / name)
        env = dict(self.env, **(extra_env or {}))
        if self.pg_bin and not self.wrapper:
            # pg_dump started by psql's \! must be the same client version.
            env["PATH"] = f"{self.pg_bin}:{env.get('PATH', '/usr/bin:/bin')}"
        return _run([*self.wrapper, program, *args], env, check=check)

    def age_encrypt(self, recipients_file, source, destination):
        _run([self.age, "--encrypt", "-R", str(recipients_file), "-o", str(destination), str(source)],
             {"PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        with open(destination, "rb") as stream:
            if not stream.read(22).startswith(b"age-encryption.org/v1\n"):
                raise RunnerError("age output is not an age v1 file")


def _run(argv, env, check=True):
    result = subprocess.run(argv, env=env, capture_output=True, timeout=1200)
    if check and result.returncode:
        # Tool stderr can name hosts or roles but never row data or passwords;
        # keep only its first line.
        first = result.stderr.decode(errors="replace").strip().splitlines()[:1]
        raise RunnerError(f"{Path(argv[0]).name if argv else 'command'} failed: {' '.join(first)}")
    return result


def retention_keep(names, *, daily=7, weekly=4, monthly=3):
    """Grandfather-father-son over point timestamps. Covers at least the local
    runtime's 7 daily + 4 weekly + 3 monthly policy (api/backup.py)."""
    stamped = sorted(((datetime.strptime(POINT_NAME.fullmatch(n).group(1), "%Y%m%dT%H%M%SZ"), n)
                      for n in names if POINT_NAME.fullmatch(n)), reverse=True)
    keep, days, weeks, months = set(), [], [], []
    for stamp, name in stamped:
        for key, seen, limit in ((stamp.date(), days, daily), (stamp.isocalendar()[:2], weeks, weekly),
                                 ((stamp.year, stamp.month), months, monthly)):
            if key not in seen and len(seen) < limit:
                seen.append(key)
                keep.add(name)
    return keep


def prune(store, verified_newest):
    """Delete only after a newer point was uploaded and read back."""
    names = store.list()
    if verified_newest not in names:
        raise RunnerError("refusing to prune without a verified newest point")
    keep = retention_keep(names) | {verified_newest}
    removed = [name for name in names if name not in keep]
    for name in removed:
        store.delete(name)
    return removed


def point_name(now):
    # No database names, kinds or financial identifiers in object names.
    return f"pft-backup-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}"


def create(*, store, tools, recipients_file, expected_database, schemas=("public",), work_parent,
           runner_commit="unknown", now=None):
    now = now or datetime.now(timezone.utc)
    if not schemas or any(not SCHEMA.fullmatch(s) for s in schemas):
        raise RunnerError("invalid schema selection")
    if not SCHEMA.fullmatch(expected_database or ""):
        raise RunnerError("invalid expected database name")
    recipients = read_recipients(recipients_file)
    policy = connection_policy(tools.env)
    work = Path(tempfile.mkdtemp(prefix="pft-backup-", dir=work_parent))
    try:
        os.chmod(work, 0o700)
        for script in ("snapshot_dump.sql", "fingerprint.sql"):
            shutil.copy(HERE / script, work / script)
        present = set(tools.pg("psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c",
                               "SELECT nspname FROM pg_namespace").stdout.decode().split())
        present = {s for s in present - SYSTEM_SCHEMAS if not s.startswith(("pg_temp_", "pg_toast_temp_"))}
        unknown = present - set(schemas) - PROVIDER_SCHEMAS
        if unknown:
            raise RunnerError("unselected non-provider schema(s): " + ", ".join(sorted(unknown)))
        if set(schemas) - present:
            raise RunnerError("selected schema missing")
        server = tools.pg("psql", "-X", "-At", "-c", "SHOW server_version").stdout.decode().strip()
        array = "{" + ",".join(schemas) + "}"
        tools.pg("psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", f"expected_database={expected_database}",
                 "-v", f"schemas={array}", "-v", f"fingerprint_file={work / 'fingerprint.txt'}",
                 "-f", str(work / "snapshot_dump.sql"),
                 extra_env={"PFT_WORK": str(work),
                            "PFT_DUMP_SCHEMA_ARGS": " ".join(f"-n {s}" for s in schemas)})
        if not (work / "dump.ok").exists():
            raise RunnerError("pg_dump did not complete inside the snapshot")
        fingerprint = (work / "fingerprint.txt").read_text()
        tables = [line.split("|")[1] for line in fingerprint.splitlines() if line.startswith("table|")]
        toc = tools.pg("pg_restore", "-l", str(work / "backup.dump")).stdout.decode()
        covered = {f"{m.group(1)}.{m.group(2)}" for m in re.finditer(r"TABLE DATA (\S+) (\S+) ", toc)}
        if set(tables) - covered:
            raise RunnerError("archive is missing table data for: " + ", ".join(sorted(set(tables) - covered)))
        client = tools.pg("pg_dump", "--version").stdout.decode().strip()
        age_version = _run([tools.age, "--version"], {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
                           ).stdout.decode().strip()
        manifest = {"format": FORMAT, "created_at": now.isoformat(), "source_database": expected_database,
                    "schemas": list(schemas), "server_version": server, "client_version": client,
                    "age_version": age_version, "runner_commit": runner_commit, "connection": policy,
                    "recipients": recipients,
                    "archive": {"file": "backup.dump", "size": (work / "backup.dump").stat().st_size,
                                "sha256": sha256_file(work / "backup.dump")},
                    "fingerprint": {"file": "fingerprint.txt", "sha256": sha256_file(work / "fingerprint.txt"),
                                    "tables": len(tables)}}
        (work / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        sealed = {}
        for asset in ASSETS:
            tools.age_encrypt(recipients_file, work / asset, work / (asset + ".age"))
            (work / asset).unlink()  # plaintext is not kept once encrypted
            sealed[asset + ".age"] = work / (asset + ".age")
        name = point_name(now)
        stored = store.put(name, sealed)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    removed = prune(store, name)
    stale = store.remove_stale_drafts() if hasattr(store, "remove_stale_drafts") else []
    return {"point": name, "assets": stored, "pruned": removed, "stale_drafts_removed": stale,
            "tables": len(tables), "archive_size": manifest["archive"]["size"],
            "server_version": server, "recipients": len(recipients)}


def open_store(spec):
    kind, _, value = spec.partition(":")
    if kind == "local":
        return LocalDirectoryStore(value)
    if kind == "github":
        return GitHubReleaseStore(value, os.environ.get("GITHUB_TOKEN", ""),
                                  api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    raise RunnerError("store must be local:<dir> or github:<owner>/<repo>")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--store", required=True)
    parser.add_argument("--recipients", type=Path, required=True)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--schema", action="append", dest="schemas")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--pg-wrapper", default=os.environ.get("PFT_PG_WRAPPER", ""))
    parser.add_argument("--pg-bin", default=os.environ.get("PFT_PG_BIN_DIR", ""))
    parser.add_argument("--age", default=os.environ.get("PFT_AGE_BIN", "age"))
    args = parser.parse_args()
    try:
        result = create(store=open_store(args.store),
                        tools=Tools(pg_wrapper=args.pg_wrapper, pg_bin=args.pg_bin, age=args.age),
                        recipients_file=args.recipients, expected_database=args.expected_database,
                        schemas=tuple(args.schemas or ("public",)), work_parent=args.work_dir,
                        runner_commit=os.environ.get("GITHUB_SHA", "unknown"))
    except (RunnerError, StoreError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        raise SystemExit(1)
    print(json.dumps({"status": "success", **result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
