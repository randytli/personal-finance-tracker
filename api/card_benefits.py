"""Reviewed American Express card-benefit evidence shared with labels."""
import re
from decimal import Decimal


AMERICAN_EXPRESS_INSTITUTION_ID = "ins_10"
CARD_BENEFIT_DESCRIPTIONS = frozenset({
    "AMEX LULULEMON CREDIT", "AMEX RESY CREDIT",
    "AMEX AIRLINE FEE REIMBURSEMENT", "AMEX DINING CREDIT",
    "PLATINUM DIGITAL ENTERTAINMENT CREDIT", "PLATINUM HOTEL CREDIT",
    "PLATINUM LULULEMON CREDIT", "PLATINUM RESY CREDIT",
    "PLATINUM SAKS CREDIT", "PLATINUM UBER ONE CREDIT",
})
MEMBERSHIP_BENEFIT_DESCRIPTIONS = frozenset({
    "PLATINUM DIGITAL ENTERTAINMENT CREDIT",
    "PLATINUM UBER ONE CREDIT",
})
AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES = {
    "DUNKIN DONUTS": "AMERICAN EXPRESS GOLD CARD",
    "WALMART": "PLATINUM CARD",
}


def normalized_benefit_text(value):
    return " ".join(re.findall(r"[A-Z0-9]+", (value or "").upper()))


def confirmed_amex_benefit(description, amount, *, institution_id, account_type,
                           account_name):
    """Require authoritative Item/account membership and reviewed evidence."""
    if (institution_id != AMERICAN_EXPRESS_INSTITUTION_ID
            or account_type != "credit" or not account_name
            or Decimal(str(amount)) <= 0):
        return False
    description = normalized_benefit_text(description)
    return (description in CARD_BENEFIT_DESCRIPTIONS
            or normalized_benefit_text(account_name)
            == AMEX_MERCHANT_BENEFIT_ACCOUNT_NAMES.get(description))


def membership_benefit(description, amount, *, institution_id, account_type,
                       account_name):
    description = normalized_benefit_text(description)
    return (description in MEMBERSHIP_BENEFIT_DESCRIPTIONS
            and confirmed_amex_benefit(description, amount,
                institution_id=institution_id, account_type=account_type,
                account_name=account_name)
            and normalized_benefit_text(account_name) == "PLATINUM CARD") or (
        description == "WALMART"
        and normalized_benefit_text(account_name) == "PLATINUM CARD"
        and institution_id == AMERICAN_EXPRESS_INSTITUTION_ID
        and account_type == "credit"
        and Decimal(str(amount)) == Decimal("13.81")
    )
