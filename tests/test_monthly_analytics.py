import asyncio
import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException

from api.routes.analytics import monthly_spending, summarize_monthly_transactions


def transaction(
    amount,
    transaction_type,
    *,
    category="FOOD_AND_DRINK",
    is_spending=False,
):
    return SimpleNamespace(
        amount=Decimal(amount),
        transaction_type=transaction_type,
        plaid_category=category,
        is_spending=is_spending,
    )


class MonthlyAnalyticsTests(unittest.TestCase):
    def test_monthly_summary_rules(self):
        rows = [
            (transaction("-100", "expense", is_spending=True), False),
            (transaction("-40", "expense", category=None, is_spending=True), False),
            (transaction("-500", "payment"), False),
            (transaction("-200", "transfer"), False),
            (transaction("1000", "income"), False),
            (transaction("25", "refund"), False),
            (transaction("10", "card_benefit"), False),
            (transaction("30", None), False),
            (transaction("-75", "expense", is_spending=True), True),
        ]

        result = summarize_monthly_transactions(rows)

        self.assertEqual(result["gross_spending"], "140.00")
        self.assertEqual(result["refunds"], "25.00")
        self.assertEqual(result["card_benefits"], "10.00")
        self.assertEqual(result["net_spending"], "105.00")
        self.assertEqual(result["income"], "1000.00")
        self.assertEqual(result["net_savings"], "895.00")
        self.assertEqual(result["unclassified_count"], 1)
        self.assertEqual(
            result["category_breakdown"],
            [
                {
                    "category": "FOOD_AND_DRINK",
                    "gross_spending": "100.00",
                    "refunds": "25.00",
                    "net_spending": "75.00",
                    "spending_transaction_count": 2,
                },
                {
                    "category": "UNCATEGORIZED",
                    "gross_spending": "40.00",
                    "refunds": "0.00",
                    "net_spending": "40.00",
                    "spending_transaction_count": 1,
                },
            ],
        )

    def test_empty_month_returns_zero_summary(self):
        self.assertEqual(
            summarize_monthly_transactions([]),
            {
                "gross_spending": "0.00",
                "refunds": "0.00",
                "card_benefits": "0.00",
                "net_spending": "0.00",
                "income": "0.00",
                "net_savings": "0.00",
                "category_breakdown": [],
                "unclassified_count": 0,
            },
        )

    def test_adjustment_and_internal_transfer_do_not_change_metrics(self):
        internal = transaction("-500", "expense", is_spending=True)
        internal.is_internal_transfer = True
        result = summarize_monthly_transactions(
            [
                (transaction("100", None), False, "adjustment"),
                (transaction("-100", None), False, "adjustment"),
                (internal, False),
            ]
        )
        self.assertEqual(result["gross_spending"], "0.00")
        self.assertEqual(result["net_spending"], "0.00")
        self.assertEqual(result["net_savings"], "0.00")
        self.assertEqual(result["unclassified_count"], 0)

    def test_invalid_month_returns_422(self):
        with self.assertRaises(HTTPException) as error:
            asyncio.run(monthly_spending("2026-13"))
        self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
