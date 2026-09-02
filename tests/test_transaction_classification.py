import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from api.routes.plaid import build_classifications, fetch_transaction_pages


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
    def test_cross_institution_accounts_can_match(self):
        chase = transfer_transaction("chase-out", "chase-checking", 1, "-250", "TRANSFER_OUT")
        amex = transfer_transaction("amex-in", "amex-card", 3, "250", "TRANSFER_IN")
        classifications, _ = build_classifications([chase, amex])
        self.assertTrue(classifications["chase-out"][2])
        self.assertTrue(classifications["amex-in"][2])

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
    BENEFIT_DESCRIPTIONS = (
        "AMEX AIRLINE FEE REIMBURSEMENT",
        "AMEX DINING CREDIT",
        "AMEX LULULEMON CREDIT",
        "AMEX RESY CREDIT",
        "PLATINUM DIGITAL ENTERTAINMENT CREDIT",
        "PLATINUM HOTEL CREDIT",
        "PLATINUM LULULEMON CREDIT",
        "PLATINUM RESY CREDIT",
        "PLATINUM SAKS CREDIT",
        "PLATINUM UBER ONE CREDIT",
    )

    def card_benefit_transaction(
        self,
        description,
        amount="50",
        category="FOOD_AND_DRINK",
        account_id="amex-card",
        transaction_id="statement-credit",
        merchant_name=None,
    ):
        return SimpleNamespace(
            transaction_id=transaction_id,
            account_id=account_id,
            transaction_date=date(2026, 1, 2),
            amount=Decimal(amount),
            merchant_name=merchant_name,
            description=description,
            plaid_category=category,
        )

    def classify(
        self,
        transactions,
        amex_accounts=frozenset({"amex-card", "gold-card", "platinum-card"}),
        merchant_accounts=None,
    ):
        if merchant_accounts is None:
            merchant_accounts = {
                "DUNKIN DONUTS": {"gold-card"},
                "WALMART": {"platinum-card"},
            }
        return build_classifications(
            transactions,
            credit_account_ids={
                "amex-card",
                "chase-card",
                "gold-card",
                "platinum-card",
            },
            amex_benefit_account_ids=amex_accounts,
            amex_merchant_benefit_account_ids=merchant_accounts,
        )

    def test_all_exact_issuer_descriptions_are_card_benefits(self):
        for description in self.BENEFIT_DESCRIPTIONS:
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(description)
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    ("card_benefit", False, False),
                )

    def test_description_normalization_is_limited_to_case_spacing_and_punctuation(self):
        transaction = self.card_benefit_transaction(
            "  platinum---digital   entertainment credit!!  "
        )

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("card_benefit", False, False),
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

        classifications, _ = self.classify(transactions)

        self.assertEqual(
            classifications["resy-credit"],
            ("card_benefit", False, False),
        )

    def test_amex_lululemon_credit_is_card_benefit(self):
        transaction = self.card_benefit_transaction("AMEX LULULEMON CREDIT")

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("card_benefit", False, False),
        )

    def test_allowlisted_descriptions_with_negative_amount_are_not_card_benefits(self):
        for description in self.BENEFIT_DESCRIPTIONS:
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(description, amount="-50")
                classifications, _ = self.classify([transaction])
                self.assertNotEqual(
                    classifications[transaction.transaction_id][0],
                    "card_benefit",
                )

    def test_generic_lululemon_credit_is_not_card_benefit(self):
        transaction = self.card_benefit_transaction("LULULEMON CREDIT")

        classifications, _ = self.classify([transaction])

        self.assertEqual(classifications[transaction.transaction_id], (None, None, None))

    def test_unrelated_positive_credit_is_not_card_benefit(self):
        transaction = self.card_benefit_transaction("OTHER STATEMENT CREDIT")

        classifications, _ = self.classify([transaction])

        self.assertEqual(classifications[transaction.transaction_id], (None, None, None))

    def test_generic_transfer_in_behavior_is_unchanged(self):
        transaction = self.card_benefit_transaction(
            "ACCOUNT TRANSFER",
            category="TRANSFER_IN",
        )

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("transfer", False, None),
        )

    def test_card_benefit_classification_is_idempotent(self):
        transaction = self.card_benefit_transaction("AMEX RESY CREDIT")

        first, _ = self.classify([transaction])
        second, _ = self.classify([transaction])

        self.assertEqual(first, second)

    def test_allowlist_requires_authoritative_amex_credit_account(self):
        for account_id, amex_accounts in (
            ("chase-card", {"amex-card"}),
            ("amex-checking", {"amex-card"}),
        ):
            with self.subTest(account_id=account_id):
                transaction = self.card_benefit_transaction(
                    "PLATINUM HOTEL CREDIT",
                    account_id=account_id,
                )
                classifications, _ = self.classify(
                    [transaction],
                    amex_accounts=amex_accounts,
                )
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    (None, None, None),
                )

    def test_shortened_and_fuzzy_descriptions_remain_unclassified(self):
        for description in (
            "DIGITAL ENTERTAINMENT CREDIT",
            "HOTEL CREDIT",
            "PLATINUM RESY STATEMENT CREDIT",
            "AMEX DINING BENEFIT",
        ):
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(description)
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    (None, None, None),
                )

    def test_merchant_credits_and_accounting_adjustments_are_not_benefits(self):
        for description in (
            "PEACOCK TV, LLC UNIVERSAL CITY",
            "Uber",
            "TodayTix, Inc.",
            "Blue Bottle Coffee",
            "AplPay IC* INSTACART",
            "Dunkin",
            "Wal-Mart",
            "AMAZON SHOP WITH POINTS CREDIT",
            "ADJ REDIST PURCHASE BAL",
        ):
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(description)
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    (None, None, None),
                )

        chase_transaction = self.card_benefit_transaction(
            "Dunkin' Donuts",
            account_id="chase-card",
        )
        classifications, _ = self.classify(
            [chase_transaction],
            merchant_accounts={"DUNKIN DONUTS": {"chase-card"}},
        )
        self.assertEqual(
            classifications[chase_transaction.transaction_id],
            (None, None, None),
        )

    def test_gold_dunkin_credit_is_card_benefit(self):
        transaction = self.card_benefit_transaction(
            "Dunkin' Donuts",
            account_id="gold-card",
        )

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("card_benefit", False, False),
        )

    def test_platinum_walmart_credit_is_card_benefit(self):
        transaction = self.card_benefit_transaction(
            "Walmart",
            account_id="platinum-card",
        )

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("card_benefit", False, False),
        )

    def test_merchant_benefits_require_the_exact_amex_card(self):
        cases = (
            ("Dunkin' Donuts", "platinum-card"),
            ("Dunkin' Donuts", "chase-card"),
            ("Walmart", "gold-card"),
            ("Walmart", "chase-card"),
        )
        for description, account_id in cases:
            with self.subTest(description=description, account_id=account_id):
                transaction = self.card_benefit_transaction(
                    description,
                    account_id=account_id,
                )
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    (None, None, None),
                )

    def test_negative_merchant_transactions_are_not_card_benefits(self):
        for description, account_id in (
            ("Dunkin' Donuts", "gold-card"),
            ("Walmart", "platinum-card"),
        ):
            with self.subTest(description=description):
                transaction = self.card_benefit_transaction(
                    description,
                    amount="-7",
                    account_id=account_id,
                )
                classifications, _ = self.classify([transaction])
                self.assertNotEqual(
                    classifications[transaction.transaction_id][0],
                    "card_benefit",
                )

    def test_merchant_benefit_classification_is_idempotent(self):
        transactions = [
            self.card_benefit_transaction(
                "Dunkin' Donuts",
                account_id="gold-card",
                transaction_id="dunkin-credit",
            ),
            self.card_benefit_transaction(
                "Walmart",
                account_id="platinum-card",
                transaction_id="walmart-credit",
            ),
        ]

        first, _ = self.classify(transactions)
        second, _ = self.classify(transactions)

        self.assertEqual(first, second)

    def test_allowlisted_benefit_precedes_transfer_and_generic_income(self):
        for category in ("TRANSFER_IN", "INCOME"):
            with self.subTest(category=category):
                transaction = self.card_benefit_transaction(
                    "AMEX RESY CREDIT",
                    category=category,
                )
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    ("card_benefit", False, False),
                )

    def test_non_allowlisted_income_rules_are_unchanged(self):
        cases = (
            self.card_benefit_transaction(
                "PAYROLL DEPOSIT",
                category="INCOME",
            ),
            self.card_benefit_transaction(
                "INTEREST EARNED",
                category="OTHER",
            ),
        )
        for transaction in cases:
            with self.subTest(description=transaction.description):
                classifications, _ = self.classify([transaction])
                self.assertEqual(
                    classifications[transaction.transaction_id],
                    ("income", False, False),
                )

    def test_payment_precedes_allowlisted_benefit(self):
        transaction = self.card_benefit_transaction(
            "AMEX RESY CREDIT",
            category="LOAN_PAYMENTS",
        )

        classifications, _ = self.classify([transaction])

        self.assertEqual(
            classifications[transaction.transaction_id],
            ("payment", False, None),
        )

    def test_allowlisted_benefit_is_not_reclassified_as_refund(self):
        expense = self.card_benefit_transaction(
            "PLATINUM HOTEL CREDIT",
            amount="-300",
            transaction_id="expense",
            merchant_name="American Express",
        )
        benefit = self.card_benefit_transaction(
            "PLATINUM HOTEL CREDIT",
            amount="300",
            transaction_id="benefit",
            merchant_name="American Express",
        )

        classifications, refund_matches = self.classify([expense, benefit])

        self.assertEqual(classifications[benefit.transaction_id][0], "card_benefit")
        self.assertEqual(refund_matches, 0)

    def test_non_allowlisted_merchant_credit_still_uses_refund_matching(self):
        expense = self.card_benefit_transaction(
            "AWS",
            amount="-1",
            category="GENERAL_SERVICES",
            transaction_id="expense",
            merchant_name="Amazon Web Services",
        )
        credit = self.card_benefit_transaction(
            "AWS",
            amount="1",
            category="GENERAL_SERVICES",
            transaction_id="credit",
            merchant_name="Amazon Web Services",
        )

        classifications, refund_matches = self.classify([expense, credit])

        self.assertEqual(classifications[credit.transaction_id], ("refund", False, False))
        self.assertEqual(refund_matches, 1)


if __name__ == "__main__":
    unittest.main()
