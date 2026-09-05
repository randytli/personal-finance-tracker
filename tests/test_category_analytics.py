import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException

from api.routes.analytics import (
    _month_bounds,
    category_transaction_details,
    summarize_category_transactions,
)


def transaction(
    transaction_id,
    day,
    amount,
    transaction_type,
    *,
    category="FOOD_AND_DRINK",
    is_spending=False,
):
    return SimpleNamespace(
        transaction_id=transaction_id,
        transaction_date=date(2026, 8, day),
        amount=Decimal(amount),
        transaction_type=transaction_type,
        plaid_category=category,
        is_spending=is_spending,
        merchant_name=f"Merchant {transaction_id}",
        description=f"Description {transaction_id}",
    )


class CategoryAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            (transaction("expense-old", 2, "-100", "expense", is_spending=True), False),
            (transaction("refund", 5, "25", "refund"), False),
            (transaction("expense-new", 8, "-40", "expense", is_spending=True), False),
            (transaction("payment", 9, "-500", "payment"), False),
            (transaction("benefit", 10, "10", "card_benefit"), False),
            (transaction("removed", 11, "-75", "expense", is_spending=True), True),
            (
                transaction(
                    "transportation",
                    12,
                    "-300",
                    "expense",
                    category="TRANSPORTATION",
                    is_spending=True,
                ),
                False,
            ),
        ]

    def test_category_summary_counts_only_active_expenses_and_refunds(self):
        result = summarize_category_transactions(self.rows, "FOOD_AND_DRINK")

        self.assertEqual(
            result,
            {
                "gross_spending": "140.00",
                "refunds": "25.00",
                "net_spending": "115.00",
                "spending_transaction_count": 3,
                "expense_transaction_count": 2,
                "refund_transaction_count": 1,
            },
        )

    def test_unrelated_category_is_excluded_by_category_filter(self):
        self.assertEqual(
            summarize_category_transactions(self.rows, "TRAVEL"),
            {
                "gross_spending": "0.00",
                "refunds": "0.00",
                "net_spending": "0.00",
                "spending_transaction_count": 0,
                "expense_transaction_count": 0,
                "refund_transaction_count": 0,
            },
        )

    def test_transaction_details_are_relevant_and_newest_first(self):
        details = category_transaction_details(self.rows, "FOOD_AND_DRINK")

        self.assertEqual(
            [item["transaction_id"] for item in details],
            ["expense-new", "refund", "expense-old"],
        )
        self.assertEqual(details[0]["amount"], "-40.00")
        self.assertEqual(details[1]["transaction_type"], "refund")

    def test_empty_details(self):
        self.assertEqual(category_transaction_details([], "FOOD_AND_DRINK"), [])

    def test_invalid_month(self):
        for month in ("2026-13", "2026-8", "August"):
            with self.subTest(month=month), self.assertRaises(HTTPException) as error:
                _month_bounds(month)
            self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
