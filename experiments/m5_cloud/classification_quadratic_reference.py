"""R13 reference: the pre-2026-10-09 quadratic build_classifications, unchanged.

Test-only. tests/test_m5_classification_bucketed.py checks that the bucketed
application function returns exactly what this original returns.
"""
from api.classification import INTERNAL_TRANSFER_TYPES
from api.classification_rules import (
    _has_exact_merchant_or_description,
    _is_same_merchant_or_description,
    _normalized_match_text,
    classify_transaction,
    zelle_confirmation_code,
)


def build_classifications_quadratic(
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
