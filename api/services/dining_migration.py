"""Explicit reviewed Dining migration; never invoked by runtime startup."""
import hashlib
import json
from sqlalchemy import text
from api.categories import CATEGORY_CHECK
from api.statement_semantics import lock_consumer_derivation

MIGRATION_ID = 'm3-manual-dining-v1'


def digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


async def snapshot(connection):
    tables = (await connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
    fingerprints = {}
    overrides = []
    for table in tables:
        quoted = connection.get_bind().dialect.identifier_preparer.quote(table)
        rows = (await connection.execute(text(
            f'SELECT to_jsonb(t)::text FROM {quoted} t ORDER BY to_jsonb(t)::text COLLATE "C"'))).scalars().all()
        fingerprints[table] = {'count': len(rows), 'sha256': digest(rows)}
        if table == 'manual_category_overrides':
            overrides = [json.loads(row) for row in rows]
    constraint = (await connection.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid='manual_category_overrides'::regclass AND conname='ck_manual_category'"))).scalar_one()
    counts = {}
    for row in overrides:
        key = str(row['category']) + (':active' if row['cleared_at'] is None else ':cleared')
        counts[key] = counts.get(key, 0) + 1
    return {'tables': fingerprints, 'overrides': overrides, 'constraint': constraint, 'counts': counts}


async def prepare(connection):
    state = await snapshot(connection)
    if any(r['category'] == 'FOOD_AND_DRINK' and r['cleared_at'] is not None for r in state['overrides']):
        raise ValueError('Cleared FOOD_AND_DRINK rows require separate owner review')
    targets = [r for r in state['overrides'] if r['category'] == 'FOOD_AND_DRINK' and r['cleared_at'] is None]
    if not targets:
        raise ValueError('No active FOOD_AND_DRINK migration targets')
    return {'migration_id': MIGRATION_ID, 'before': state, 'target_ids': sorted(r['transaction_id'] for r in targets),
            'restore_constraint_sql': 'CHECK (' + CATEGORY_CHECK.replace("'DINING'", "'FOOD_AND_DRINK'") + ')'}


async def change(connection, manifest, *, rollback=False, user_id):
    """Caller owns transaction; any failure must roll back its DDL and updates."""
    if manifest.get('migration_id') != MIGRATION_ID:
        raise ValueError('Wrong migration manifest')
    await lock_consumer_derivation(connection, user_id)
    tables = (await connection.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
    # Maintenance-only: prevent concurrent writes, including unrelated audit writes.
    for table in tables:
        quoted = connection.get_bind().dialect.identifier_preparer.quote(table)
        mode = 'ACCESS EXCLUSIVE' if table == 'manual_category_overrides' else 'SHARE'
        await connection.execute(text(f'LOCK TABLE {quoted} IN {mode} MODE'))
    expected = manifest['after'] if rollback else manifest['before']
    before = await snapshot(connection)
    if before != expected:
        raise ValueError('Database changed since reviewed manifest; refusing migration')
    source, destination = ('DINING', 'FOOD_AND_DRINK') if rollback else ('FOOD_AND_DRINK', 'DINING')
    target_ids = manifest['target_ids']
    if not target_ids or len(set(target_ids)) != len(target_ids):
        raise ValueError('Invalid target manifest')
    actual_targets = sorted(r['transaction_id'] for r in before['overrides']
                            if r['category'] == source and r['cleared_at'] is None
                            and (not rollback or r['transaction_id'] in target_ids))
    if actual_targets != target_ids:
        raise ValueError('Target rows differ from manifest')
    await connection.execute(text('ALTER TABLE manual_category_overrides DROP CONSTRAINT ck_manual_category'))
    # SQL bypasses ORM onupdate metadata; full-row checks also detect DB triggers.
    result = await connection.execute(text(
        'UPDATE manual_category_overrides SET category=:destination '
        'WHERE transaction_id=ANY(:ids) AND category=:source AND cleared_at IS NULL'),
        {'destination': destination, 'ids': target_ids, 'source': source})
    if result.rowcount != len(target_ids):
        raise ValueError('Unexpected migrated count')
    constraint = manifest['restore_constraint_sql'] if rollback else f'CHECK ({CATEGORY_CHECK})'
    await connection.execute(text('ALTER TABLE manual_category_overrides ADD CONSTRAINT ck_manual_category ' + constraint))
    after = await snapshot(connection)
    expected_rows = [dict(r, category=destination) if r['transaction_id'] in target_ids else r
                     for r in before['overrides']]
    if sorted(expected_rows, key=lambda r:r['transaction_id']) != sorted(after['overrides'], key=lambda r:r['transaction_id']):
        raise ValueError('Unexpected audit row changes')
    for table, fingerprint in before['tables'].items():
        if table != 'manual_category_overrides' and after['tables'].get(table) != fingerprint:
            raise ValueError('Unrelated financial fingerprint changed: ' + table)
    if rollback and after != manifest['before']:
        raise ValueError('Rollback did not restore exact baseline: ' + ','.join(k for k in after if after[k] != manifest['before'][k]))
    return {**manifest, 'after': after} if not rollback else after
