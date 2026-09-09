from decimal import Decimal

from api.classification import effective_classification

MANUAL_CATEGORIES = (
    'BANK_FEES', 'ENTERTAINMENT', 'FOOD_AND_DRINK', 'GENERAL_MERCHANDISE',
    'GENERAL_SERVICES', 'GOVERNMENT_AND_NON_PROFIT', 'HOME_IMPROVEMENT',
    'MEDICAL', 'PERSONAL_CARE', 'RENT_AND_UTILITIES', 'TRANSPORTATION', 'TRAVEL',
)
CATEGORY_CHECK = 'category IS NULL OR category IN (' + ','.join(
    "'" + category + "'" for category in MANUAL_CATEGORIES
) + ')'


def active_category(override):
    return override.category if override is not None and override.cleared_at is None else None


def effective_category(transaction, override=None):
    return active_category(override) or transaction.plaid_category or 'UNCATEGORIZED'


def category_editable(transaction, classification_override=None):
    kind, spending, internal = effective_classification(transaction, classification_override)
    amount = Decimal(transaction.amount)
    return internal is not True and (
        (kind == 'expense' and spending is True and amount < 0)
        or (kind == 'refund' and amount > 0)
    )
