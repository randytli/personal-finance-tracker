-- One consistent backup: identity check, exported snapshot, pg_dump inside that
-- snapshot, fingerprint of the same snapshot. Driven by pft_backup_runner.py.
--
-- psql variables: expected_database, schemas ('{public}'), fingerprint_file.
-- Environment: PG* connection settings (inherited by pg_dump), PFT_WORK (output
-- directory), PFT_DUMP_SCHEMA_ARGS ("-n public ...", validated by the runner).
\set ON_ERROR_STOP on
\pset format unaligned
\pset tuples_only on

BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
-- Wrong database: division by zero aborts the script before anything is dumped.
-- (Not CASE ... ELSE 1/0: PostgreSQL folds that constant at plan time.)
SELECT 1 / (current_database() = :'expected_database')::int AS identity_ok;
SELECT pg_export_snapshot() AS pft_snapshot \gset
\setenv PFT_SNAPSHOT :pft_snapshot
-- \! receives the rest of the line verbatim (no psql interpolation); the shell
-- expands the environment. dump.ok is written only when pg_dump succeeds.
\! pg_dump --snapshot="$PFT_SNAPSHOT" $PFT_DUMP_SCHEMA_ARGS -Fc -f "$PFT_WORK/backup.dump" && touch "$PFT_WORK/dump.ok"
\o :fingerprint_file
\ir fingerprint.sql
\o
ROLLBACK;
