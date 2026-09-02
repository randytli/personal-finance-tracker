import os

from sqlalchemy import text


async def migrate_multi_institution(connection):
    """Idempotently upgrade the original single-Item schema without rewriting data."""
    user_id = os.environ.get("PLAID_PILOT_USER_ID", "local-sandbox-user")
    chase_id = os.environ.get("PFT_EXISTING_CHASE_INSTITUTION_ID")
    chase_name = os.environ.get("PFT_EXISTING_CHASE_INSTITUTION_NAME", "Chase")

    await connection.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS user_id VARCHAR"))
    await connection.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS institution_id VARCHAR"))
    await connection.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS institution_name VARCHAR"))
    await connection.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS status VARCHAR"))

    legacy_count = await connection.scalar(text(
        "SELECT count(*) FROM items WHERE user_id IS NULL OR institution_id IS NULL "
        "OR institution_name IS NULL OR status IS NULL"
    ))
    if legacy_count:
        total_count = await connection.scalar(text("SELECT count(*) FROM items"))
        if total_count != 1:
            raise RuntimeError("Legacy Item migration requires exactly one existing Item")
        if not chase_id:
            raise RuntimeError(
                "Set PFT_EXISTING_CHASE_INSTITUTION_ID after safely verifying the "
                "existing Item identity"
            )
        await connection.execute(
            text(
                "UPDATE items SET user_id=:user_id, institution_id=:institution_id, "
                "institution_name=:institution_name, status='active' "
                "WHERE user_id IS NULL OR institution_id IS NULL "
                "OR institution_name IS NULL OR status IS NULL"
            ),
            {"user_id": user_id, "institution_id": chase_id, "institution_name": chase_name},
        )

    await connection.execute(text("ALTER TABLE items ALTER COLUMN user_id SET NOT NULL"))
    await connection.execute(text("ALTER TABLE items ALTER COLUMN institution_id SET NOT NULL"))
    await connection.execute(text("ALTER TABLE items ALTER COLUMN institution_name SET NOT NULL"))
    await connection.execute(text("ALTER TABLE items ALTER COLUMN status SET DEFAULT 'pending'"))
    await connection.execute(text("ALTER TABLE items ALTER COLUMN status SET NOT NULL"))
    await connection.execute(text(
        "DO $$ BEGIN ALTER TABLE items ADD CONSTRAINT ck_items_status "
        "CHECK (status IN ('pending','active','disabled')); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    ))
    await connection.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_items_user_institution "
        "ON items (user_id, institution_id)"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_items_user_status ON items (user_id, status)"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_items_institution_id ON items (institution_id)"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_accounts_item_id ON accounts (item_id)"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_raw_transactions_item_active "
        "ON raw_transactions (item_id, is_removed)"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_transactions_date ON transactions (transaction_date)"
    ))
    await connection.execute(text(
        "CREATE TABLE IF NOT EXISTS manual_classification_overrides ("
        "transaction_id VARCHAR PRIMARY KEY REFERENCES transactions(transaction_id), "
        "transaction_type VARCHAR NULL, created_by VARCHAR NOT NULL, "
        "created_at TIMESTAMP NOT NULL DEFAULT now(), updated_by VARCHAR NOT NULL, "
        "updated_at TIMESTAMP NOT NULL DEFAULT now(), cleared_by VARCHAR NULL, "
        "cleared_at TIMESTAMP NULL)"
    ))
    await connection.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        "SELECT 1 FROM pg_constraint WHERE conname='ck_manual_override_transaction_type' "
        "AND pg_get_constraintdef(oid) LIKE '%adjustment%'"
        ") THEN "
        "ALTER TABLE manual_classification_overrides DROP CONSTRAINT IF EXISTS "
        "ck_manual_override_transaction_type; "
        "ALTER TABLE manual_classification_overrides ADD CONSTRAINT "
        "ck_manual_override_transaction_type CHECK ("
        "transaction_type IS NULL OR transaction_type IN "
        "('expense','refund','income','card_benefit','payment','transfer','adjustment')); "
        "END IF; END $$"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_manual_overrides_updated_at "
        "ON manual_classification_overrides (updated_at)"
    ))
