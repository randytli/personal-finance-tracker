"""Consumer derivation using a caller-owned transaction and session."""

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from api.card_benefits import AMERICAN_EXPRESS_INSTITUTION_ID, AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES
from api.models import Account, Item, ManualClassificationOverride, RawTransaction, Transaction
from api.statement_semantics import lock_consumer_derivation, normalized_raw_values


async def normalize_item_transactions(db, user_id, item_id):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("pending", "active")),
    ))
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    result = await db.execute(
        select(RawTransaction).join(Account,
            (Account.account_id == RawTransaction.account_id)
            & (Account.item_id == RawTransaction.item_id)).where(
            RawTransaction.item_id == item.item_id,
            RawTransaction.is_removed.is_(False),
            Account.consumer_transactions_enabled.is_(True),
        )
    )
    raw_transactions = result.scalars().all()
    for raw_transaction in raw_transactions:
        values = {
            "transaction_id": raw_transaction.transaction_id,
            "account_id": raw_transaction.account_id,
            "transaction_date": raw_transaction.transaction_date,
            **normalized_raw_values(raw_transaction),
            "transaction_type": None,
            "is_spending": None,
            "is_internal_transfer": None,
        }
        statement = insert(Transaction).values(**values)
        await db.execute(statement.on_conflict_do_update(
            index_elements=["transaction_id"],
            set_={
                "account_id": values["account_id"],
                "transaction_date": values["transaction_date"],
                "amount": values["amount"],
                "merchant_name": values["merchant_name"],
                "description": values["description"],
                "plaid_category": values["plaid_category"],
                "statement_kind": values["statement_kind"],
                "updated_at": func.now(),
            },
        ))
    return {"normalized_count": len(raw_transactions)}


async def classify_active_transactions(db, user_id):
    await lock_consumer_derivation(db, user_id)
    # The calculation remains in plaid.py until the M1C preview extraction.
    from api.routes.plaid import build_classifications, _normalized_match_text

    result = await db.execute(
        select(Transaction, ManualClassificationOverride.transaction_type)
        .join(RawTransaction, RawTransaction.transaction_id == Transaction.transaction_id)
        .join(Item, Item.item_id == RawTransaction.item_id)
        .join(Account, (Account.account_id == Transaction.account_id)
              & (Account.account_id == RawTransaction.account_id)
              & (Account.item_id == Item.item_id))
        .outerjoin(ManualClassificationOverride,
                   (ManualClassificationOverride.transaction_id == Transaction.transaction_id)
                   & ManualClassificationOverride.cleared_at.is_(None))
        .where(
            Account.consumer_transactions_enabled.is_(True),
            Item.user_id == user_id,
            Item.status == "active",
            RawTransaction.is_removed.is_(False),
        )
    )
    classified_rows = result.all()
    transactions = [transaction for transaction, _ in classified_rows]
    active_manual_types = {
        transaction.transaction_id: manual_type
        for transaction, manual_type in classified_rows if manual_type is not None
    }
    result = await db.execute(
        select(Account.account_id)
        .join(Item, Item.item_id == Account.item_id)
        .where(
            Account.type == "credit",
            Account.consumer_transactions_enabled.is_(True),
            Item.user_id == user_id,
            Item.status == "active",
        )
    )
    credit_account_ids = set(result.scalars().all())
    result = await db.execute(
        select(Account.account_id, Account.name)
        .join(Item, Item.item_id == Account.item_id)
        .where(
            Account.type == "credit",
            Account.consumer_transactions_enabled.is_(True),
            Item.institution_id == AMERICAN_EXPRESS_INSTITUTION_ID,
            Item.user_id == user_id,
            Item.status == "active",
        )
    )
    amex_credit_accounts = result.all()
    amex_benefit_account_ids = {
        account_id for account_id, _ in amex_credit_accounts
    }
    amex_merchant_benefit_account_ids = {
        description: {
            account_id
            for account_id, account_name in amex_credit_accounts
            if _normalized_match_text(account_name) == required_account_name
        }
        for description, required_account_name in (
            AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES.items()
        )
    }

    classifications, refund_matches = build_classifications(
        transactions,
        credit_account_ids,
        amex_benefit_account_ids,
        amex_merchant_benefit_account_ids,
        active_manual_types=active_manual_types,
    )
    internal_transfer_matches = sum(
        1 for values in classifications.values() if values[2] is True
    ) // 2
    counts = {
        "card_benefit": 0,
        "expense": 0,
        "income": 0,
        "payment": 0,
        "refund": 0,
        "transfer": 0,
        "unclassified": 0,
    }
    for transaction in transactions:
        transaction_type, is_spending, is_internal_transfer = (
            classifications[transaction.transaction_id]
        )
        await db.execute(
            update(Transaction)
            .where(Transaction.transaction_id == transaction.transaction_id)
            .values(
                transaction_type=transaction_type,
                is_spending=is_spending,
                is_internal_transfer=is_internal_transfer,
            )
        )
        counts[transaction_type or "unclassified"] += 1

    return {
        "classified_count": len(transactions) - counts["unclassified"],
        "refund_matches": refund_matches,
        "internal_transfer_matches": internal_transfer_matches,
        **counts,
    }
