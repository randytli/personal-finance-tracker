"""Derived canonical spending attribution; never changes source classifications."""
from decimal import Decimal

from api.benefit_categories import active_benefit_category, automatic_benefit_category
from api.categories import MANUAL_CATEGORIES, active_category, automatic_category, source_spending_category
from api.classification import effective_classification


BENEFIT_TO_SPENDING = {
    "DINING_CREDIT": "DINING",
    "TRAVEL_CREDIT": "TRAVEL",
    "SHOPPING_CREDIT": "GENERAL_MERCHANDISE",
    "TRANSPORTATION_CREDIT": "TRANSPORTATION",
    "DIGITAL_ENTERTAINMENT_CREDIT": "ENTERTAINMENT",
    "ENTERTAINMENT_CREDIT": "ENTERTAINMENT",
    "GENERAL_SERVICES_CREDIT": "GENERAL_SERVICES",
    "UNCATEGORIZED": "UNCATEGORIZED",
}


def contribution(transaction, classification_override=None, category_override=None,
                 benefit_override=None, *, item=None, account=None):
    """Return one eligible component and signed net amount, or None."""
    kind, spending, internal = effective_classification(transaction, classification_override)
    amount = Decimal(transaction.amount)
    if internal is True:
        return None
    if kind == "expense" and spending is True and amount < 0:
        component, magnitude, sign = "gross", -amount, 1
    elif kind == "refund" and amount > 0:
        component, magnitude, sign = "refunds", amount, -1
    elif kind == "reimbursement" and amount > 0:
        component, magnitude, sign = "reimbursements", amount, -1
    elif kind == "card_benefit" and amount > 0:
        component, magnitude, sign = "card_benefits", amount, -1
    else:
        return None

    if component == "card_benefits":
        manual = active_benefit_category(benefit_override)
        benefit = manual or automatic_benefit_category(
            transaction, institution_id=getattr(item, "institution_id", None),
            account_name=getattr(account, "name", None),
            account_type=getattr(account, "type", None), transaction_type=kind)
        category = BENEFIT_TO_SPENDING.get(benefit, "UNCATEGORIZED")
        source = "manual_benefit" if manual else "automatic_benefit"
    else:
        manual = active_category(category_override)
        if component == "reimbursements":
            category = manual or "UNCATEGORIZED"
            source = "manual_spending" if manual else "uncategorized"
        else:
            automatic = automatic_category(transaction) if not manual else None
            plaid = getattr(transaction, "plaid_category", None)
            category = manual or automatic or source_spending_category(plaid) or "UNCATEGORIZED"
            source = ("manual_spending" if manual else "merchant_rule" if automatic
                      else "plaid" if plaid else "uncategorized")
        if category not in MANUAL_CATEGORIES:
            category, source = "UNCATEGORIZED", "unsupported_source"
    return {"canonical_category": category, "attribution_source": source,
            "component": component, "magnitude": magnitude,
            "net_contribution": magnitude * sign}
