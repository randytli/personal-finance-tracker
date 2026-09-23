from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Numeric,
    String, Integer, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from api.categories import CATEGORY_CHECK
from api.labels import LABEL_CHECK
from api.benefit_categories import BENEFIT_CATEGORY_CHECK

Base = declarative_base()


class ManualCategoryOverride(Base):
    __tablename__ = 'manual_category_overrides'
    __table_args__ = (
        CheckConstraint(CATEGORY_CHECK, name='ck_manual_category'),
        Index('ix_manual_category_updated_at', 'updated_at'),
    )
    transaction_id = Column(String, ForeignKey('transactions.transaction_id'), primary_key=True)
    category = Column(String, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_by = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
    cleared_by = Column(String, nullable=True)
    cleared_at = Column(DateTime, nullable=True)

class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("user_id", "institution_id", name="uq_items_user_institution"),
        CheckConstraint(
            "status IN ('pending', 'active', 'disabled')",
            name="ck_items_status",
        ),
        Index("ix_items_user_status", "user_id", "status"),
        Index("ix_items_institution_id", "institution_id"),
    )
    item_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    institution_id = Column(String, nullable=False)
    institution_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending", server_default="pending")
    access_token = Column(String, nullable=False)
    transactions_cursor = Column(String, nullable=True)
    sync_paused = Column(Boolean, nullable=False, default=False, server_default="false")
    last_sync_attempt_at = Column(DateTime(timezone=True))
    last_sync_success_at = Column(DateTime(timezone=True))
    last_sync_change_at = Column(DateTime(timezone=True))
    next_sync_retry_at = Column(DateTime(timezone=True))
    sync_retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    metadata_warning = Column(String)
    metadata_warning_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SyncRun(Base):
    __tablename__ = "sync_runs"
    run_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    trigger_source = Column(String, nullable=False)
    request_sequence = Column(Integer)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    duration_ms = Column(Integer)
    status = Column(String, nullable=False)
    classification_status = Column(String, nullable=False, server_default="not_run")
    classified_count = Column(Integer, nullable=False, server_default="0")
    classification_duration_ms = Column(Integer)
    published_at = Column(DateTime(timezone=True))
    error_category = Column(String)


class SyncItemRun(Base):
    __tablename__ = "sync_item_runs"
    run_id = Column(String, ForeignKey("sync_runs.run_id"), primary_key=True)
    item_id = Column(String, ForeignKey("items.item_id"), primary_key=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True))
    status = Column(String, nullable=False)
    phase = Column(String, nullable=False)
    pages_fetched = Column(Integer, nullable=False, server_default="0")
    received_added = Column(Integer, nullable=False, server_default="0")
    received_modified = Column(Integer, nullable=False, server_default="0")
    received_removed = Column(Integer, nullable=False, server_default="0")
    added_count = Column(Integer, nullable=False, server_default="0")
    modified_count = Column(Integer, nullable=False, server_default="0")
    removed_count = Column(Integer, nullable=False, server_default="0")
    skipped_disabled_count = Column(Integer, nullable=False, server_default="0")
    normalized_count = Column(Integer, nullable=False, server_default="0")
    classified_count = Column(Integer, nullable=False, server_default="0")
    retry_count = Column(Integer, nullable=False, server_default="0")
    error_category = Column(String)
    request_id = Column(String)


class SyncRuntimeState(Base):
    __tablename__ = "sync_runtime_state"
    user_id = Column(String, primary_key=True)
    last_published_run_id = Column(String, ForeignKey("sync_runs.run_id"))
    published_at = Column(DateTime(timezone=True))
    requested_sequence = Column(Integer, nullable=False, server_default="0")
    handled_sequence = Column(Integer, nullable=False, server_default="0")
    requested_item_ids = Column(JSONB)
    running_sequence = Column(Integer)
    running_item_ids = Column(JSONB)
    jobs_heartbeat_at = Column(DateTime(timezone=True))
    last_backup_at = Column(DateTime(timezone=True))
    last_backup_attempt_at = Column(DateTime(timezone=True))
    last_backup_error = Column(String)

class RawTransaction(Base):
    __tablename__ = "raw_transactions"
    transaction_id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey("items.item_id"), nullable=False)
    account_id = Column(String, nullable=False)
    transaction_date = Column(Date, nullable=False)
    payload = Column(JSONB, nullable=False)
    source = Column(String, nullable=False, default="plaid", server_default="plaid")
    statement_row_id = Column(String, ForeignKey("statement_import_rows.row_id"))
    is_removed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_raw_transactions_item_active", "item_id", "is_removed"),
        Index("ix_raw_account_date", "account_id", "transaction_date"),
        Index("ix_raw_statement_row", "statement_row_id", unique=True),
        CheckConstraint("(source = 'plaid' AND statement_row_id IS NULL) OR "
                        "(source = 'statement' AND statement_row_id IS NOT NULL)", name="ck_raw_source"),
    )

class Account(Base):
    __tablename__ = "accounts"
    account_id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey("items.item_id"), nullable=False)
    name = Column(String, nullable=False)
    official_name = Column(String, nullable=True)
    type = Column(String, nullable=False)
    subtype = Column(String, nullable=True)
    mask = Column(String, nullable=True)
    consumer_transactions_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_accounts_item_id", "item_id"),)

class LegacyConsumerRow(Base):
    """Migration-time identity snapshot; never populated by ingestion."""
    __tablename__ = "legacy_consumer_rows"
    transaction_id = Column(String, primary_key=True)
    item_id = Column(String, nullable=False)
    account_id = Column(String, nullable=False)
    normalized_account_id = Column(String, nullable=True)

class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_date", "transaction_date"),)
    transaction_id = Column(
        String,
        ForeignKey("raw_transactions.transaction_id"),
        primary_key=True,
    )
    account_id = Column(String, ForeignKey("accounts.account_id"), nullable=False)
    transaction_date = Column(Date, nullable=False)
    amount = Column(Numeric, nullable=False)
    merchant_name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    plaid_category = Column(String, nullable=True)
    statement_kind = Column(String, nullable=True)
    transaction_type = Column(String, nullable=True)
    is_spending = Column(Boolean, nullable=True)
    is_internal_transfer = Column(Boolean, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class ManualClassificationOverride(Base):
    __tablename__ = "manual_classification_overrides"
    __table_args__ = (
        CheckConstraint(
            "transaction_type IS NULL OR transaction_type IN "
            "('expense', 'refund', 'reimbursement', 'income', 'card_benefit', 'payment', 'transfer', "
            "'adjustment')",
            name="ck_manual_override_transaction_type",
        ),
        Index("ix_manual_overrides_updated_at", "updated_at"),
    )
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), primary_key=True)
    transaction_type = Column(String, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_by = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
    cleared_by = Column(String, nullable=True)
    cleared_at = Column(DateTime, nullable=True)


class ManualTransactionLabelOverride(Base):
    __tablename__ = "manual_transaction_label_overrides"
    __table_args__ = (
        CheckConstraint(LABEL_CHECK, name="ck_manual_transaction_label"),
        CheckConstraint("decision IS NULL OR decision IN ('include','exclude')",
                        name="ck_manual_transaction_label_decision"),
        Index("ix_manual_transaction_labels_updated_at", "updated_at"),
    )
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), primary_key=True)
    label = Column(String, primary_key=True)
    decision = Column(String)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_by = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
    cleared_by = Column(String)
    cleared_at = Column(DateTime)


class ManualBenefitCategoryOverride(Base):
    __tablename__ = "manual_benefit_category_overrides"
    __table_args__ = (
        CheckConstraint(BENEFIT_CATEGORY_CHECK, name="ck_manual_benefit_category"),
        Index("ix_manual_benefit_category_updated_at", "updated_at"),
    )
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), primary_key=True)
    benefit_category = Column(String, nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_by = Column(String, nullable=False)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())
    cleared_by = Column(String, nullable=True)
    cleared_at = Column(DateTime, nullable=True)


class StatementImportBatch(Base):
    __tablename__ = "statement_import_batches"
    __table_args__ = (
        UniqueConstraint("account_id", "adapter", "file_sha256", name="uq_statement_file"),
        CheckConstraint("status IN ('applied', 'rolled_back')", name="ck_statement_status"),
    )
    batch_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    item_id = Column(String, ForeignKey("items.item_id"), nullable=False)
    account_id = Column(String, ForeignKey("accounts.account_id"), nullable=False, index=True)
    adapter = Column(String, nullable=False)
    adapter_version = Column(String, nullable=False)
    file_sha256 = Column(String, nullable=False)
    import_through = Column(Date)
    preview_digest = Column(String, nullable=False)
    manifest = Column(JSONB, nullable=False)
    status = Column(String, nullable=False)
    applied_by = Column(String, nullable=False)
    applied_at = Column(DateTime, nullable=False, server_default=func.now())
    rolled_back_by = Column(String)
    rolled_back_at = Column(DateTime)
    rollback_reason = Column(String)


class StatementImportRow(Base):
    __tablename__ = "statement_import_rows"
    __table_args__ = (UniqueConstraint("batch_id", "source_record", name="uq_statement_record"),)
    row_id = Column(String, primary_key=True)
    batch_id = Column(String, ForeignKey("statement_import_batches.batch_id"), nullable=False, index=True)
    source_record = Column(Integer, nullable=False)
    source_line_end = Column(Integer, nullable=False)
    fingerprint = Column(String, nullable=False)
    disposition = Column(String, nullable=False)
    canonical = Column(JSONB, nullable=False)
    source_evidence = Column(JSONB, nullable=False)
