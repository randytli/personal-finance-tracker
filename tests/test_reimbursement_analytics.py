import asyncio
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.categories import category_editable, effective_category
from api.routes.analytics import (
    _active_month_rows, analytics_transactions, category_transaction_details,
    spending_trend, summarize_breakdown,
    summarize_category_transactions, summarize_monthly_transactions, transaction_details,
)
from api.routes.review import _apply_category


def transaction(identifier, month, amount, kind, *, category="FOOD_AND_DRINK",
                merchant="Ordinary Merchant", internal=None):
    return SimpleNamespace(
        transaction_id=identifier, transaction_date=date(2026, month, 10),
        amount=Decimal(amount), transaction_type=kind, is_spending=kind == "expense",
        is_internal_transfer=internal, plaid_category=category,
        merchant_name=merchant, description=identifier,
    )


class ReimbursementAnalyticsTests(unittest.TestCase):
    def setUp(self):
        session = patch('api.routes.analytics.SessionLocal')
        session.start()
        self.addCleanup(session.stop)

    def test_expense_reimbursement_and_refund_reconcile_without_changing_spending_counts(self):
        expense = transaction("purchase", 8, "-100", "expense")
        repayment = transaction("repayment", 8, "40", "transfer", category="TRANSFER_IN")
        refund = transaction("refund", 8, "10", "refund")
        rows = [(expense, False), (repayment, False, "reimbursement"), (refund, False)]

        with_repayment = summarize_monthly_transactions(rows[:2])
        self.assertEqual(with_repayment["gross_spending"], "100.00")
        self.assertEqual(with_repayment["reimbursements"], "40.00")
        self.assertEqual(with_repayment["reimbursement_transaction_count"], 1)
        self.assertEqual(with_repayment["net_spending"], "60.00")

        summary = summarize_monthly_transactions(rows)
        self.assertEqual(summary["refunds"], "10.00")
        self.assertEqual(summary["net_spending"], "50.00")
        self.assertEqual(sum(Decimal(group["net_spending"]) for group in summary["category_breakdown"]), Decimal("50"))
        by_category = {group["category"]: group for group in summary["category_breakdown"]}
        self.assertEqual(by_category["FOOD_AND_DRINK"]["spending_transaction_count"], 2)
        self.assertEqual(by_category["FOOD_AND_DRINK"]["expense_transaction_count"], 1)
        self.assertEqual(by_category["FOOD_AND_DRINK"]["refund_transaction_count"], 1)
        self.assertEqual(by_category["FOOD_AND_DRINK"]["reimbursement_transaction_count"], 0)
        self.assertEqual(by_category["UNCATEGORIZED"]["spending_transaction_count"], 0)
        self.assertEqual(by_category["UNCATEGORIZED"]["reimbursement_transaction_count"], 1)
        self.assertEqual(by_category["UNCATEGORIZED"]["reimbursements"], "40.00")
        self.assertEqual(by_category["UNCATEGORIZED"]["net_spending"], "-40.00")
        self.assertEqual(summarize_category_transactions(rows, "UNCATEGORIZED")["reimbursements"], "40.00")

    def test_manual_type_changes_metric_split_and_preserves_net_savings_relationship(self):
        expense = transaction("purchase", 8, "-100", "expense")
        credit = transaction("credit", 8, "40", "refund")
        baseline = summarize_monthly_transactions([(expense, False), (credit, False)])
        overridden = summarize_monthly_transactions([(expense, False), (credit, False, "reimbursement")])
        self.assertEqual(baseline["refunds"], "40.00")
        self.assertEqual(overridden["refunds"], "0.00")
        self.assertEqual(overridden["reimbursements"], "40.00")
        self.assertEqual(baseline["net_spending"], overridden["net_spending"])
        self.assertEqual(baseline["category_breakdown"][0]["spending_transaction_count"], 2)
        self.assertEqual(sum(group["spending_transaction_count"] for group in overridden["category_breakdown"]), 1)

        credit.transaction_type = "income"
        income = summarize_monthly_transactions([(expense, False), (credit, False)])
        reimbursement = summarize_monthly_transactions([(expense, False), (credit, False, "reimbursement")])
        self.assertEqual(income["income"], "40.00")
        self.assertEqual(reimbursement["income"], "0.00")
        self.assertEqual(income["net_spending"], "100.00")
        self.assertEqual(reimbursement["net_spending"], "60.00")
        self.assertEqual(income["net_savings"], reimbursement["net_savings"])

    def test_reimbursement_uses_only_manual_category_and_clearing_restores_uncategorized(self):
        value = transaction("repayment", 8, "40", "transfer",
                            category="TRANSFER_IN", merchant="Weee")
        self.assertEqual(effective_category(value, None, "reimbursement"), "UNCATEGORIZED")
        self.assertTrue(category_editable(value, "reimbursement"))
        override = SimpleNamespace(category="GROCERIES", cleared_at=None)
        self.assertEqual(effective_category(value, override, "reimbursement"), "GROCERIES")
        rows = [(value, False, "reimbursement", None, None, override)]
        self.assertEqual(summarize_monthly_transactions(rows)["category_breakdown"][0]["category"], "GROCERIES")
        override.cleared_at = datetime(2026, 8, 11)
        self.assertEqual(effective_category(value, override, "reimbursement"), "UNCATEGORIZED")
        self.assertEqual(summarize_monthly_transactions(rows)["category_breakdown"][0]["category"], "UNCATEGORIZED")
        self.assertEqual(value.plaid_category, "TRANSFER_IN")
        value.is_internal_transfer = True
        self.assertFalse(category_editable(value, "reimbursement"))

    def test_category_mutation_preserves_override_and_returns_reimbursement_category(self):
        value = transaction("repayment", 8, "40", "transfer",
                            category="TRANSFER_IN", merchant="Weee")
        classification = SimpleNamespace(transaction_type="reimbursement", cleared_at=None)
        db = SimpleNamespace(get=AsyncMock(side_effect=[None, classification]), add=Mock())
        saved, changed = asyncio.run(_apply_category(db, value, "GROCERIES", "test-user"))
        self.assertTrue(changed)
        self.assertEqual(saved["effective_category"], "GROCERIES")
        category_override = db.add.call_args.args[0]
        db.get = AsyncMock(side_effect=[category_override, classification])
        cleared, changed = asyncio.run(_apply_category(db, value, None, "test-user"))
        self.assertTrue(changed)
        self.assertEqual(cleared["effective_category"], "UNCATEGORIZED")
        self.assertEqual(value.plaid_category, "TRANSFER_IN")

    def test_posted_month_trend_does_not_backdate_reimbursement(self):
        rows = [
            (transaction("purchase", 7, "-100", "expense"), False),
            (transaction("repayment", 8, "40", "transfer"), False, "reimbursement"),
        ]
        with patch("api.routes.analytics._active_analytics_rows", AsyncMock(return_value=rows)):
            result = asyncio.run(spending_trend("2026-08"))
        by_month = {month["month"]: month for month in result["months"]}
        self.assertEqual(by_month["2026-07"]["net_spending"], "100.00")
        self.assertEqual(by_month["2026-07"]["reimbursements"], "0.00")
        self.assertEqual(by_month["2026-08"]["net_spending"], "-40.00")
        self.assertEqual(by_month["2026-08"]["reimbursements"], "40.00")
        self.assertEqual(by_month["2026-08"]["reimbursement_transaction_count"], 1)
        self.assertEqual(by_month["2026-06"]["reimbursement_transaction_count"], 0)

    def test_breakdown_details_and_pages_reconcile_by_actual_ownership(self):
        chase = SimpleNamespace(institution_id="ins_56", institution_name="Chase")
        amex = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
        checking = SimpleNamespace(account_id="checking", name="Checking", mask="1106",
                                   type="depository", subtype="checking")
        card = SimpleNamespace(account_id="card", name="Gold", mask="3008",
                               type="credit", subtype="credit card")
        rows = [
            (transaction("chase-one", 8, "40", "transfer", category="TRANSFER_IN"), False,
             "reimbursement", chase, checking),
            (transaction("chase-two", 8, "15", "income", category="INCOME"), False,
             "reimbursement", chase, checking),
            (transaction("amex", 8, "5", "refund"), False, "reimbursement", amex, card),
            (transaction("internal", 8, "20", "reimbursement", internal=True), False,
             None, chase, checking),
            (transaction("removed", 8, "30", "reimbursement"), True, None, chase, checking),
        ]
        summary = summarize_monthly_transactions(rows)
        self.assertEqual(summary["reimbursements"], "60.00")
        self.assertEqual(summary["reimbursement_transaction_count"], 3)
        institutions = summarize_breakdown(rows, "institution", "reimbursements")
        accounts = summarize_breakdown(rows, "account", "reimbursements")
        self.assertEqual({group["institution_id"]: group["reimbursements"] for group in institutions},
                         {"ins_56": "55.00", "ins_10": "5.00"})
        self.assertEqual({group["account_id"]: group["reimbursements"] for group in accounts},
                         {"checking": "55.00", "card": "5.00"})
        self.assertEqual(sum(group["reimbursement_transaction_count"] for group in accounts), 3)
        self.assertEqual(sum(Decimal(group["reimbursements"]) for group in
                             summarize_breakdown(rows, "account")), Decimal("60"))
        details = transaction_details(rows, "UNCATEGORIZED", "reimbursement")
        self.assertEqual(len(details), 3)
        self.assertEqual(sum(Decimal(detail["amount"]) for detail in details), Decimal("60"))
        self.assertEqual(len(category_transaction_details(rows, "UNCATEGORIZED")), 3)
        self.assertEqual(len(transaction_details(rows, "UNCATEGORIZED", "reimbursement", "ins_56", "checking")), 2)
        self.assertEqual(len(transaction_details(rows, "UNCATEGORIZED", "refund")), 0)

        with (patch("api.routes.analytics._active_month_rows", AsyncMock(return_value=rows)),
              patch("api.routes.analytics.load_label_overrides", AsyncMock(return_value={}))):
            first = asyncio.run(analytics_transactions("2026-08", "UNCATEGORIZED", "reimbursement", 1, 0))
            second = asyncio.run(analytics_transactions("2026-08", "UNCATEGORIZED", "reimbursement", 1, 1))
            third = asyncio.run(analytics_transactions("2026-08", "UNCATEGORIZED", "reimbursement", 1, 2))
        self.assertEqual(first["total"], 3)
        self.assertEqual(first["reimbursements"], "60.00")
        self.assertEqual(first["reimbursement_transaction_count"], 3)
        self.assertEqual(second["reimbursements"], first["reimbursements"])
        self.assertEqual(sum(Decimal(page["transactions"][0]["amount"])
                             for page in (first, second, third)), Decimal("60"))

        with patch("api.routes.analytics._active_analytics_rows", AsyncMock(return_value=rows)):
            by_category = asyncio.run(_active_month_rows("2026-08", "UNCATEGORIZED"))
        self.assertEqual(len(by_category), 5)


if __name__ == "__main__":
    unittest.main()
