"""Source-kind semantics shared by normalization and classifier reruns."""
from decimal import Decimal


async def lock_consumer_derivation(db, user_id):
    """Lock the user's derivation scope before any caller composes row writes.

    Classification can span every Item. Lock all owned Items, then Accounts,
    up front so activation and composed services never acquire a new Item lock
    after an Account or Transaction lock. Reacquisition in one transaction is safe.
    """
    from sqlalchemy import select, text
    from api.models import Account, Item
    # Do not flush caller-staged ORM changes before acquiring the guard.
    with db.no_autoflush:
        await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                         {"key": "pft-consumer-derivation:" + user_id})
        await db.execute(select(Item.item_id).where(Item.user_id == user_id)
                         .order_by(Item.item_id).with_for_update())
        await db.execute(select(Account.account_id).join(Item, Item.item_id == Account.item_id)
                         .where(Item.user_id == user_id).order_by(Account.account_id)
                         .with_for_update(of=Account))


def statement_classification(kind, amount):
    amount = Decimal(amount)
    if kind in {"purchase", "fee"} and amount < 0:
        return "expense", True, False
    if kind in {"refund", "payment"} and amount > 0:
        return kind, False, False
    return None


def normalized_raw_values(raw):
    payload = raw.payload
    if raw.source == "statement":
        return dict(amount=Decimal(payload["amount"]), merchant_name=payload.get("merchant"),
                    description=payload.get("description"), plaid_category=None,
                    statement_kind=payload["kind"])
    category = payload.get("personal_finance_category")
    return dict(amount=-Decimal(str(payload["amount"])), merchant_name=payload.get("merchant_name"),
                description=payload.get("name"), plaid_category=category.get("primary") if category else None,
                statement_kind=None)
