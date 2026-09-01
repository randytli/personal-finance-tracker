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

    def test_recurring_expenses_use_unique_recent_exact_match(self):
        transactions = [
            united_transaction("older-expense", 1, "-500"),
            united_transaction("recent-expense", 20, "-500"),
            united_transaction("credit", 24, "500"),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["credit"], ("refund", False, False))
        self.assertEqual(refund_matches, 1)

    def test_multiple_recent_expenses_remain_ambiguous(self):
        transactions = [
            united_transaction("recent-expense-1", 20, "-500"),
            united_transaction("recent-expense-2", 21, "-500"),
            united_transaction("credit", 24, "500"),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["credit"], (None, None, None))
        self.assertEqual(refund_matches, 0)

    def test_unique_historical_refund_outside_seven_days_still_matches(self):
        transactions = [
            united_transaction("expense", 1, "-500"),
            united_transaction("credit", 20, "500"),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["credit"], ("refund", False, False))
        self.assertEqual(refund_matches, 1)

    def test_same_day_aws_reversal_is_refund(self):
        transactions = [
            SimpleNamespace(
                transaction_id="aws-expense",
                account_id="credit-card",
                transaction_date=date(2026, 9, 1),
                amount=Decimal("-1"),
                merchant_name="Amazon Web Services",
                description="AWS",
                plaid_category="GENERAL_SERVICES",
            ),
            SimpleNamespace(
                transaction_id="aws-credit",
                account_id="credit-card",
                transaction_date=date(2026, 9, 1),
                amount=Decimal("1"),
                merchant_name="Amazon Web Services",
                description="AWS",
                plaid_category="GENERAL_SERVICES",
            ),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["aws-expense"][0], "expense")
        self.assertEqual(classifications["aws-credit"], ("refund", False, False))
        self.assertEqual(refund_matches, 1)

    def test_multiple_same_day_reversals_remain_ambiguous(self):
        transactions = [
            SimpleNamespace(
                transaction_id=transaction_id,
                account_id="credit-card",
                transaction_date=date(2026, 9, 1),
                amount=Decimal(amount),
                merchant_name="Amazon Web Services",
                description="AWS",
                plaid_category="GENERAL_SERVICES",
            )
            for transaction_id, amount in (
                ("aws-expense-1", "-1"),
                ("aws-expense-2", "-1"),
                ("aws-credit", "1"),
            )
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["aws-credit"], (None, None, None))
        self.assertEqual(refund_matches, 0)

    def test_partial_amazon_refund_without_exact_amount_remains_unclassified(self):
        transactions = [
            SimpleNamespace(
                transaction_id="amazon-expense",
                account_id="credit-card",
                transaction_date=date(2026, 6, 1),
                amount=Decimal("-55.49"),
                merchant_name="Amazon",
                description="Amazon.com*ORDER",
                plaid_category="GENERAL_MERCHANDISE",
            ),
            SimpleNamespace(
                transaction_id="amazon-credit",
                account_id="credit-card",
                transaction_date=date(2026, 6, 10),
                amount=Decimal("36.03"),
                merchant_name="Amazon",
                description="Amazon.com",
                plaid_category="GENERAL_MERCHANDISE",
            ),
        ]

        classifications, refund_matches = build_classifications(transactions)

        self.assertEqual(classifications["amazon-credit"], (None, None, None))
        self.assertEqual(refund_matches, 0)


class CreditCardPaymentClassificationTests(unittest.TestCase):
    def transaction(
        self,
        transaction_id="credit-payment",
        account_id="credit-card",
        amount="1002.17",
        description="Payment Thank You-Mobile",
        category="LOAN_DISBURSEMENTS",
        day=2,
    ):
        return SimpleNamespace(
            transaction_id=transaction_id,
            account_id=account_id,
            transaction_date=date(2026, 1, day),
            amount=Decimal(amount),
            merchant_name=None,
            description=description,
            plaid_category=category,
        )

    def test_chase_mobile_payment_amounts_are_payments_on_credit_account(self):
        for amount in ("1002.17", "30.65"):
            with self.subTest(amount=amount):
                transaction = self.transaction(amount=amount)
                classifications, _ = build_classifications(
                    [transaction],
                    {"credit-card"},
                )
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    ("payment", False, None),
                )

    def test_payment_rule_requires_credit_account_positive_amount_exact_text_and_category(self):
        cases = (
            self.transaction(account_id="checking"),
            self.transaction(amount="-1002.17"),
            self.transaction(description="Payment Thank You"),
            self.transaction(category="TRANSFER_IN"),
        )
        for transaction in cases:
            with self.subTest(transaction=transaction):
                classifications, _ = build_classifications(
                    [transaction],
                    {"credit-card"},
                )
                self.assertNotEqual(
                    classifications[transaction.transaction_id][0],
                    "payment",
                )

    def test_credit_payment_can_match_checking_payment_as_internal(self):
        credit = self.transaction(amount="100", day=2)
        checking = self.transaction(
            transaction_id="checking-payment",
            account_id="checking",
            amount="-100",
            description="Credit card payment",
            category="LOAN_PAYMENTS",
            day=1,
        )

        classifications, _ = build_classifications(
            [checking, credit],
            {"credit-card"},
        )

        self.assertEqual(classifications[credit.transaction_id], ("payment", False, True))
        self.assertEqual(classifications[checking.transaction_id], ("payment", False, True))


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
