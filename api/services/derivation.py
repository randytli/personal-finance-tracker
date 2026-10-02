"""Consumer derivation using a caller-owned transaction and session."""

from fastapi import HTTPException
from decimal import Decimal, InvalidOperation
from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm.attributes import set_committed_value

from api.card_benefits import AMERICAN_EXPRESS_INSTITUTION_ID, AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES
from api.classification_rules import (
    ClassificationCandidate, build_classifications, _normalized_match_text,
)
from api.models import Account, Item, LegacyConsumerRow, ManualClassificationOverride, RawTransaction, Transaction
from api.statement_semantics import lock_consumer_derivation, normalized_raw_values


class NormalizationInputError(ValueError):
    """Invalid stored source evidence; safe to isolate at the Item savepoint."""


def validate_normalization_input(raw):
    payload = raw.payload
    if not isinstance(payload, dict) or "amount" not in payload:
        raise NormalizationInputError("Missing source amount")
    try:
        amount = Decimal(str(payload["amount"]))
    except (InvalidOperation, ValueError):
        raise NormalizationInputError("Invalid source amount") from None
    if not amount.is_finite():
        raise NormalizationInputError("Non-finite source amount")
    if raw.source == "statement" and "kind" not in payload:
        raise NormalizationInputError("Missing statement kind")
    category = payload.get("personal_finance_category")
    if raw.source == "plaid" and category is not None and not isinstance(category, dict):
        raise NormalizationInputError("Invalid source category")


async def normalize_item_transactions(db, user_id, item_id, *, statuses):
    await lock_consumer_derivation(db, user_id)
    item = await db.scalar(select(Item).where(
        Item.item_id == item_id, Item.user_id == user_id, Item.status.in_(statuses),
    ).with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.execute(select(Account).where(Account.item_id == item_id)
                     .order_by(Account.account_id).with_for_update())
    result = await db.execute(
        select(RawTransaction, Transaction).join(Account,
            (Account.account_id == RawTransaction.account_id)
            & (Account.item_id == RawTransaction.item_id))
        .outerjoin(Transaction, Transaction.transaction_id == RawTransaction.transaction_id)
        .where(
            RawTransaction.item_id == item.item_id,
            RawTransaction.is_removed.is_(False),
            Account.consumer_transactions_enabled.is_(True),
        ).execution_options(populate_existing=True)
    )
    rows = result.all()
    changed = []
    # Every eligible row is still validated, and missing normalized rows are restored.
    for raw_transaction, normalized in rows:
        validate_normalization_input(raw_transaction)
        values = {
            "transaction_id": raw_transaction.transaction_id,
            "account_id": raw_transaction.account_id,
            "transaction_date": raw_transaction.transaction_date,
            **normalized_raw_values(raw_transaction),
        }
        if normalized is None or _normalized_differs(normalized, values):
            changed.append((normalized, values))
    await _write_normalized(db, changed)
    return {"normalized_count": len(rows)}


NORMALIZED_FIELDS = ("account_id", "transaction_date", "amount", "merchant_name",
                     "description", "plaid_category", "statement_kind")


def _normalized_differs(row, values):
    # Numeric keeps the payload's scale (-30 vs -30.0), so compare it exactly.
    if (row.amount != values["amount"]
            or row.amount.as_tuple().exponent != values["amount"].as_tuple().exponent):
        return True
    return any(getattr(row, name) != values[name] for name in NORMALIZED_FIELDS if name != "amount")


async def _write_normalized(db, changed):
    """Upsert only missing or different rows, as one statement however many changed.

    INSERT ... SELECT FROM unnest keeps the round trips constant; executemany is
    avoided because its round trips depend on driver batching. New rows start
    unclassified, as before, and classification stays untouched on update.
    """
    if not changed:
        return
    await db.execute(text(
        "INSERT INTO transactions (transaction_id, account_id, transaction_date, amount, "
        "merchant_name, description, plaid_category, statement_kind) "
        "SELECT * FROM unnest(CAST(:transaction_id AS VARCHAR[]), CAST(:account_id AS VARCHAR[]), "
        "CAST(:transaction_date AS DATE[]), CAST(:amount AS NUMERIC[]), "
        "CAST(:merchant_name AS VARCHAR[]), CAST(:description AS VARCHAR[]), "
        "CAST(:plaid_category AS VARCHAR[]), CAST(:statement_kind AS VARCHAR[])) "
        "ON CONFLICT (transaction_id) DO UPDATE SET account_id = excluded.account_id, "
        "transaction_date = excluded.transaction_date, amount = excluded.amount, "
        "merchant_name = excluded.merchant_name, description = excluded.description, "
        "plaid_category = excluded.plaid_category, statement_kind = excluded.statement_kind, "
        "updated_at = now()"
    ), {name: [values[name] for _, values in changed]
        for name in ("transaction_id", *NORMALIZED_FIELDS)})
    # Keep loaded rows consistent with the database, as classification reads them next.
    for row, values in changed:
        if row is not None:
            for name in NORMALIZED_FIELDS:
                set_committed_value(row, name, values[name])


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
        .execution_options(populate_existing=True)
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
    stored_rows = {transaction.transaction_id: transaction for transaction, _, _ in classified_rows}
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
            amex_merchant_benefit_account_ids, active_manual_types, stored_rows)


async def _write_classifications(db, changed):
    """Write only changed results, as one statement however many rows changed.

    Matching needs the full history, so every row is still recomputed, but a
    no-op sync then writes nothing. UPDATE ... FROM unnest keeps the round trips
    constant; executemany is avoided because its round trips depend on driver
    batching. The derivation advisory lock already serializes these writers.
    """
    if not changed:
        return
    await db.execute(text(
        "UPDATE transactions AS t SET transaction_type = v.transaction_type, "
        "is_spending = v.is_spending, is_internal_transfer = v.is_internal_transfer, "
        "updated_at = now() "
        "FROM unnest(CAST(:ids AS VARCHAR[]), CAST(:types AS VARCHAR[]), "
        "CAST(:spending AS BOOLEAN[]), CAST(:internal AS BOOLEAN[])) "
        "AS v(transaction_id, transaction_type, is_spending, is_internal_transfer) "
        "WHERE t.transaction_id = v.transaction_id"
    ), {
        "ids": [row.transaction_id for row, _ in changed],
        "types": [values[0] for _, values in changed],
        "spending": [values[1] for _, values in changed],
        "internal": [values[2] for _, values in changed],
    })
    # Keep loaded rows consistent with the database, as the ORM update did.
    for row, values in changed:
        for name, value in zip(("transaction_type", "is_spending", "is_internal_transfer"), values):
            set_committed_value(row, name, value)


async def classify_active_transactions(db, user_id):
    await lock_consumer_derivation(db, user_id)
    await db.execute(select(Item).where(Item.user_id == user_id, Item.published.is_(True))
                     .order_by(Item.item_id).with_for_update())
    await db.execute(select(Account).join(Item, Item.item_id == Account.item_id)
                     .where(Item.user_id == user_id, Item.published.is_(True),
                            Account.consumer_transactions_enabled.is_(True))
                     .order_by(Account.account_id).with_for_update(of=Account))
    # Deactivated Items stay published, so they keep feeding classification.
    inputs = await _classification_inputs(db, user_id, Item.published.is_(True))
    transactions, stored_rows = inputs[0], inputs[5]
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
    changed = []
    for transaction in sorted(transactions, key=lambda candidate: candidate.transaction_id):
        values = classifications[transaction.transaction_id]
        row = stored_rows[transaction.transaction_id]
        if (row.transaction_type, row.is_spending, row.is_internal_transfer) != values:
            changed.append((row, values))
        counts[values[0] or "unclassified"] += 1
    await _write_classifications(db, changed)

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
    scope = or_(Item.published.is_(True), and_(Item.status == "pending", Item.item_id == item_id))
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
        .order_by(Account.account_id).with_for_update().execution_options(populate_existing=True)
    )).scalars()}
    if not any(a.consumer_transactions_enabled for a in accounts.values()):
        raise HTTPException(409, "Discover at least one enabled consumer account before activation")
    rows = (await db.execute(
        select(RawTransaction, Transaction, LegacyConsumerRow)
        .outerjoin(Transaction, Transaction.transaction_id == RawTransaction.transaction_id)
        .outerjoin(LegacyConsumerRow, LegacyConsumerRow.transaction_id == RawTransaction.transaction_id)
        .where(RawTransaction.item_id == item_id)
        .execution_options(populate_existing=True)
    )).all()
    for raw, normalized, legacy in rows:
        account = accounts.get(raw.account_id)
        if account is None or (normalized and normalized.account_id != raw.account_id):
            raise HTTPException(409, "Consumer transaction account ownership is inconsistent")
        if not account.consumer_transactions_enabled:
            if (legacy is None or legacy.item_id != item_id or legacy.account_id != raw.account_id
                    or (normalized and legacy.normalized_account_id != normalized.account_id)):
                raise HTTPException(409, "New disabled-account consumer data requires investigation")
