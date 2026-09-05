import asyncio
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.routes.analytics import (
    analytics_transactions,
    spending_trend,
    summarize_breakdown,
    summarize_monthly_transactions,
    transaction_details,
)


def transaction(identifier, day, amount, kind, category="GENERAL_MERCHANDISE"):
    return SimpleNamespace(
        transaction_id=identifier,
        transaction_date=day,
        amount=Decimal(amount),
        transaction_type=kind,
        is_spending=kind == "expense",
        is_internal_transfer=None,
        plaid_category=category,
        merchant_name=f"Merchant {identifier}",
        description=f"Description {identifier}",
    )


class AnalyticsPhaseOneTests(unittest.TestCase):
    def test_manual_override_drives_monthly_metrics(self):
        value = transaction("override", date(2026, 8, 1), "25", None)
        result = summarize_monthly_transactions([(value, False, "refund")])
        self.assertEqual(result["refunds"], "25.00")
        self.assertEqual(result["unclassified_count"], 0)

    def test_category_totals_expose_separate_expense_and_refund_counts(self):
        rows = [
            (transaction("expense", date(2026, 8, 1), "-40", "expense", "FOOD_AND_DRINK"), False),
            (transaction("refund", date(2026, 8, 2), "10", "refund", "FOOD_AND_DRINK"), False),
            (transaction("benefit", date(2026, 8, 3), "5", "card_benefit", "FOOD_AND_DRINK"), False),
        ]
        result = summarize_monthly_transactions(rows)
        category = result["category_breakdown"][0]
        self.assertEqual(category["gross_spending"], "40.00")
        self.assertEqual(category["refunds"], "10.00")
        self.assertEqual(category["expense_transaction_count"], 1)
        self.assertEqual(category["refund_transaction_count"], 1)
        self.assertEqual(category["spending_transaction_count"], 2)
        self.assertEqual(result["card_benefits"], "5.00")

    def test_category_drilldowns_separate_expenses_refunds_and_benefits(self):
        rows = [
            (transaction("expense", date(2026, 8, 1), "-40", "expense"), False),
            (transaction("refund", date(2026, 8, 2), "10", "refund"), False),
            (transaction("benefit", date(2026, 8, 3), "5", "card_benefit"), False),
        ]
        expenses = transaction_details(rows, "GENERAL_MERCHANDISE", "expense")
        refunds = transaction_details(rows, "GENERAL_MERCHANDISE", "refund")
        self.assertEqual([row["transaction_id"] for row in expenses], ["expense"])
        self.assertEqual([row["transaction_id"] for row in refunds], ["refund"])

    def test_twelve_month_trend_is_chronological_and_zero_filled(self):
        rows = [
            (transaction("income", date(2026, 8, 1), "100", "income"), False),
            (transaction("expense", date(2026, 8, 2), "-40", "expense"), False),
        ]
        with patch(
            "api.routes.analytics._active_analytics_rows",
            AsyncMock(return_value=rows),
        ):
            result = asyncio.run(spending_trend("2026-08"))
        self.assertEqual(len(result["months"]), 12)
        self.assertEqual(result["months"][0]["month"], "2025-09")
        self.assertEqual(result["months"][-1], {
            "month": "2026-08",
            "net_spending": "40.00",
            "income": "100.00",
            "net_savings": "60.00",
        })
        self.assertEqual(result["months"][0]["net_savings"], "0.00")

    def test_breakdown_excludes_payment_and_reconciles_expense(self):
        item = SimpleNamespace(institution_id="ins_test", institution_name="Test Bank")
        account = SimpleNamespace(
            account_id="account", name="Card", mask="1234", type="credit", subtype="credit card"
        )
        rows = [
            (transaction("expense", date(2026, 8, 1), "-75", "expense"), False, None, item, account),
            (transaction("payment", date(2026, 8, 2), "-500", "payment"), False, None, item, account),
        ]
        groups = summarize_breakdown(rows, "institution")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["gross_spending"], "75.00")
        self.assertEqual(groups[0]["net_spending"], "75.00")

    def test_drilldown_uses_effective_type_and_safe_metadata(self):
        item = SimpleNamespace(institution_name="Test Bank")
        account = SimpleNamespace(name="Checking", mask="1234", type="depository", subtype="checking")
        value = transaction("manual", date(2026, 8, 1), "20", None)
        details = transaction_details([(value, False, "income", item, account)], transaction_type="income")
        self.assertEqual(details[0]["transaction_type"], "income")
        self.assertNotIn("access_token", details[0])
        self.assertNotIn("payload", details[0])

    def test_drilldown_pagination_and_invalid_type(self):
        rows = [
            (transaction("old", date(2026, 8, 1), "-1", "expense"), False),
            (transaction("new", date(2026, 8, 2), "-2", "expense"), False),
        ]
        with patch("api.routes.analytics._active_month_rows", AsyncMock(return_value=rows)):
            result = asyncio.run(analytics_transactions("2026-08", None, "expense", 1, 1))
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["transactions"][0]["transaction_id"], "old")
            with self.assertRaises(HTTPException):
                asyncio.run(analytics_transactions("2026-08", None, "invalid", 50, 0))


if __name__ == "__main__":
    unittest.main()
