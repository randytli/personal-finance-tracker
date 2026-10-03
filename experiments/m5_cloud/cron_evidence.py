"""Export M5 cron acceptance evidence (synthetic only, read-only, jobs role via the pooler).

Exports deliveries, sync runs, item runs, Item scheduling fields (no tokens, no
transaction content), row counts and the publication marker.

Usage: python -m experiments.m5_cloud.cron_evidence --password-file F --out OUT.json
"""
import argparse
import asyncio
import json
from pathlib import Path

from experiments.m5_cloud.cron_observer import CA, HOST, PROJECT_REF, ROLE

import asyncpg
import ssl

QUERIES = {
    "deliveries": "select * from pft_m5_cron.deliveries order by received_at",
    "sync_runs": "select run_id, trigger_source, request_sequence, started_at, finished_at, duration_ms, status, "
                 "classification_status, classified_count, classification_duration_ms, published_at, error_category "
                 "from pft_m5_cron.sync_runs order by started_at",
    "sync_item_runs": "select run_id, item_id, started_at, finished_at, status, phase, pages_fetched, received_added, "
                      "added_count, normalized_count, classified_count, retry_count, error_category "
                      "from pft_m5_cron.sync_item_runs order by started_at, item_id",
    "items": "select item_id, status, sync_paused, transactions_cursor, last_sync_attempt_at, last_sync_success_at, "
             "last_sync_change_at, next_sync_retry_at, sync_retry_count from pft_m5_cron.items order by item_id",
    "runtime_state": "select user_id, last_published_run_id, published_at, requested_sequence, handled_sequence, "
                     "running_sequence, jobs_heartbeat_at from pft_m5_cron.sync_runtime_state",
    "counts": "select (select count(*) from pft_m5_cron.raw_transactions) raw_rows, "
              "(select count(*) from pft_m5_cron.transactions) normalized_rows, "
              "(select count(*) from pft_m5_cron.trigger_nonces) live_nonces, "
              "pg_database_size(current_database()) database_bytes",
}


async def export(password_file):
    connection = await asyncpg.connect(
        host=HOST, port=5432, database="postgres", user=f"{ROLE}.{PROJECT_REF}",
        password=Path(password_file).read_text().strip(), ssl=ssl.create_default_context(cafile=str(CA)),
        timeout=15, command_timeout=30, statement_cache_size=0)
    try:
        return {name: [dict(row) for row in await connection.fetch(query)] for name, query in QUERIES.items()}
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    data = asyncio.run(export(args.password_file))
    Path(args.out).write_text(json.dumps(data, indent=2, default=str) + "\n")
    print(json.dumps({name: len(rows) for name, rows in data.items()}))
