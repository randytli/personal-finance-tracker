"""Prepare private M6 runtime files from the existing backfill configuration.

Run only after sourcing .env.backend.production-backfill.local. This command
does not connect to any database or print credential values.
"""

import os
from pathlib import Path

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parent.parent
DB_NAME = "pft_production_backfill"
OUTPUTS = {
    ".env.runtime.production.local": None,
    ".env.runtime.db.production.local": None,
    ".env.runtime.backup.production.local": None,
}


def value(name):
    result = os.environ.get(name)
    if not result or "\n" in result or "\r" in result:
        raise RuntimeError(f"Missing or invalid {name}")
    return result


def write_private(path, entries):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            for name, entry in entries.items():
                stream.write(f"{name}={entry}\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main():
    if value("PLAID_ENV") != "production":
        raise RuntimeError("Source must be the backfill Production environment")
    if value("EXPECTED_DATABASE_NAME") != DB_NAME or value("PFT_BACKFILL_DB_NAME") != DB_NAME:
        raise RuntimeError("Source database identity mismatch")
    url = make_url(value("DATABASE_URL"))
    if (url.database != DB_NAME or url.host not in {"127.0.0.1", "localhost"}
            or url.port != 5434 or url.username != value("PFT_BACKFILL_DB_USER")
            or url.password != value("PFT_BACKFILL_DB_PASSWORD")):
        raise RuntimeError("Source URL does not match the M0 backfill database")
    if any((ROOT / name).exists() for name in OUTPUTS):
        raise RuntimeError("A Production runtime file already exists; refusing to overwrite it")
    internal_url = url.set(host="db", port=5432).render_as_string(hide_password=False)
    runtime = {
        name: value(name) for name in (
            "PLAID_ENV", "PLAID_CLIENT_ID", "PLAID_SECRET",
            "PLAID_TOKEN_ENCRYPTION_KEY", "PLAID_PILOT_USER_ID",
            "PLAID_REDIRECT_URI", "PLAID_PILOT_LINK_ENABLED",
            "PFT_EXISTING_CHASE_INSTITUTION_ID",
            "PFT_EXISTING_CHASE_INSTITUTION_NAME",
        )
    }
    runtime.update(DATABASE_URL=internal_url, EXPECTED_DATABASE_NAME=DB_NAME,
                   PFT_STRICT_LOCAL_HTTP="true",
                   PFT_ALLOWED_ORIGIN="http://127.0.0.1:3000")
    database = {"POSTGRES_USER": url.username,
                "POSTGRES_PASSWORD": url.password, "POSTGRES_DB": DB_NAME}
    backup = {"DATABASE_URL": internal_url, "EXPECTED_DATABASE_NAME": DB_NAME,
              "POSTGRES_DB": DB_NAME, "PFT_BACKUP_HOST_ACL_VERIFIED": "true"}
    for name, entries in zip(OUTPUTS, (runtime, database, backup)):
        write_private(ROOT / name, entries)
    print("Prepared three private Production runtime files; no values printed")


if __name__ == "__main__":
    main()
