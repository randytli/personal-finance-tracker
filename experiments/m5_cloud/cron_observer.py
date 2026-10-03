"""M5 cron acceptance observer: connection, lock and delivery sampling (synthetic only).

Connects as the synthetic jobs role through the session pooler (password from a
private file, never printed) and samples every 0.5 s until enough deliveries
have finished or the time limit passes. Records peaks and a change-only series:
jobs-role backends (excluding this observer), active ones, all client backends,
the holders of the synthetic jobs/sync advisory locks, and delivery progress.

Usage: python -m experiments.m5_cloud.cron_observer --password-file F --out OUT.json
           [--wait-finished N] [--wait-started N] [--limit-seconds S] [--label L]
"""
import argparse
import asyncio
import json
import ssl
import time
from pathlib import Path

import asyncpg

PROJECT_REF = "acyghoemtdrilsdszolq"
HOST = "aws-0-us-east-1.pooler.supabase.com"
ROLE = "pft_m5_jobs"
USER = "synthetic-cron"
CA = Path(__file__).resolve().parents[2] / "deploy/backup_runner/supabase-ca.crt"
SAMPLE = f"""
select clock_timestamp() as at,
  (select count(*) from pg_stat_activity where usename = '{ROLE}' and pid <> pg_backend_pid()) as jobs_backends,
  (select count(*) from pg_stat_activity where usename = '{ROLE}' and pid <> pg_backend_pid()
     and state <> 'idle') as jobs_busy,
  (select count(*) from pg_stat_activity where backend_type = 'client backend') as client_backends,
  (select coalesce(array_agg(pid order by pid), '{{}}') from pg_locks where locktype = 'advisory' and granted
     and classid::bigint = ((hashtextextended('pft-jobs:{USER}', 0) >> 32) & 4294967295)
     and objid::bigint = (hashtextextended('pft-jobs:{USER}', 0) & 4294967295)) as jobs_lock,
  (select coalesce(array_agg(pid order by pid), '{{}}') from pg_locks where locktype = 'advisory' and granted
     and classid::bigint = ((hashtextextended('pft-sync:{USER}', 0) >> 32) & 4294967295)
     and objid::bigint = (hashtextextended('pft-sync:{USER}', 0) & 4294967295)) as sync_lock,
  (select count(*) from pft_m5_cron.deliveries where received_at >= $1) as started,
  (select count(*) from pft_m5_cron.deliveries where received_at >= $1 and finished_at is not null) as finished,
  (select count(*) from pft_m5_cron.sync_runs where status = 'running') as running_runs
"""


async def observe(args):
    context = ssl.create_default_context(cafile=str(CA))
    connection = await asyncpg.connect(
        host=HOST, port=5432, database="postgres", user=f"{ROLE}.{PROJECT_REF}",
        password=Path(args.password_file).read_text().strip(), ssl=context, timeout=15,
        command_timeout=15, statement_cache_size=0)
    try:
        if await connection.fetchval("select current_user") != ROLE:
            raise RuntimeError("observer identity rejected")
        since = await connection.fetchval("select clock_timestamp()")
        started = time.monotonic()
        series, peaks, last, reached = [], {}, None, None
        while time.monotonic() - started < args.limit_seconds:
            row = dict(await connection.fetchrow(SAMPLE, since))
            elapsed = round(time.monotonic() - started, 2)
            for key in ("jobs_backends", "jobs_busy", "client_backends", "running_runs"):
                peaks[key] = max(peaks.get(key, 0), row[key])
            state = {key: row[key] for key in row if key != "at"}
            if state != last:
                series.append({"t": elapsed, **state})
                last = state
            if ((args.wait_finished and row["finished"] >= args.wait_finished)
                    or (args.wait_started and row["started"] >= args.wait_started)):
                reached = elapsed
                break
            await asyncio.sleep(.5)
        return {"kind": "m5_cron_observation", "label": args.label, "since": since.isoformat(),
                "condition_reached_after_s": reached, "limit_s": args.limit_seconds,
                "peaks": peaks, "series": series, "observer_connections": 1}
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--wait-finished", type=int, default=0)
    parser.add_argument("--wait-started", type=int, default=0)
    parser.add_argument("--limit-seconds", type=int, default=420)
    result = asyncio.run(observe(parser.parse_args()))
    Path(result_path := parser.parse_args().out).write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({"label": result["label"], "reached_s": result["condition_reached_after_s"],
                      "peaks": result["peaks"], "samples_changed": len(result["series"])}))
