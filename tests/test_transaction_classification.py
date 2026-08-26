import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from api.routes.plaid import build_classifications


def united_transaction(transaction_id, day, amount):
    return SimpleNamespace(
        transaction_id=transaction_id,
        account_id="credit-card",
        transaction_date=date(2026, 1, day),
        amount=Decimal(amount),
        merchant_name="United Airlines",
        description="United Airlines",
        plaid_category="TRAVEL",
    )


class RefundClassificationTests(unittest.TestCase):
    def test_matching_airline_credit_is_refund(self):
        transactions = [
            united_transaction("expense", 1, "-500"),
            united_transaction("credit", 5, "500"),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["expense"][0], "expense")
        self.assertEqual(classifications["credit"], ("refund", False, False))
        self.assertEqual(refund_matches, 1)

    def test_multiple_matching_expenses_leave_credit_unclassified(self):
        transactions = [
            united_transaction("expense-1", 1, "-500"),
            united_transaction("expense-2", 2, "-500"),
            united_transaction("credit", 5, "500"),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["credit"], (None, None, None))
        self.assertEqual(refund_matches, 0)


def transfer_transaction(transaction_id, account_id, day, amount, category):
    return SimpleNamespace(
        transaction_id=transaction_id,
        account_id=account_id,
        transaction_date=date(2026, 1, day),
        amount=Decimal(amount),
        merchant_name=None,
        description="Account transfer",
        plaid_category=category,
    )


class InternalTransferClassificationTests(unittest.TestCase):
    def test_opposite_transfers_within_one_day_are_matched(self):
        transactions = [
            transfer_transaction("checking", "checking-account", 1, "-1000", "TRANSFER_OUT"),
            transfer_transaction("savings", "savings-account", 2, "1000", "TRANSFER_IN"),
        ]

        classifications, _ = build_classifications(transactions)

        self.assertEqual(classifications["checking"], ("transfer", False, True))
        self.assertEqual(classifications["savings"], ("transfer", False, True))

    def test_opposite_transfers_ten_days_apart_are_not_matched(self):
        transactions = [
            transfer_transaction("checking", "checking-account", 1, "-1000", "TRANSFER_OUT"),
            transfer_transaction("savings", "savings-account", 11, "1000", "TRANSFER_IN"),
        ]

        classifications, _ = build_classifications(transactions)

        self.assertEqual(classifications["checking"], ("transfer", False, None))
        self.assertEqual(classifications["savings"], ("transfer", False, None))

    def test_multiple_counterparts_are_left_ambiguous(self):
        transactions = [
            transfer_transaction("checking", "checking-account", 1, "-1000", "TRANSFER_OUT"),
            transfer_transaction("savings-1", "savings-account", 2, "1000", "TRANSFER_IN"),
            transfer_transaction("savings-2", "other-savings", 3, "1000", "TRANSFER_IN"),
        ]

        classifications, _ = build_classifications(transactions)

        self.assertIsNone(classifications["checking"][2])
        self.assertIsNone(classifications["savings-1"][2])
        self.assertIsNone(classifications["savings-2"][2])


class CardBenefitClassificationTests(unittest.TestCase):
    def card_benefit_transaction(self, description, amount="50", category="FOOD_AND_DRINK"):
        return SimpleNamespace(
            transaction_id="statement-credit",
            account_id="amex-card",
            transaction_date=date(2026, 1, 2),
            amount=Decimal(amount),
            merchant_name=None,
            description=description,
            plaid_category=category,
        )

    def test_partial_restaurant_credit_is_card_benefit(self):
        transactions = [
            SimpleNamespace(
                transaction_id="restaurant-expense",
                account_id="amex-card",
                transaction_date=date(2026, 1, 1),
                amount=Decimal("-100"),
                merchant_name="Restaurant",
                description="RESTAURANT PURCHASE",
                plaid_category="FOOD_AND_DRINK",
            ),
            SimpleNamespace(
                transaction_id="resy-credit",
                account_id="amex-card",
                transaction_date=date(2026, 1, 2),
                amount=Decimal("50"),
                merchant_name=None,
                description="AMEX RESY CREDIT",
                plaid_category="FOOD_AND_DRINK",
            ),
        ]

        classifications, _ = build_classifications(transactions)

        self.assertEqual(
            classifications["resy-credit"],
            ("card_benefit", False, False),
        )

    def test_amex_lululemon_credit_is_card_benefit(self):
        transaction = self.card_benefit_transaction("AMEX LULULEMON CREDIT")

        classifications, _ = build_classifications([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("card_benefit", False, False),
        )

    def test_allowlisted_descriptions_with_negative_amount_are_not_card_benefits(self):
        for description in ("AMEX RESY CREDIT", "AMEX LULULEMON CREDIT"):
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(description, amount="-50")
                classifications, _ = build_classifications([transaction])
                self.assertNotEqual(
                    classifications[transaction.transaction_id][0],
                    "card_benefit",
                )

    def test_generic_lululemon_credit_is_not_card_benefit(self):
        transaction = self.card_benefit_transaction("LULULEMON CREDIT")

        classifications, _ = build_classifications([transaction])

        self.assertEqual(classifications[transaction.transaction_id], (None, None, None))

    def test_unrelated_positive_credit_is_not_card_benefit(self):
        transaction = self.card_benefit_transaction("OTHER STATEMENT CREDIT")

        classifications, _ = build_classifications([transaction])

        self.assertEqual(classifications[transaction.transaction_id], (None, None, None))

    def test_generic_transfer_in_behavior_is_unchanged(self):
        transaction = self.card_benefit_transaction(
            "ACCOUNT TRANSFER",
            category="TRANSFER_IN",
        )

        classifications, _ = build_classifications([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("transfer", False, None),
        )

    def test_card_benefit_classification_is_idempotent(self):
        transaction = self.card_benefit_transaction("AMEX RESY CREDIT")

        first, _ = build_classifications([transaction])
        second, _ = build_classifications([transaction])

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
