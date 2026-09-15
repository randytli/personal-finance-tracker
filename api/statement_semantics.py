"""Source-kind semantics shared by normalization and classifier reruns."""
from decimal import Decimal


async def lock_consumer_derivation(db, user_id):
    """Serialize import/rollback against normalization and cross-account classification."""
    from sqlalchemy import text
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                     {"key": "pft-consumer-derivation:" + user_id})


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
