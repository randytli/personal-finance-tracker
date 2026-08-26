from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Item(Base):
    __tablename__ = "items"
    item_id = Column(String, primary_key=True)
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

class Transaction(Base):
    __tablename__ = "transactions"
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
