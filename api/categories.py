from decimal import Decimal
import re

from api.classification import effective_classification

MANUAL_CATEGORIES = (
    'BANK_FEES', 'ENTERTAINMENT', 'FOOD_AND_DRINK', 'GENERAL_MERCHANDISE',
    'GENERAL_SERVICES', 'GOVERNMENT_AND_NON_PROFIT', 'GROCERIES', 'HOME_IMPROVEMENT',
    'MEDICAL', 'PERSONAL_CARE', 'RENT_AND_UTILITIES', 'TRANSPORTATION', 'TRAVEL',
    'UNCATEGORIZED',
)
CATEGORY_CHECK = 'category IS NULL OR category IN (' + ','.join(
    "'" + category + "'" for category in MANUAL_CATEGORIES
) + ')'

# Exact normalized merchant-name rules only. Normalization removes punctuation and
# collapses whitespace; it never performs substring, fuzzy, or description matching.
MERCHANT_CATEGORY_RULES = {
    'WEEE': 'GROCERIES',
    'AMAP TAXI': 'TRANSPORTATION',
    'ALIPAY AMAP TAXI': 'TRANSPORTATION',
    'NANJING METRO': 'TRANSPORTATION',
    'ALIPAY NANJING METRO': 'TRANSPORTATION',
    'UBER': 'TRANSPORTATION',
    'TFL': 'TRANSPORTATION',
    'UBER EATS': 'FOOD_AND_DRINK',
    'WEIXIN ZHEJIANG GUMING': 'FOOD_AND_DRINK',
    'WEIXIN A RICE NOODLE S': 'FOOD_AND_DRINK',
    'OPENAI': 'GENERAL_SERVICES',
    'ANTHROPIC': 'GENERAL_SERVICES',
    'CLAUDE AI SUBSCRIPTION': 'GENERAL_SERVICES',
    'UPS': 'GENERAL_SERVICES',
    'VERIZON': 'RENT_AND_UTILITIES',
    'PSE G': 'RENT_AND_UTILITIES',
    'AMAZON': 'GENERAL_MERCHANDISE',
    'WALMART': 'GENERAL_MERCHANDISE',
    'WEIXIN PANDUO PLATFO': 'GENERAL_MERCHANDISE',
    'WEIXIN JINGDONG MALL': 'GENERAL_MERCHANDISE',
    'TAOBAO': 'GENERAL_MERCHANDISE',
    'GU USA LLC': 'GENERAL_MERCHANDISE',
    'GLOBAL E ARSENAL': 'GENERAL_MERCHANDISE',
}


def normalize_merchant_name(value):
    return ' '.join(re.findall(r'[A-Z0-9]+', value or '', flags=re.IGNORECASE)).upper()


def automatic_category(transaction):
    merchant = normalize_merchant_name(getattr(transaction, 'merchant_name', None))
    return MERCHANT_CATEGORY_RULES.get(merchant)


def active_category(override):
    return override.category if override is not None and override.cleared_at is None else None


def effective_category(transaction, override=None):
    return (active_category(override) or automatic_category(transaction)
            or transaction.plaid_category or 'UNCATEGORIZED')


def category_editable(transaction, classification_override=None):
    kind, spending, internal = effective_classification(transaction, classification_override)
    amount = Decimal(transaction.amount)
    return internal is not True and (
        (kind == 'expense' and spending is True and amount < 0)
        or (kind == 'refund' and amount > 0)
    )
