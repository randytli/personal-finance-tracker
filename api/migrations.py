import os

from sqlalchemy import text


async def migrate_sync_runs(connection):
    """Add M2 run state without changing existing financial rows or cursors."""
    from api.models import SyncRun, SyncItemRun, SyncRuntimeState
    for name, definition in (
        ("sync_paused", "BOOLEAN NOT NULL DEFAULT false"),
        ("last_sync_attempt_at", "TIMESTAMPTZ"),
        ("last_sync_success_at", "TIMESTAMPTZ"),
        ("last_sync_change_at", "TIMESTAMPTZ"),
        ("next_sync_retry_at", "TIMESTAMPTZ"),
        ("sync_retry_count", "INTEGER NOT NULL DEFAULT 0"),
        ("metadata_warning", "VARCHAR"),
        ("metadata_warning_at", "TIMESTAMPTZ"),
    ):
        await connection.execute(text(f"ALTER TABLE items ADD COLUMN IF NOT EXISTS {name} {definition}"))
    for table in (SyncRun.__table__, SyncItemRun.__table__, SyncRuntimeState.__table__):
        await connection.run_sync(lambda sync, table=table: table.create(sync, checkfirst=True))
    await connection.execute(text("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS request_sequence INTEGER"))
    for name, definition in (
        ("requested_item_ids", "JSONB"),
        ("running_sequence", "INTEGER"),
        ("running_item_ids", "JSONB"),
        ("last_backup_attempt_at", "TIMESTAMPTZ"),
        ("last_backup_error", "VARCHAR"),
    ):
        await connection.execute(text(f"ALTER TABLE sync_runtime_state ADD COLUMN IF NOT EXISTS {name} {definition}"))


async def migrate_transaction_labels(connection):
    """Upgrade definitions/constraints without rewriting any historical decision."""
    from api.models import ManualTransactionLabelOverride, TransactionLabelDefinition
    from api.label_schema import LABEL_SCHEMA_SQL
    await connection.run_sync(
        lambda sync: TransactionLabelDefinition.__table__.create(sync, checkfirst=True))
    for index in TransactionLabelDefinition.__table__.indexes:
        await connection.run_sync(lambda sync, index=index: index.create(sync, checkfirst=True))
    # Seed the stable system IDs before adding the reference to existing rows.
    await connection.execute(text(LABEL_SCHEMA_SQL[0]))
    await connection.run_sync(
        lambda sync: ManualTransactionLabelOverride.__table__.create(sync, checkfirst=True))
    await connection.execute(text(
        "ALTER TABLE manual_transaction_label_overrides "
        "DROP CONSTRAINT IF EXISTS ck_manual_transaction_label"))
    await connection.execute(text("""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint
          WHERE conrelid = 'manual_transaction_label_overrides'::regclass
          AND conname = 'fk_manual_transaction_label') THEN
          ALTER TABLE manual_transaction_label_overrides
          ADD CONSTRAINT fk_manual_transaction_label FOREIGN KEY (label)
          REFERENCES transaction_label_definitions(label_id);
        END IF;
        END $$"""))
    for statement in LABEL_SCHEMA_SQL[1:]:
        await connection.execute(text(statement))


async def migrate_benefit_categories(connection):
    from api.benefit_categories import BENEFIT_CATEGORY_CHECK
    from api.models import ManualBenefitCategoryOverride
    await connection.run_sync(lambda sync: ManualBenefitCategoryOverride.__table__.create(sync, checkfirst=True))
    await connection.execute(text("ALTER TABLE manual_benefit_category_overrides DROP CONSTRAINT IF EXISTS ck_manual_benefit_category"))
    await connection.execute(text(
        "ALTER TABLE manual_benefit_category_overrides ADD CONSTRAINT ck_manual_benefit_category CHECK (" + BENEFIT_CATEGORY_CHECK + ")"
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
    legacy = await connection.scalar(text(
        "SELECT count(*) FROM manual_category_overrides WHERE category='FOOD_AND_DRINK'"))
    if legacy:
        raise RuntimeError("Explicit reviewed Dining migration required before schema migration")
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
        "SELECT 1 FROM pg_constraint WHERE conrelid='manual_classification_overrides'::regclass "
        "AND conname='ck_manual_override_transaction_type' "
        "AND pg_get_constraintdef(oid) LIKE '%reimbursement%'"
        ") THEN "
        "ALTER TABLE manual_classification_overrides DROP CONSTRAINT IF EXISTS "
        "ck_manual_override_transaction_type; "
        "ALTER TABLE manual_classification_overrides ADD CONSTRAINT "
        "ck_manual_override_transaction_type CHECK ("
        "transaction_type IS NULL OR transaction_type IN "
        "('expense','refund','reimbursement','income','card_benefit','payment','transfer','adjustment')); "
        "END IF; END $$"
    ))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_manual_overrides_updated_at "
        "ON manual_classification_overrides (updated_at)"
    ))




LIFECYCLE_COLUMNS = ("sync_enabled", "published", "activated_at", "deactivated_at", "activation_digest",
                     "disconnected_at")
LIFECYCLE_STATUSES = ("pending", "active", "deactivated", "disabled")


class LifecyclePreflightBlocked(RuntimeError):
    def __init__(self, errors, report):
        super().__init__("Institution lifecycle migration preflight blocked: " + "; ".join(errors))
        self.errors = errors
        self.report = report


async def institution_lifecycle_preflight(connection):
    """Describe whether the lifecycle migration may run, using only reads."""
    report = {"items_table": False, "applied": False, "status_counts": {}, "blockers": []}
    if await connection.scalar(text("SELECT to_regclass('items')")) is None:
        return report
    report["items_table"] = True
    columns = set((await connection.execute(text(
        "SELECT attname FROM pg_attribute WHERE attrelid='items'::regclass AND attnum>0 AND NOT attisdropped"
    ))).scalars())
    if "status" not in columns:
        report["blockers"].append("items.status is missing")
        return report
    report["status_counts"] = dict((await connection.execute(text(
        "SELECT coalesce(status, '<null>'), count(*) FROM items GROUP BY 1 ORDER BY 1"))).all())
    present = [name for name in LIFECYCLE_COLUMNS if name in columns]
    report["applied"] = len(present) == len(LIFECYCLE_COLUMNS)
    if present and not report["applied"]:
        report["blockers"].append("lifecycle columns are partially present: " + ", ".join(present))
    unknown = sorted(status for status in report["status_counts"] if status not in LIFECYCLE_STATUSES)
    if unknown:
        report["blockers"].append("unsupported Item status: " + ", ".join(unknown))
    if report["applied"] and not unknown:
        from api.models import LIFECYCLE_STATES
        expected = " OR ".join(
            f"(status = '{status}' AND sync_enabled = {sync} AND published = {published})"
            for status, (sync, published) in LIFECYCLE_STATES.items())
        mismatched = await connection.scalar(text(f"SELECT count(*) FROM items WHERE NOT ({expected})"))
        if mismatched:
            report["blockers"].append(f"{mismatched} Items have lifecycle flags that differ from their status")
    return report


def lifecycle_preflight_errors(report, production):
    errors = list(report["blockers"])
    # Production must be exactly the expected baseline; nothing is promoted or reinterpreted.
    if production and report["items_table"] and not report["applied"]:
        other = {status: count for status, count in report["status_counts"].items() if status != "active"}
        if other:
            errors.append("Production Items must all be active before this migration; found "
                          + ", ".join(f"{status}={count}" for status, count in sorted(other.items())))
    return errors


async def require_lifecycle_preflight(connection, *, production):
    report = await institution_lifecycle_preflight(connection)
    errors = lifecycle_preflight_errors(report, production)
    if errors:
        raise LifecyclePreflightBlocked(errors, report)
    return report


async def migrate_institution_lifecycle(connection):
    """Derive lifecycle scope flags from status; no financial row is touched.

    Generated columns keep status the single written field, so older images that
    write only status stay consistent, and the flags equal the old status filters.
    """
    from api.models import PUBLISHED_SQL, SYNC_ENABLED_SQL
    await require_lifecycle_preflight(connection, production=False)
    await connection.execute(text(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='items'::regclass "
        "AND conname='ck_items_status' AND pg_get_constraintdef(oid) LIKE '%deactivated%') THEN "
        "ALTER TABLE items DROP CONSTRAINT IF EXISTS ck_items_status; "
        "ALTER TABLE items ADD CONSTRAINT ck_items_status "
        "CHECK (status IN ('pending','active','deactivated','disabled')); "
        "END IF; END $$"
    ))
    for name, expression in (("sync_enabled", SYNC_ENABLED_SQL), ("published", PUBLISHED_SQL)):
        await connection.execute(text(
            f"ALTER TABLE items ADD COLUMN IF NOT EXISTS {name} BOOLEAN NOT NULL "
            f"GENERATED ALWAYS AS ({expression}) STORED"))
    for name in ("activated_at", "deactivated_at", "disconnected_at"):
        await connection.execute(text(f"ALTER TABLE items ADD COLUMN IF NOT EXISTS {name} TIMESTAMPTZ"))
    await connection.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS activation_digest VARCHAR"))
    await connection.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_items_user_lifecycle ON items (user_id, sync_enabled, published)"
    ))
