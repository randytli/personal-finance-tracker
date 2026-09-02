from decimal import Decimal


ALLOWED_TRANSACTION_TYPES = frozenset(
    {
        "expense",
        "refund",
        "income",
        "card_benefit",
        "payment",
        "transfer",
        "adjustment",
    }
)
POSITIVE_ONLY_TYPES = frozenset({"refund", "income", "card_benefit"})
INTERNAL_TRANSFER_TYPES = frozenset({"payment", "transfer"})


def effective_classification(transaction, override_type=None):
    transaction_type = override_type or transaction.transaction_type
    if override_type is None:
        is_spending = transaction.is_spending
    else:
        is_spending = override_type == "expense"
    return transaction_type, is_spending, getattr(transaction, "is_internal_transfer", None)


def validate_manual_override(transaction, transaction_type):
    if transaction_type not in ALLOWED_TRANSACTION_TYPES:
        return "unsupported transaction type"
    amount = Decimal(transaction.amount)
    if transaction_type == "expense" and amount >= 0:
        return "expense requires a negative amount"
    if transaction_type in POSITIVE_ONLY_TYPES and amount <= 0:
        return f"{transaction_type} requires a positive amount"
    if transaction.is_internal_transfer is True and transaction_type not in INTERNAL_TRANSFER_TYPES:
        return "internal transfers may only be classified as payment or transfer"
    return None
