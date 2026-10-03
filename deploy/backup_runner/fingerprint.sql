-- PFT backup fingerprint. Needs only psql; no PFT code.
--
-- Usage (restore check, years later):
--   psql -X -q -v ON_ERROR_STOP=1 -v schemas='{public}' -d <restored db> \
--        -f fingerprint.sql > restored-fingerprint.txt
--   diff fingerprint.txt restored-fingerprint.txt      # no output = identical
--
-- Output is one line per object, sorted, with no database name, so a source
-- and its restore can be compared byte for byte:
--   table|<schema.table>|<row count>|<sha256 over per-row sha256 of to_jsonb text>
--   sequence|<schema.sequence>|<last_value>|<is_called>
--   constraint|<schema.table>|<name>|<type>|<definition>   (p, f, u, x)
--   check|<schema.table>|<name>        (names only: PostgreSQL rewrites some
--                                        CHECK expressions to an equivalent form
--                                        on restore)
--   index|<schema.table>|<name>|<definition>
--   column|<schema.table>|<column>|<type>|<nullable>|<default>
--   function|<schema.name>|<identity arguments>|<sha256 of definition/config>
--   trigger|<schema.table>|<name>|<enabled state>|<sha256 of definition>
-- Row hashes are memory-bounded: one 64-character hash per row is aggregated,
-- not the rows themselves.
--
-- When included from snapshot_dump.sql it runs inside the backup's exported
-- REPEATABLE READ snapshot, so it describes exactly what pg_dump wrote.

\pset format unaligned
\pset tuples_only on
\pset fieldsep '|'
\pset footer off
-- Rendering settings that affect to_jsonb()/catalog text; pinned on both sides.
SET TIME ZONE 'UTC';
SET search_path = pg_catalog;
SET bytea_output = 'hex';
SET extra_float_digits = 1;
SET IntervalStyle = 'postgres';

SELECT format(
    'SELECT %L || ''|'' || count(*) || ''|'' || encode(sha256(convert_to(coalesce(string_agg(h, '''' ORDER BY h COLLATE "C"), ''''), ''UTF8'')), ''hex'') FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text, ''UTF8'')), ''hex'') AS h FROM %I.%I t) s',
    'table|' || schemaname || '.' || tablename, schemaname, tablename)
FROM pg_tables
WHERE schemaname = ANY (:'schemas'::text[])
ORDER BY schemaname COLLATE "C", tablename COLLATE "C"
\gexec

SELECT format('SELECT %L || ''|'' || last_value || ''|'' || is_called FROM %I.%I',
              'sequence|' || schemaname || '.' || sequencename, schemaname, sequencename)
FROM pg_sequences
WHERE schemaname = ANY (:'schemas'::text[])
ORDER BY schemaname COLLATE "C", sequencename COLLATE "C"
\gexec

SELECT line FROM (
    SELECT CASE WHEN x.contype = 'c'
                THEN 'check|' || n.nspname || '.' || c.relname || '|' || x.conname
                ELSE 'constraint|' || n.nspname || '.' || c.relname || '|' || x.conname || '|'
                     || x.contype::text || '|' || pg_get_constraintdef(x.oid) END AS line
    FROM pg_constraint x
    JOIN pg_class c ON c.oid = x.conrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = ANY (:'schemas'::text[]) AND x.contype IN ('p', 'f', 'u', 'x', 'c')
    UNION ALL
    SELECT 'index|' || schemaname || '.' || tablename || '|' || indexname || '|' || indexdef
    FROM pg_indexes WHERE schemaname = ANY (:'schemas'::text[])
    UNION ALL
    SELECT 'column|' || table_schema || '.' || table_name || '|' || column_name || '|' || data_type
           || '|' || is_nullable || '|' || coalesce(column_default, '')
    FROM information_schema.columns WHERE table_schema = ANY (:'schemas'::text[])
    UNION ALL
    SELECT 'function|' || n.nspname || '.' || p.proname || '|'
           || pg_get_function_identity_arguments(p.oid) || '|'
           || encode(sha256(convert_to(pg_get_functiondef(p.oid), 'UTF8')), 'hex')
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = ANY (:'schemas'::text[]) AND p.prokind <> 'a'
    UNION ALL
    SELECT 'trigger|' || n.nspname || '.' || c.relname || '|' || t.tgname || '|'
           || t.tgenabled::text || '|'
           || encode(sha256(convert_to(pg_get_triggerdef(t.oid), 'UTF8')), 'hex')
    FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = ANY (:'schemas'::text[]) AND NOT t.tgisinternal
) catalog
ORDER BY line COLLATE "C";
