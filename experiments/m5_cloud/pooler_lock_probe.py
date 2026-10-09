"""M5: does a session advisory lock outlive a SIGKILLed/frozen client behind Supavisor?

Synthetic project only. A child process takes a dedicated probe lock through the
session pooler and is then killed (SIGKILL) or frozen (SIGSTOP). An independent
observer connection polls pg_locks / pg_stat_activity until the lock and the
backend disappear, and fresh connections check whether the old backend PID is
handed out again and whether they could re-enter the leaked lock.

The password is read from a private file and never printed. Output is JSON with
timings, PIDs and booleans only.

Usage:
  pooler_lock_probe.py run --password-file F [--kill-trials 3] [--freeze-seconds 90]
  pooler_lock_probe.py child <password file> <key> <marker>      (internal)
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import uuid

import asyncpg

PROJECT_REF = "acyghoemtdrilsdszolq"
HOST = "aws-0-us-east-1.pooler.supabase.com"
ROLE = "pft_m5_jobs"
CA = Path(__file__).resolve().parents[2] / "deploy/backup_runner/supabase-ca.crt"
LOCK_ROWS = """
select l.pid, l.granted from pg_locks l
where l.locktype = 'advisory' and l.database = (select oid from pg_database where datname = current_database())
  and l.classid::bigint = ((hashtextextended($1, 0) >> 32) & 4294967295)
  and l.objid::bigint = (hashtextextended($1, 0) & 4294967295)
"""


def tls():
    context = ssl.create_default_context(cafile=str(CA))
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    return context


async def connect(password_file):
    connection = await asyncpg.connect(
        host=HOST, port=5432, database="postgres", user=f"{ROLE}.{PROJECT_REF}",
        password=Path(password_file).read_text().strip(), ssl=tls(), timeout=15,
        command_timeout=15, statement_cache_size=0)
    row = await connection.fetchrow(
        "select current_user as role, (select ssl from pg_stat_ssl where pid = pg_backend_pid()) as ssl, "
        "(select project_ref from pft_m5_probe.identity where singleton) as ref")
    if (row["role"], row["ssl"], row["ref"]) != (ROLE, True, PROJECT_REF):
        await connection.close()
        raise RuntimeError("Synthetic identity/TLS gate rejected")
    return connection


async def child(password_file, key, marker, idle_timeout_s="0"):
    connection = await connect(password_file)
    if int(idle_timeout_s):
        # Session level only; Supavisor's reset on client disconnect discards it.
        await connection.execute(f"set idle_session_timeout = '{int(idle_timeout_s)}s'")
    pid = await connection.fetchval("select pg_backend_pid()")
    if not await connection.fetchval("select pg_try_advisory_lock(hashtextextended($1, 0))", key):
        raise RuntimeError("probe lock unexpectedly busy")
    Path(marker).write_text(json.dumps({"backend_pid": pid}))
    await asyncio.sleep(3600)  # Killed or frozen by the parent; no cleanup runs.


async def observe(observer, key, backend_pid, limit_s):
    started = time.monotonic()
    lock_gone = backend_gone = None
    samples = 0
    while time.monotonic() - started < limit_s:
        samples += 1
        rows = await observer.fetch(LOCK_ROWS, key)
        alive = await observer.fetchval("select count(*) from pg_stat_activity where pid = $1", backend_pid)
        elapsed = time.monotonic() - started
        if lock_gone is None and not rows:
            lock_gone = elapsed
        if backend_gone is None and not alive:
            backend_gone = elapsed
        if lock_gone is not None and backend_gone is not None:
            break
        await asyncio.sleep(.25)
    return {"lock_released_after_s": lock_gone, "backend_ended_after_s": backend_gone,
            "observer_samples": samples, "observation_limit_s": limit_s}


async def reuse_check(password_file, key, backend_pid, fresh=3):
    """Fresh clients: is the dead client's backend reused, and could they re-enter its lock?"""
    results = []
    for _ in range(fresh):
        connection = await connect(password_file)
        try:
            pid = await connection.fetchval("select pg_backend_pid()")
            held_here = any(row["pid"] == pid and row["granted"] for row in await connection.fetch(LOCK_ROWS, key))
            results.append({"backend_pid_reused": pid == backend_pid, "lock_already_held_by_this_backend": held_here})
        finally:
            await connection.close()
    return results


async def trial(password_file, mode, limit_s, freeze_s, idle_timeout_s=0):
    key = "pft-m5-pooler-leak-probe:" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory() as directory:
        marker = Path(directory) / "ready"
        process = subprocess.Popen([sys.executable, __file__, "child", password_file, key, str(marker),
                                    str(idle_timeout_s)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        observer = await connect(password_file)
        try:
            deadline = time.monotonic() + 30
            while not marker.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("child did not take the probe lock")
                await asyncio.sleep(.05)
            backend_pid = json.loads(marker.read_text())["backend_pid"]
            before = [dict(row) for row in await observer.fetch(LOCK_ROWS, key)]
            result = {"mode": mode, "child_idle_session_timeout_s": idle_timeout_s,
                      "lock_held_before":before == [{"pid": backend_pid, "granted": True}]}
            if mode == "sigkill":
                os.kill(process.pid, signal.SIGKILL)
                process.wait(10)
                result.update(await observe(observer, key, backend_pid, limit_s))
            else:
                os.kill(process.pid, signal.SIGSTOP)
                frozen = await observe(observer, key, backend_pid, freeze_s)
                result["while_frozen"] = frozen
                os.kill(process.pid, signal.SIGKILL)
                os.kill(process.pid, signal.SIGCONT)
                process.wait(10)
                result["after_kill"] = await observe(observer, key, backend_pid, limit_s)
            result["fresh_connections"] = await reuse_check(password_file, key, backend_pid)
            result["lock_rows_at_end"] = len(await observer.fetch(LOCK_ROWS, key))
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            await observer.close()


async def run(args):
    started = time.time()
    trials = [await trial(args.password_file, "sigkill", args.limit_seconds, 0) for _ in range(args.kill_trials)]
    if args.freeze_seconds:
        trials.append(await trial(args.password_file, "sigstop", args.limit_seconds, args.freeze_seconds,
                                  args.child_idle_timeout))
    return {"kind": "m5_pooler_advisory_lock_leak_probe", "project_ref": PROJECT_REF,
            "endpoint": f"{HOST}:5432 (session pooler)", "role": ROLE, "client": "local WSL2, asyncpg",
            "started_unix": int(started), "trials": trials}


if __name__ == "__main__":
    if sys.argv[1:2] == ["child"]:
        asyncio.run(child(*sys.argv[2:6]))
        sys.exit(0)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--kill-trials", type=int, default=3, choices=range(0, 4))
    parser.add_argument("--child-idle-timeout", type=int, default=0,
                        help="session idle_session_timeout in the frozen child, seconds (0 = unset)")
    parser.add_argument("--freeze-seconds", type=int, default=90)
    parser.add_argument("--limit-seconds", type=int, default=120)
    print(json.dumps(asyncio.run(run(parser.parse_args())), indent=2))
