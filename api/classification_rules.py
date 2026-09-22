"""Pure consumer transaction classification rules."""

from decimal import Decimal
from difflib import SequenceMatcher
from dataclasses import dataclass
import re

from api.card_benefits import CARD_BENEFIT_DESCRIPTIONS, normalized_benefit_text
from api.classification import INTERNAL_TRANSFER_TYPES
from api.statement_semantics import statement_classification


@dataclass(frozen=True)
class ClassificationCandidate:
    transaction_id: str
    item_id: str
    account_id: str
    transaction_date: object
    amount: Decimal
    merchant_name: str | None
    description: str | None
    plaid_category: str | None
    statement_kind: str | None


SPENDING_CATEGORIES = {
    "BANK_FEES",
    "ENTERTAINMENT",
    "FOOD_AND_DRINK",
    "GENERAL_MERCHANDISE",
    "GENERAL_SERVICES",
    "GOVERNMENT_AND_NON_PROFIT",
    "HOME_IMPROVEMENT",
    "MEDICAL",
    "PERSONAL_CARE",
    "RENT_AND_UTILITIES",
    "TRANSPORTATION",
    "TRAVEL",
}
CREDIT_CARD_PAYMENT_DESCRIPTIONS = {
    "PAYMENT THANK YOU MOBILE",
}

def classify_transaction(
    transaction,
    credit_account_ids=frozenset(),
    amex_benefit_account_ids=frozenset(),
    amex_merchant_benefit_account_ids=None,
):
    seed = statement_classification(getattr(transaction, "statement_kind", None), transaction.amount)
    if seed is not None:
        return seed
    category = transaction.plaid_category
    amount = transaction.amount
    description = (transaction.description or "").upper()

    if amount > 0 and re.search(
        r"\b(?:INTRST\s+PYMNT|INTEREST\s+(?:PAYMENT|PAID|EARNED|CREDIT))\b",
        description,
    ):
        return "income", False, False
    if category == "LOAN_PAYMENTS":
        return "payment", False, None
    if (
        amount > 0
        and transaction.account_id in credit_account_ids
        and category == "LOAN_DISBURSEMENTS"
        and _normalized_match_text(description) in CREDIT_CARD_PAYMENT_DESCRIPTIONS
    ):
        return "payment", False, None
    normalized_description = _normalized_match_text(description)
    merchant_benefit_account_ids = (
        amex_merchant_benefit_account_ids or {}
    ).get(normalized_description, frozenset())
    if (
        amount > 0
        and transaction.account_id in amex_benefit_account_ids
        and (
            normalized_description in CARD_BENEFIT_DESCRIPTIONS
            or (normalized_description == "WALMART"
                and amount == Decimal("13.81")
                and transaction.account_id in merchant_benefit_account_ids)
            or (normalized_description != "WALMART"
                and transaction.account_id in merchant_benefit_account_ids)
        )
    ):
        return "card_benefit", False, False
    if category in {"TRANSFER_IN", "TRANSFER_OUT"}:
        return "transfer", False, None
    if amount < 0 and category in SPENDING_CATEGORIES:
        return "expense", True, False
    if amount > 0 and (
        category == "INCOME"
    ):
        return "income", False, False
    return None, None, None

def _normalized_match_text(value):
    return normalized_benefit_text(value)

def _is_same_merchant_or_description(expense, credit):
    expense_merchant = _normalized_match_text(expense.merchant_name)
    credit_merchant = _normalized_match_text(credit.merchant_name)
    if expense_merchant and credit_merchant:
        return expense_merchant == credit_merchant

    expense_description = _normalized_match_text(expense.description)
    credit_description = _normalized_match_text(credit.description)
    if len(expense_description) < 5 or len(credit_description) < 5:
        return False
    return SequenceMatcher(
        None,
        expense_description,
        credit_description,
    ).ratio() >= 0.9

def _has_exact_merchant_or_description(expense, credit):
    expense_merchant = _normalized_match_text(expense.merchant_name)
    credit_merchant = _normalized_match_text(credit.merchant_name)
    expense_description = _normalized_match_text(expense.description)
    credit_description = _normalized_match_text(credit.description)
    return bool(
        (expense_merchant and expense_merchant == credit_merchant)
        or (
            expense_description
            and expense_description == credit_description
        )
    )


ZELLE_CONFIRMATION_PATTERNS = (
    re.compile(r"\bCONF(?:IRMATION)?\s*#?\s*([A-Z0-9]{8,16})\b", re.IGNORECASE),
    re.compile(r"\b(?:BAC|JPM)([A-Z0-9]{8,16})\b", re.IGNORECASE),
)


def zelle_confirmation_code(description):
    """Return one exact bank confirmation code from a Zelle description."""
    value = description or ""
    if re.search(r"\bZELLE\s+PAYMENT\b", value, re.IGNORECASE) is None:
        return None
    codes = {
        match.group(1).upper()
        for pattern in ZELLE_CONFIRMATION_PATTERNS
        for match in pattern.finditer(value)
    }
    return codes.pop() if len(codes) == 1 else None


def build_classifications(
    transactions,
    credit_account_ids=frozenset(),
    amex_benefit_account_ids=frozenset(),
    amex_merchant_benefit_account_ids=None,
    active_manual_types=None,
):
    active_manual_types = active_manual_types or {}
    classifications = {
        transaction.transaction_id: classify_transaction(
            transaction,
            credit_account_ids,
            amex_benefit_account_ids,
            amex_merchant_benefit_account_ids,
        )
        for transaction in transactions
    }
    expenses = [
        transaction
        for transaction in transactions
        if classifications[transaction.transaction_id][0] == "expense"
    ]
    refund_matches = 0

    for credit in transactions:
        if credit.amount <= 0 or classifications[credit.transaction_id][0] is not None:
            continue
        same_day_candidates = [
            expense
            for expense in expenses
            if expense.account_id == credit.account_id
            and expense.transaction_date == credit.transaction_date
            and abs(expense.amount) == credit.amount
            and expense.plaid_category == credit.plaid_category
            and _has_exact_merchant_or_description(expense, credit)
        ]
        if len(same_day_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1
            continue

        historical_candidates = [
            expense
            for expense in expenses
            if expense.account_id == credit.account_id
            and expense.transaction_date < credit.transaction_date
            and abs(expense.amount) == credit.amount
            and _is_same_merchant_or_description(expense, credit)
        ]
        if len(historical_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1
            continue

        recent_exact_candidates = [
            expense
            for expense in historical_candidates
            if (credit.transaction_date - expense.transaction_date).days <= 7
            and _normalized_match_text(expense.description)
            == _normalized_match_text(credit.description)
        ]
        if len(recent_exact_candidates) == 1:
            classifications[credit.transaction_id] = ("refund", False, False)
            refund_matches += 1

    confirmation_groups = {}
    for transaction in transactions:
        code = zelle_confirmation_code(transaction.description)
        if code is not None:
            confirmation_groups.setdefault(code, []).append(transaction)

    confirmation_matched = set()
    confirmation_blocked = set()
    for matches in confirmation_groups.values():
        if len(matches) != 2:
            if len(matches) > 1:
                confirmation_blocked.update(
                    transaction.transaction_id for transaction in matches
                )
            continue
        first, second = matches
        transaction_ids = {first.transaction_id, second.transaction_id}
        manual_types = {
            active_manual_types.get(first.transaction_id),
            active_manual_types.get(second.transaction_id),
        }
        has_conflicting_manual_type = any(
            manual_type is not None and manual_type not in INTERNAL_TRANSFER_TYPES
            for manual_type in manual_types
        )
        if (
            has_conflicting_manual_type
            or first.account_id == second.account_id
            or first.amount != -second.amount
            or first.amount == 0
        ):
            confirmation_blocked.update(transaction_ids)
            continue
        for matched_transaction in matches:
            transaction_type = classifications[matched_transaction.transaction_id][0]
            if transaction_type not in INTERNAL_TRANSFER_TYPES:
                transaction_type = "transfer"
            classifications[matched_transaction.transaction_id] = (
                transaction_type,
                False,
                True,
            )
        confirmation_matched.update(transaction_ids)

    transfer_candidates = {
        transaction.transaction_id: []
        for transaction in transactions
        if transaction.transaction_id not in confirmation_matched
        and transaction.transaction_id not in confirmation_blocked
        if classifications[transaction.transaction_id][0] in INTERNAL_TRANSFER_TYPES
        and (active_manual_types.get(transaction.transaction_id) is None
             or active_manual_types[transaction.transaction_id] in INTERNAL_TRANSFER_TYPES)
    }
    eligible_transfers = [
        transaction
        for transaction in transactions
        if transaction.transaction_id in transfer_candidates
    ]
    for index, transaction in enumerate(eligible_transfers):
        for counterpart in eligible_transfers[index + 1:]:
            if (
                transaction.account_id != counterpart.account_id
                and transaction.amount == -counterpart.amount
                and transaction.amount != 0
                and abs(
                    (transaction.transaction_date - counterpart.transaction_date).days
                ) <= 3
            ):
                transfer_candidates[transaction.transaction_id].append(counterpart)
                transfer_candidates[counterpart.transaction_id].append(transaction)

    for transaction in eligible_transfers:
        candidates = transfer_candidates[transaction.transaction_id]
        if len(candidates) != 1:
            continue
        counterpart = candidates[0]
        if len(transfer_candidates[counterpart.transaction_id]) != 1:
            continue
        for matched_transaction in (transaction, counterpart):
            transaction_type = classifications[matched_transaction.transaction_id][0]
            classifications[matched_transaction.transaction_id] = (
                transaction_type,
                False,
                True,
            )

    return classifications, refund_matches
