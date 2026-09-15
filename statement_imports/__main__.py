import argparse
from datetime import date
import json
import asyncio
import os
from pathlib import Path

from .models import StatementImportAdapter
from .robinhood import RobinhoodGoldCardCSV

ADAPTERS: dict[str, StatementImportAdapter] = {"robinhood-gold-card": RobinhoodGoldCardCSV()}


async def database_command(args, data):
    # Lazy imports keep Phase 1 dry-run entirely independent of database configuration.
    from api.db import SessionLocal, engine, verify_database_name
    from sqlalchemy import text
    from .persistence import preview, apply, rollback_preview, rollback, ImportBlocked
    try:
        await verify_database_name()
        user_id = os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user")
        if os.environ.get("PLAID_ENV", "").lower() == "production" and not os.environ.get("PLAID_PILOT_USER_ID"):
            raise ImportBlocked("Production requires an explicit configured user")
        async with SessionLocal.begin() as db:
            if args.command in {"preview", "rollback-preview"}:
                await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            if args.command == "preview":
                return await preview(db, user_id, args.account_id, ADAPTERS[args.adapter], data, args.through)
            if args.command == "apply":
                approved = json.loads(args.manifest.read_text())
                return await apply(db, user_id, args.account_id, ADAPTERS[args.adapter], data,
                                   args.through, approved, args.confirm)
            if args.command == "rollback-preview":
                return (await rollback_preview(db, user_id, args.batch_id))[0]
            return await rollback(db, user_id, args.batch_id, args.confirm, args.reason)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Statement parsing and explicitly reviewed persistence")
    parser.add_argument("command", choices=["dry-run", "preview", "apply", "rollback-preview", "rollback"])
    parser.add_argument("path", type=Path, nargs="?")
    parser.add_argument("--adapter", choices=sorted(ADAPTERS))
    parser.add_argument("--through", type=date.fromisoformat, help="Inclusive transaction date cutoff (YYYY-MM-DD)")
    parser.add_argument("--account-id")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--confirm", help="Exact reviewed preview digest; acknowledges displayed warnings")
    parser.add_argument("--batch-id")
    parser.add_argument("--reason")
    parser.add_argument("--output", type=Path, help="New private preview file (never overwritten)")
    args = parser.parse_args()
    if args.command in {"dry-run", "preview", "apply"} and (not args.path or not args.adapter):
        parser.error("path and --adapter required")
    if args.command in {"preview", "apply"} and not args.account_id:
        parser.error("--account-id required")
    if args.command == "apply" and (not args.manifest or not args.confirm):
        parser.error("--manifest and --confirm required")
    if args.command.startswith("rollback") and not args.batch_id:
        parser.error("--batch-id required")
    if args.command == "rollback" and (not args.confirm or not args.reason):
        parser.error("--confirm and --reason required")
    if args.output and args.command not in {"preview", "rollback-preview"}:
        parser.error("--output is only allowed for read-only previews")
    try:
        data = args.path.read_bytes() if args.path else None
    except OSError:
        parser.exit(2, "Cannot read statement file. Check its path and permissions.\n")
    if args.command == "dry-run":
        parsed = ADAPTERS[args.adapter].parse(data, through=args.through)
        print(json.dumps(parsed.report(), indent=2))
        return 2 if parsed.errors else 0
    from .persistence import ImportBlocked
    from sqlalchemy.exc import SQLAlchemyError
    try:
        result = asyncio.run(database_command(args, data))
        rendered = json.dumps(result, indent=2)
        if args.output:
            with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
                output.write(rendered + "\n")
            print(json.dumps({"digest": result["digest"], "blockers": result["blockers"]}))
        else:
            print(rendered)
        return 2 if result.get("blockers") else 0
    except ImportBlocked as exc:
        parser.exit(2, str(exc) + "\n")
    except (SQLAlchemyError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        parser.exit(2, "Statement operation failed. Verify database/migration, file, and manifest; no partial apply is committed.\n")


if __name__ == "__main__":
    raise SystemExit(main())
