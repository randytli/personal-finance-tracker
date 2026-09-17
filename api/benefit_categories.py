"""Independent categories for positive card-benefit credits."""
from decimal import Decimal
import re

BENEFIT_CATEGORIES = (
    "DINING_CREDIT",
    "TRAVEL_CREDIT",
    "SHOPPING_CREDIT",
    "TRANSPORTATION_CREDIT",
    "DIGITAL_ENTERTAINMENT_CREDIT",
    "ENTERTAINMENT_CREDIT",
    "GENERAL_SERVICES_CREDIT",
    "UNCATEGORIZED",
)
BENEFIT_CATEGORY_LABELS = {
    "DINING_CREDIT": "Dining",
    "TRAVEL_CREDIT": "Travel",
    "SHOPPING_CREDIT": "Shopping",
    "TRANSPORTATION_CREDIT": "Transportation",
    "DIGITAL_ENTERTAINMENT_CREDIT": "Digital entertainment",
    "ENTERTAINMENT_CREDIT": "Entertainment",
    "GENERAL_SERVICES_CREDIT": "General Services",
    "UNCATEGORIZED": "Uncategorized",
}
BENEFIT_CATEGORY_CHECK = "benefit_category IS NULL OR benefit_category IN (" + ",".join(
    repr(value) for value in BENEFIT_CATEGORIES
) + ")"


def normalize_benefit_description(value):
    return " ".join(re.findall(r"[A-Z0-9]+", value or "", flags=re.IGNORECASE)).upper()


def automatic_benefit_category(transaction, *, institution_id=None, account_name=None,
                               account_type=None, transaction_type=None):
    kind = transaction_type or (getattr(transaction, "transaction_type", None) if not isinstance(transaction, dict) else transaction.get("transaction_type"))
    amount = Decimal(str(getattr(transaction, "amount", 0) if not isinstance(transaction, dict) else transaction.get("amount", 0)))
    if kind != "card_benefit" or amount <= 0:
        return None
    description = normalize_benefit_description(
        getattr(transaction, "description", None) if not isinstance(transaction, dict) else transaction.get("description")
    )
    account = normalize_benefit_description(account_name)
    if description in {"AMEX DINING CREDIT", "AMEX RESY CREDIT", "PLATINUM RESY CREDIT", "DUNKIN DONUTS"}:
        return "DINING_CREDIT"
    if description in {"AMEX AIRLINE FEE REIMBURSEMENT", "PLATINUM HOTEL CREDIT"}:
        return "TRAVEL_CREDIT"
    if description in {"PLATINUM LULULEMON CREDIT", "PLATINUM SAKS CREDIT"}:
        return "SHOPPING_CREDIT"
    if description == "WALMART" and institution_id == "ins_10" and account_type == "credit" and account == "PLATINUM CARD" and amount == Decimal("13.81"):
        return "SHOPPING_CREDIT"
    if description == "PLATINUM UBER ONE CREDIT":
        return "TRANSPORTATION_CREDIT"
    if description == "PLATINUM DIGITAL ENTERTAINMENT CREDIT":
        return "DIGITAL_ENTERTAINMENT_CREDIT"
    if description in {"TODAYTIX INC", "APLPAY TODAYTIX INCNEW"}:
        return "ENTERTAINMENT_CREDIT"
    if description in {"INTUIT ORDER CHANNELSAN DIEGO"}:
        return "GENERAL_SERVICES_CREDIT"
    if description == "PEACOCK TV LLC UNIVERSAL CITY" and institution_id == "ins_10" and account == "AMERICAN EXPRESS GOLD CARD":
        return "DIGITAL_ENTERTAINMENT_CREDIT"
    return "UNCATEGORIZED"


def active_benefit_category(override):
    return override.benefit_category if override is not None and override.cleared_at is None else None


def effective_benefit_category(transaction, override=None, **context):
    return active_benefit_category(override) or automatic_benefit_category(transaction, **context)
