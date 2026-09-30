"""Prepare/apply/reverse a reviewed manifest. No runtime startup integration."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from sqlalchemy import text
from api.db import SessionLocal, engine
from api.services.dining_migration import prepare, change, snapshot


def private_write(path, value):
    # Evidence must never silently overwrite a previous action record.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(value, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())


async def run(args):
    if Path(args.output).exists():
        raise ValueError('Evidence output already exists')
    if args.command != 'prepare' and os.environ.get('PLAID_ENV') == 'production' and not args.production_authorized:
        raise ValueError('Separate Production authorization required')
    async with SessionLocal() as db:
        async with db.begin():
            await db.execute(text("SET LOCAL lock_timeout='10s'"))
            await db.execute(text("SET LOCAL statement_timeout='120s'"))
            if args.command == 'prepare':
                await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            identity = await db.scalar(text('SELECT current_database()'))
            if identity != args.expected_database:
                raise ValueError('Wrong database identity')
            if args.command == 'prepare':
                result = await prepare(db)
                result['database'] = identity
            else:
                manifest = json.loads(Path(args.manifest).read_text())
                manifest = manifest.get('result', manifest)
                if manifest['database'] != identity:
                    raise ValueError('Wrong manifest database')
                result = await change(db, manifest, rollback=args.command == 'rollback', user_id=args.user_id)
            private_write(args.output, {'state':'validated_before_commit', 'command':args.command, 'result':result})
        # Separate durable receipt: a crash before it requires read-only commit reconciliation.
        private_write(args.output + '.committed', {'state':'committed', 'command':args.command, 'database':identity})
    if args.command != 'prepare':
        async with SessionLocal() as db:
            await db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            state = await snapshot(db)
            expected = result if args.command == 'rollback' else result['after']
            if state != expected:
                raise ValueError('Committed state differs from validated migration evidence')
        private_write(args.output + '.verified', {'state':'committed_state_verified','database':identity})
    await engine.dispose()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare','apply','rollback'])
    p.add_argument('--expected-database', required=True)
    p.add_argument('--user-id', required=True)
    p.add_argument('--manifest')
    p.add_argument('--output', required=True)
    p.add_argument('--production-authorized', action='store_true')
    args = p.parse_args()
    if args.command != 'prepare' and not args.manifest: p.error('--manifest required')
    asyncio.run(run(args))
