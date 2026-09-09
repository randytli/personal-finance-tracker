from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Index, Numeric,
    String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base
from api.categories import CATEGORY_CHECK

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
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class RawTransaction(Base):
    __tablename__ = "raw_transactions"
    transaction_id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey("items.item_id"), nullable=False)
    account_id = Column(String, nullable=False)
    transaction_date = Column(Date, nullable=False)
    payload = Column(JSONB, nullable=False)
    is_removed = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_raw_transactions_item_active", "item_id", "is_removed"),)

class Account(Base):
    __tablename__ = "accounts"
    account_id = Column(String, primary_key=True)
    item_id = Column(String, ForeignKey("items.item_id"), nullable=False)
    name = Column(String, nullable=False)
    official_name = Column(String, nullable=True)
    type = Column(String, nullable=False)
    subtype = Column(String, nullable=True)
    mask = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_accounts_item_id", "item_id"),)

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
            "('expense', 'refund', 'income', 'card_benefit', 'payment', 'transfer', "
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
