"""Migration SQL for the M5 cron acceptance fixture (synthetic project only).

Creates a private schema with the unchanged application tables (compiled from
api.models), copies the existing synthetic 2,610-row fixture into it under a
new synthetic user, and adds the fixture-control, delivery-log and nonce
tables. Only the synthetic jobs role gets access; PUBLIC gets nothing.

Usage: cron_fixture.py --dataset-id m5-<32 hex>   (prints SQL; no I/O)
"""
import argparse
import re

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

SCHEMA = "pft_m5_cron"
SOURCE = "pft_m5_bench_2610"
USER_ID = "synthetic-cron"
JOBS_ROLE = "pft_m5_jobs"
COPIED = ("items", "accounts", "raw_transactions", "transactions")
_NAME = re.compile(r"[a-z_][a-z0-9_]*")


def _tables(schema):
    from api.models import Base
    metadata = MetaData()
    return [table.to_metadata(metadata, schema=schema) for table in Base.metadata.sorted_tables]


def migration_sql(dataset_id, *, schema=SCHEMA, source=SOURCE, jobs_role=JOBS_ROLE, project_ref="acyghoemtdrilsdszolq"):
    if not re.fullmatch(r"m5-[0-9a-f]{32}", dataset_id) or not re.fullmatch(r"[a-z]{20}", project_ref):
        raise ValueError("synthetic identifiers required")
    if not all(_NAME.fullmatch(name) for name in (schema, source, jobs_role)):
        raise ValueError("invalid identifier")
    dialect = postgresql.dialect()
    tables = _tables(schema)
    statements = [f"CREATE SCHEMA {schema}", f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC"]
    for table in tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip())
        statements.extend(str(CreateIndex(index).compile(dialect=dialect)).strip()
                          for index in sorted(table.indexes, key=lambda index: index.name))
    by_name = {table.name: table for table in tables}
    for name in COPIED:
        columns = ", ".join(f'"{column.name}"' for column in by_name[name].columns)
        statements.append(f"INSERT INTO {schema}.{name} ({columns}) SELECT {columns} FROM {source}.{name}")
    # A fresh synthetic owner: nothing is due until a scenario makes it due.
    statements.append(f"UPDATE {schema}.items SET user_id = '{USER_ID}', last_sync_success_at = now(), "
                      "last_sync_attempt_at = NULL, next_sync_retry_at = NULL, sync_retry_count = 0, "
                      "sync_paused = false")
    # CreateTable/CreateIndex do not run metadata.after_create. Install the same
    # seeds and ownership guards explicitly in the private fixture schema.
    from api.label_schema import LABEL_SCHEMA_SQL
    statements.append(f"SET search_path TO {schema}, pg_catalog")
    statements.extend(LABEL_SCHEMA_SQL)
    statements.append(f"REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {schema} FROM PUBLIC")
    statements.append(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {schema} TO {jobs_role}")
    statements.append("RESET search_path")
    statements += [
        f"""CREATE TABLE {schema}.fixture_manifest (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    dataset_id text NOT NULL,
    project_ref text NOT NULL,
    hang_publication_s integer NOT NULL DEFAULT 0 CHECK (hang_publication_s BETWEEN 0 AND 600),
    created_at timestamptz NOT NULL DEFAULT now())""",
        f"INSERT INTO {schema}.fixture_manifest (dataset_id, project_ref) VALUES ('{dataset_id}', '{project_ref}')",
        f"""CREATE TABLE {schema}.fixture_plan (
    item_id text PRIMARY KEY REFERENCES {schema}.items (item_id),
    mode text NOT NULL DEFAULT 'noop' CHECK (mode IN ('noop', 'pages', 'mutation', 'plaid_error', 'slow')),
    account_id text NOT NULL REFERENCES {schema}.accounts (account_id),
    pages integer NOT NULL DEFAULT 1 CHECK (pages BETWEEN 0 AND 100),
    rows_per_page integer NOT NULL DEFAULT 0 CHECK (rows_per_page BETWEEN 0 AND 500),
    generation integer NOT NULL DEFAULT 0,
    failures integer NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 5),
    delay_s numeric NOT NULL DEFAULT 0 CHECK (delay_s BETWEEN 0 AND 60))""",
        f"""INSERT INTO {schema}.fixture_plan (item_id, account_id)
SELECT i.item_id, (SELECT a.account_id FROM {schema}.accounts a WHERE a.item_id = i.item_id
                   AND a.consumer_transactions_enabled ORDER BY a.account_id LIMIT 1)
FROM {schema}.items i""",
        f"""CREATE TABLE {schema}.deliveries (
    delivery_id uuid PRIMARY KEY,
    source text,
    received_at timestamptz NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    instance_id text NOT NULL,
    instance_ordinal integer NOT NULL,
    inflight_at_start integer NOT NULL,
    hang_publication_s integer NOT NULL DEFAULT 0,
    idle_session_timeout text,
    outcome text,
    run_id text,
    error_type text,
    handler_ms integer,
    engine_checkout_peak integer)""",
        f"CREATE TABLE {schema}.trigger_nonces (nonce text PRIMARY KEY, expires_at timestamptz NOT NULL)",
        f"GRANT USAGE ON SCHEMA {schema} TO {jobs_role}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO {jobs_role}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {jobs_role}",
        # Scenarios are set by the controller, never by the endpoint.
        f"REVOKE INSERT, UPDATE, DELETE ON {schema}.fixture_plan FROM {jobs_role}",
        f"REVOKE INSERT, UPDATE, DELETE ON {schema}.fixture_manifest FROM {jobs_role}",
        # The endpoint only consumes a one-shot hang request.
        f"GRANT UPDATE (hang_publication_s) ON {schema}.fixture_manifest TO {jobs_role}",
        f"REVOKE UPDATE, DELETE ON {schema}.deliveries FROM {jobs_role}",
        f"GRANT UPDATE (finished_at, outcome, run_id, error_type, handler_ms, engine_checkout_peak) "
        f"ON {schema}.deliveries TO {jobs_role}",
    ]
    return ";\n".join(statements) + ";\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    print(migration_sql(parser.parse_args().dataset_id))
