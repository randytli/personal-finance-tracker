import argparse
from datetime import date
import json
from pathlib import Path

from .models import StatementImportAdapter
from .robinhood import RobinhoodGoldCardCSV

ADAPTERS: dict[str, StatementImportAdapter] = {"robinhood-gold-card": RobinhoodGoldCardCSV()}


def main():
    parser = argparse.ArgumentParser(description="Parse statements in memory; never writes to a database")
    parser.add_argument("command", choices=["dry-run"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--adapter", required=True, choices=sorted(ADAPTERS))
    parser.add_argument("--through", type=date.fromisoformat, help="Inclusive transaction date cutoff (YYYY-MM-DD)")
    args = parser.parse_args()
    try:
        data = args.path.read_bytes()
    except OSError:
        parser.exit(2, "Cannot read statement file. Check its path and permissions.\n")
    preview = ADAPTERS[args.adapter].parse(data, through=args.through)
    print(json.dumps(preview.report(), indent=2))
    return 2 if preview.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
