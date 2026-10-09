"""Synthetic populated fixture for the M5 backup drill; disposable databases only.

Every application table receives rows, including overrides, statement evidence,
sync runs and runtime state. Descriptions and payloads are random so archive
sizes are not flattered by identical rows. No real financial data.
"""
from datetime import date, datetime, timedelta, timezone
import random
import secrets

from cryptography.fernet import Fernet
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.models import (Account, Item, LegacyConsumerRow, ManualBenefitCategoryOverride,
                        ManualCategoryOverride, ManualClassificationOverride,
                        ManualTransactionLabelOverride, RawTransaction, StatementImportBatch,
                        StatementImportRow, SyncItemRun, SyncRun, SyncRuntimeState, Transaction, TransactionLabelDefinition)

USER = "synthetic-backup-user"


async def seed(engine, rows=2610, seed_value=20261002):
    """Five active Items, 13 accounts (9 enabled), ``rows`` raw+normalized rows."""
    rng = random.Random(seed_value)
    token_key = Fernet.generate_key()
    now = datetime(2026, 10, 2, 4, 0, tzinfo=timezone.utc)
    items, accounts = [], []
    for i in range(5):
        items.append({"item_id": f"item-{i}", "user_id": USER, "institution_id": f"ins_{i}",
                      "institution_name": f"Synthetic Bank {i}", "status": "active",
                      "access_token": "enc:" + Fernet(token_key).encrypt(secrets.token_bytes(24)).decode(),
                      "transactions_cursor": secrets.token_urlsafe(48), "last_sync_success_at": now})
        for j in range(3 if i < 3 else 2):
            accounts.append({"account_id": f"account-{i}-{j}", "item_id": f"item-{i}",
                             "name": f"Synthetic {i}-{j}", "type": "credit" if j == 0 else "depository",
                             "consumer_transactions_enabled": len(accounts) < 9})
    enabled = [a["account_id"] for a in accounts if a["consumer_transactions_enabled"]]
    raw, normalized = [], []
    for n in range(rows):
        account = enabled[n % len(enabled)]
        item = account.rsplit("-", 1)[0].replace("account", "item")
        day = date(2024, 10, 1) + timedelta(days=rng.randrange(730))
        amount = round(rng.uniform(-400, 120), 2)
        tid = f"txn-{n:06d}-{secrets.token_hex(6)}"
        merchant = f"Merchant {secrets.token_hex(5)}"
        raw.append({"transaction_id": tid, "item_id": item, "account_id": account,
                    "transaction_date": day, "source": "plaid", "is_removed": n % 97 == 0,
                    "payload": {"transaction_id": tid, "amount": -amount, "name": merchant,
                                "merchant_name": merchant, "date": day.isoformat(),
                                "personal_finance_category": {"primary": rng.choice(
                                    ["FOOD_AND_DRINK", "GENERAL_MERCHANDISE", "TRAVEL", "TRANSFER_OUT"])},
                                "location": {"city": secrets.token_hex(4)},
                                "payment_meta": {"reference_number": secrets.token_hex(8)}}})
        normalized.append({"transaction_id": tid, "account_id": account, "transaction_date": day,
                           "amount": amount, "description": merchant,
                           "transaction_type": "expense" if amount < 0 else "refund",
                           "is_spending": amount < 0})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await session.execute(insert(Item), items)
        await session.execute(insert(Account), accounts)
        session.add(StatementImportBatch(batch_id="batch-1", user_id=USER, item_id="item-0",
                                         account_id="account-0-0", adapter="synthetic", adapter_version="1",
                                         file_sha256=secrets.token_hex(32), preview_digest=secrets.token_hex(32),
                                         manifest={"rows": 1}, status="applied", applied_by="drill"))
        await session.flush()
        session.add(StatementImportRow(row_id="srow-1", batch_id="batch-1", source_record=1,
                                       source_line_end=1, fingerprint=secrets.token_hex(16),
                                       disposition="new", canonical={"amount": "-12.34"},
                                       source_evidence={"line": "synthetic statement line"}))
        await session.flush()
        for start in range(0, len(raw), 1000):
            await session.execute(insert(RawTransaction), raw[start:start + 1000])
            await session.execute(insert(Transaction), normalized[start:start + 1000])
        session.add(RawTransaction(transaction_id="stmt-1", item_id="item-0", account_id="account-0-0",
                                   transaction_date=date(2026, 8, 1), payload={"statement": True},
                                   source="statement", statement_row_id="srow-1"))
        session.add(Transaction(transaction_id="stmt-1", account_id="account-0-0",
                                transaction_date=date(2026, 8, 1), amount=-12.34, description="Statement",
                                statement_kind="Purchase", transaction_type="expense", is_spending=True))
        await session.flush()
        first, second = normalized[1]["transaction_id"], normalized[2]["transaction_id"]
        archived = TransactionLabelDefinition(label_id="fixture-archived", user_id=USER,
            name="Old gear", normalized_name="old gear", is_system=False,
            created_by="drill", updated_by="drill")
        session.add_all([
            TransactionLabelDefinition(label_id="fixture-tech", user_id=USER,
                name="Tech", normalized_name="tech", color="success", is_system=False,
                created_by="drill", updated_by="drill"), archived,
        ])
        await session.flush()
        session.add_all([
            ManualCategoryOverride(transaction_id=first, category="GENERAL_MERCHANDISE",
                                   created_by="drill", updated_by="drill"),
            ManualClassificationOverride(transaction_id=first, transaction_type="expense",
                                         created_by="drill", updated_by="drill"),
            ManualTransactionLabelOverride(transaction_id=second, label="MEMBERSHIP", decision="include",
                                           created_by="drill", updated_by="drill"),
            ManualBenefitCategoryOverride(transaction_id=second, benefit_category="DINING_CREDIT",
                                          created_by="drill", updated_by="drill"),
            ManualTransactionLabelOverride(transaction_id=first, label="fixture-tech", decision="include",
                                           created_by="drill", updated_by="drill"),
            ManualTransactionLabelOverride(transaction_id=second, label="fixture-tech", decision="include",
                                           created_by="drill", updated_by="drill"),
            ManualTransactionLabelOverride(transaction_id=second, label="fixture-archived", decision="include",
                                           created_by="drill", updated_by="drill"),
            ManualTransactionLabelOverride(transaction_id=first, label="fixture-archived", decision=None,
                                           cleared_at=now.replace(tzinfo=None), created_by="drill", updated_by="drill"),
            LegacyConsumerRow(transaction_id="legacy-1", item_id="item-0", account_id="account-0-0"),
            SyncRun(run_id="run-1", user_id=USER, trigger_source="jobs", started_at=now,
                    finished_at=now, status="success", published_at=now),
        ])
        await session.flush()
        # Establish history while active, then archive without deleting links.
        archived.archived_at = now.replace(tzinfo=None)
        session.add_all([SyncItemRun(run_id="run-1", item_id=f"item-{i}", started_at=now, finished_at=now,
                                     status="success", phase="published") for i in range(5)])
        session.add(SyncRuntimeState(user_id=USER, last_published_run_id="run-1", published_at=now,
                                     requested_sequence=3, handled_sequence=3, last_backup_at=now))
    return {"raw": len(raw) + 1, "normalized": len(normalized) + 1}
