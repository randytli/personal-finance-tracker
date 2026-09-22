"""Consumer derivation using a caller-owned transaction and session."""

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert

from api.card_benefits import AMERICAN_EXPRESS_INSTITUTION_ID, AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES
from api.classification_rules import (
    ClassificationCandidate, build_classifications, _normalized_match_text,
)
from api.models import Account, Item, LegacyConsumerRow, ManualClassificationOverride, RawTransaction, Transaction
from api.statement_semantics import lock_consumer_derivation, normalized_raw_values


async def normalize_item_transactions(db, user_id, item_id):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("pending", "active")),
    ).with_for_update())
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.execute(select(Account).where(Account.item_id == item_id)
                     .order_by(Account.account_id).with_for_update())
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


async def _classification_inputs(db, user_id, item_scope):
    result = await db.execute(
        select(Transaction, Item.item_id, ManualClassificationOverride.transaction_type)
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
            item_scope,
            RawTransaction.is_removed.is_(False),
        )
    )
    classified_rows = result.all()
    transactions = [ClassificationCandidate(
        transaction_id=transaction.transaction_id,
        item_id=item_id,
        account_id=transaction.account_id,
        transaction_date=transaction.transaction_date,
        amount=transaction.amount,
        merchant_name=transaction.merchant_name,
        description=transaction.description,
        plaid_category=transaction.plaid_category,
        statement_kind=transaction.statement_kind,
    ) for transaction, item_id, _ in classified_rows]
    active_manual_types = {
        transaction.transaction_id: manual_type
        for transaction, _, manual_type in classified_rows if manual_type is not None
    }
    result = await db.execute(
        select(Account.account_id)
        .join(Item, Item.item_id == Account.item_id)
        .where(
            Account.type == "credit",
            Account.consumer_transactions_enabled.is_(True),
            Item.user_id == user_id,
            item_scope,
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
            item_scope,
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

    return (transactions, credit_account_ids, amex_benefit_account_ids,
            amex_merchant_benefit_account_ids, active_manual_types)


async def classify_active_transactions(db, user_id):
    await lock_consumer_derivation(db, user_id)
    await db.execute(select(Item).where(Item.user_id == user_id, Item.status == "active")
                     .order_by(Item.item_id).with_for_update())
    await db.execute(select(Account).join(Item, Item.item_id == Account.item_id)
                     .where(Item.user_id == user_id, Item.status == "active",
                            Account.consumer_transactions_enabled.is_(True))
                     .order_by(Account.account_id).with_for_update(of=Account))
    inputs = await _classification_inputs(db, user_id, Item.status == "active")
    transactions = inputs[0]
    classifications, refund_matches = build_classifications(
        *inputs[:4], active_manual_types=inputs[4],
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
    for transaction in sorted(transactions, key=lambda candidate: candidate.transaction_id):
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


async def preview_pending_classification(db, user_id, item_id):
    # This must be the first statement in the caller's transaction.
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id, Item.status == "pending",
    ))
    if item is None:
        raise HTTPException(404, "Pending Item not found")
    scope = or_(Item.status == "active", and_(Item.status == "pending", Item.item_id == item_id))
    inputs = await _classification_inputs(db, user_id, scope)
    classifications, _ = build_classifications(*inputs[:4], active_manual_types=inputs[4])
    return {
        "item_id": item_id,
        "status": "unpublished",
        "transactions": [
            {
                "transaction_id": candidate.transaction_id,
                "transaction_type": classifications[candidate.transaction_id][0],
                "is_spending": classifications[candidate.transaction_id][1],
                "is_internal_transfer": classifications[candidate.transaction_id][2],
                "status": "unpublished",
            }
            for candidate in inputs[0] if candidate.item_id == item_id
        ],
    }


async def validate_consumer_activation(db, item_id):
    accounts = {a.account_id: a for a in (await db.execute(
        select(Account).where(Account.item_id == item_id)
        .order_by(Account.account_id).with_for_update()
    )).scalars()}
    if not any(a.consumer_transactions_enabled for a in accounts.values()):
        raise HTTPException(409, "Discover at least one enabled consumer account before activation")
    rows = (await db.execute(
        select(RawTransaction, Transaction, LegacyConsumerRow)
        .outerjoin(Transaction, Transaction.transaction_id == RawTransaction.transaction_id)
        .outerjoin(LegacyConsumerRow, LegacyConsumerRow.transaction_id == RawTransaction.transaction_id)
        .where(RawTransaction.item_id == item_id)
    )).all()
    for raw, normalized, legacy in rows:
        account = accounts.get(raw.account_id)
        if account is None or (normalized and normalized.account_id != raw.account_id):
            raise HTTPException(409, "Consumer transaction account ownership is inconsistent")
        if not account.consumer_transactions_enabled:
            if (legacy is None or legacy.item_id != item_id or legacy.account_id != raw.account_id
                    or (normalized and legacy.normalized_account_id != normalized.account_id)):
                raise HTTPException(409, "New disabled-account consumer data requires investigation")


async def activate_item(db, user_id, item_id):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id,
        Item.status.in_(("pending", "active", "disabled")),
    ).with_for_update())
    if item is None:
        raise HTTPException(404, "Item not found")
    await validate_consumer_activation(db, item_id)
    await db.execute(update(Item).where(Item.item_id == item_id).values(status="active"))
    await classify_active_transactions(db, user_id)
    return {"item_id": item_id, "status": "active"}
