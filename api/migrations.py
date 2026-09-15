import os

from sqlalchemy import text


async def migrate_transaction_labels(connection):
    from api.labels import LABEL_CHECK
    from api.models import ManualTransactionLabelOverride
    await connection.run_sync(
        lambda sync: ManualTransactionLabelOverride.__table__.create(sync, checkfirst=True)
    )
    await connection.execute(text(
        "ALTER TABLE manual_transaction_label_overrides "
        "DROP CONSTRAINT IF EXISTS ck_manual_transaction_label"
    ))
    await connection.execute(text(
        "ALTER TABLE manual_transaction_label_overrides "
        f"ADD CONSTRAINT ck_manual_transaction_label CHECK ({LABEL_CHECK})"
    ))


async def migrate_statement_imports(connection):
    from api.models import StatementImportBatch, StatementImportRow
    for table in (StatementImportBatch.__table__, StatementImportRow.__table__):
        await connection.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
    await connection.execute(text("ALTER TABLE raw_transactions ADD COLUMN IF NOT EXISTS "
                                  "source VARCHAR NOT NULL DEFAULT 'plaid'"))
    await connection.execute(text("ALTER TABLE raw_transactions ADD COLUMN IF NOT EXISTS "
                                  "statement_row_id VARCHAR REFERENCES statement_import_rows(row_id)"))
    await connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_raw_statement_row "
                                  "ON raw_transactions(statement_row_id)"))
    await connection.execute(text("CREATE INDEX IF NOT EXISTS ix_raw_account_date "
                                  "ON raw_transactions(account_id, transaction_date)"))
    await connection.execute(text("ALTER TABLE raw_transactions DROP CONSTRAINT IF EXISTS ck_raw_source"))
    await connection.execute(text("ALTER TABLE raw_transactions ADD CONSTRAINT ck_raw_source CHECK ("
                                  "(source='plaid' AND statement_row_id IS NULL) OR "
                                  "(source='statement' AND statement_row_id IS NOT NULL))"))
    await connection.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS statement_kind VARCHAR"))


async def migrate_consumer_scope(connection):
    # NULL marks legacy accounts only; explicit decisions are never reset.
    await connection.execute(text(
        "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS consumer_transactions_enabled BOOLEAN"
    ))
    await connection.execute(text(
        "CREATE TABLE IF NOT EXISTS consumer_scope_migrations (version INTEGER PRIMARY KEY)"
    ))
    await connection.execute(text(
        "CREATE TABLE IF NOT EXISTS legacy_consumer_rows (transaction_id VARCHAR PRIMARY KEY, "
        "item_id VARCHAR NOT NULL, account_id VARCHAR NOT NULL, normalized_account_id VARCHAR)"
    ))
    # Snapshot once, including enabled accounts that might be disabled in a future phase.
    # Serialize initialization and never grandfather newly ingested rows on reruns.
    await connection.execute(text("LOCK TABLE consumer_scope_migrations IN EXCLUSIVE MODE"))
    if not await connection.scalar(text("SELECT count(*) FROM consumer_scope_migrations WHERE version=1")):
        await connection.execute(text(
            "INSERT INTO legacy_consumer_rows "
            "SELECT r.transaction_id, r.item_id, r.account_id, t.account_id "
            "FROM raw_transactions r LEFT JOIN transactions t USING (transaction_id)"
        ))
        await connection.execute(text("INSERT INTO consumer_scope_migrations VALUES (1)"))
    await connection.execute(text(
        "UPDATE accounts SET consumer_transactions_enabled = "
        "COALESCE(type IN ('credit','depository'), false) WHERE consumer_transactions_enabled IS NULL"
    ))
    await connection.execute(text(
        "ALTER TABLE accounts ALTER COLUMN consumer_transactions_enabled SET DEFAULT false"
    ))
    await connection.execute(text(
        "ALTER TABLE accounts ALTER COLUMN consumer_transactions_enabled SET NOT NULL"
    ))


async def migrate_manual_categories(connection):
    from api.categories import CATEGORY_CHECK
    from api.models import ManualCategoryOverride
    await connection.run_sync(
        lambda sync: ManualCategoryOverride.__table__.create(sync, checkfirst=True)
    )
    # init_db runs this in one transaction: replace only the constraint, never rows.
    # create(checkfirst=True) alone does not update an existing table's vocabulary.
    await connection.execute(text(
        "ALTER TABLE manual_category_overrides DROP CONSTRAINT IF EXISTS ck_manual_category"
    ))
    await connection.execute(text(
        "ALTER TABLE manual_category_overrides ADD CONSTRAINT ck_manual_category "
        f"CHECK ({CATEGORY_CHECK})"
    ))


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
