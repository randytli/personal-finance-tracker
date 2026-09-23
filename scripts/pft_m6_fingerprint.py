"""Read-only, snapshot-consistent M6 preservation fingerprints.

The output contains counts and hashes, never stored tokens, cursors, or rows.
Pass a pre-migration output with --columns-from to compare legacy fields after
new columns and tables are added.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

import asyncpg
from sqlalchemy.engine import make_url


def fingerprint(rows):
    canonical = sorted(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows)
    return hashlib.sha256("\n".join(canonical).encode()).hexdigest()


async def snapshot(reference):
    url = make_url(os.environ["DATABASE_URL"])
    expected = os.environ["EXPECTED_DATABASE_NAME"]
    if not expected or url.database != expected:
        raise RuntimeError("Database URL and expected database name differ")
    db = await asyncpg.connect(host=url.host, port=url.port or 5432,
                               user=url.username, password=url.password,
                               database=url.database, server_settings={
                                   "application_name": "pft_m6_read_only_fingerprint"})
    try:
        # jsonb renders timestamptz in the session zone. Canonicalize live and
        # isolated restores before comparing their otherwise identical rows.
        await db.execute("SET TIME ZONE 'UTC'")
        async with db.transaction(isolation="repeatable_read", readonly=True):
            actual = await db.fetchval("SELECT current_database()")
            if actual != expected:
                raise RuntimeError("Connected database identity mismatch")
            tables = await db.fetch("SELECT tablename FROM pg_tables "
                                    "WHERE schemaname='public' ORDER BY tablename")
            result = {"database": actual, "tables": {}, "institutions": [],
                      "raw_by_institution_source": [], "integrity": {}}
            for table_row in tables:
                table = table_row["tablename"]
                columns = [row["column_name"] for row in await db.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=$1 "
                    "ORDER BY ordinal_position", table)]
                if reference is not None:
                    if table not in reference["tables"]:
                        continue
                    selected = reference["tables"][table]["columns"]
                    if not set(selected).issubset(columns):
                        raise RuntimeError(f"Legacy columns missing from {table}")
                else:
                    selected = columns
                # Table names come from the PostgreSQL catalog, then are quoted.
                quoted = '"' + table.replace('"', '""') + '"'
                values = [json.loads(row[0]) for row in await db.fetch(
                    f"SELECT to_jsonb(t)::text FROM {quoted} t")]
                projected = [{name: value[name] for name in selected} for value in values]
                result["tables"][table] = {"columns": selected, "count": len(values),
                                           "sha256": fingerprint(projected)}
            if "items" in result["tables"]:
                result["institutions"] = [dict(row) for row in await db.fetch("""
                    SELECT i.institution_name, i.status,
                      count(a.account_id)::int AS accounts,
                      count(a.account_id) FILTER
                        (WHERE a.consumer_transactions_enabled)::int AS enabled_accounts,
                      count(a.account_id) FILTER
                        (WHERE NOT a.consumer_transactions_enabled)::int AS disabled_accounts,
                      (i.transactions_cursor IS NOT NULL) AS cursor_present
                    FROM items i LEFT JOIN accounts a USING (item_id)
                    GROUP BY i.item_id, i.institution_name, i.status, i.transactions_cursor
                    ORDER BY i.institution_name, i.item_id
                """)]
                result["raw_by_institution_source"] = [dict(row) for row in await db.fetch("""
                    SELECT i.institution_name, r.source, r.is_removed,
                      count(*)::int AS rows, min(r.transaction_date)::text AS first_date,
                      max(r.transaction_date)::text AS last_date
                    FROM raw_transactions r JOIN items i USING (item_id)
                    GROUP BY i.item_id, i.institution_name, r.source, r.is_removed
                    ORDER BY i.institution_name, r.source, r.is_removed
                """)]
                result["integrity"] = dict(await db.fetchrow("""
                    SELECT
                      (SELECT count(*) FROM raw_transactions r JOIN accounts a
                       ON a.account_id=r.account_id WHERE r.item_id<>a.item_id)::int
                        AS raw_item_mismatches,
                      (SELECT count(*) FROM transactions t JOIN raw_transactions r
                       USING (transaction_id) WHERE t.account_id<>r.account_id)::int
                        AS normalized_account_mismatches,
                      (SELECT count(*) FROM statement_import_rows s LEFT JOIN
                       statement_import_batches b USING (batch_id)
                       WHERE b.batch_id IS NULL OR s.canonical IS NULL
                       OR s.source_evidence IS NULL)::int AS statement_evidence_errors,
                      (SELECT count(*) FROM raw_transactions WHERE source='plaid'
                       AND statement_row_id IS NOT NULL)::int AS plaid_statement_link_errors
                """))
            return result
    finally:
        await db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--columns-from", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.columns_from.read_text()) if args.columns_from else None
    result = asyncio.run(snapshot(reference))
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(f"Wrote read-only fingerprints for {len(result['tables'])} tables")


if __name__ == "__main__":
    main()
