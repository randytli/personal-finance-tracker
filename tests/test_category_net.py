import asyncio
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.services.category_attribution import BENEFIT_TO_SPENDING, contribution
from api.routes.analytics import analytics_transactions, summarize_monthly_transactions


def tx(identifier, amount, kind, *, category=None, description="Unknown credit", month=8):
    return SimpleNamespace(transaction_id=identifier, transaction_date=date(2026, month, 10),
        amount=Decimal(amount), transaction_type=kind, is_spending=kind == "expense",
        is_internal_transfer=False, plaid_category=category, merchant_name=None,
        description=description)


ITEM = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
ACCOUNT = SimpleNamespace(account_id="card", name="Platinum Card", type="credit", mask="1004", subtype="credit card")


def row(value, classification=None, category=None, benefit=None, removed=False):
    category_override = SimpleNamespace(category=category, cleared_at=None) if category else None
    benefit_override = SimpleNamespace(benefit_category=benefit, cleared_at=None) if benefit else None
    return value, removed, classification, ITEM, ACCOUNT, category_override, benefit_override


class CategoryNetTests(unittest.TestCase):
    def test_all_approved_benefit_codes_and_unknown(self):
        self.assertEqual(len(BENEFIT_TO_SPENDING), 8)
        for benefit, spending in BENEFIT_TO_SPENDING.items():
            with self.subTest(benefit=benefit):
                value = tx(benefit, "10", "card_benefit", category="TRAVEL")
                result = contribution(value, benefit_override=SimpleNamespace(benefit_category=benefit, cleared_at=None),
                    item=ITEM, account=ACCOUNT)
                self.assertEqual(result["canonical_category"], spending)
                self.assertEqual(result["net_contribution"], Decimal("-10"))
        unknown = contribution(tx("unknown", "10", "card_benefit"),
            benefit_override=SimpleNamespace(benefit_category="FUTURE", cleared_at=None), item=ITEM, account=ACCOUNT)
        self.assertEqual(unknown["canonical_category"], "UNCATEGORIZED")

    def test_precedence_restore_and_ineligible_rows(self):
        value = tx("auto", "13.81", "expense", description="Walmart", category="TRAVEL")
        benefit = SimpleNamespace(benefit_category="TRAVEL_CREDIT", cleared_at=None)
        manual = contribution(value, "card_benefit", category_override=SimpleNamespace(category="GROCERIES", cleared_at=None),
            benefit_override=benefit, item=ITEM, account=ACCOUNT)
        self.assertEqual((manual["canonical_category"], manual["attribution_source"]), ("TRAVEL", "manual_benefit"))
        benefit.cleared_at = object()
        automatic = contribution(value, "card_benefit", benefit_override=benefit, item=ITEM, account=ACCOUNT)
        self.assertEqual(automatic["canonical_category"], "GENERAL_MERCHANDISE")
        self.assertEqual(automatic["attribution_source"], "automatic_benefit")
        self.assertEqual(contribution(tx("refund", "20", "refund", category="NEW_CODE"))["canonical_category"], "UNCATEGORIZED")
        self.assertEqual(contribution(tx("reimbursement", "15", "reimbursement", category="TRAVEL"))["canonical_category"], "UNCATEGORIZED")
        self.assertEqual(contribution(tx("reimbursement", "15", "reimbursement"), category_override=SimpleNamespace(category="DINING", cleared_at=None))["canonical_category"], "DINING")
        internal = tx("internal", "20", "refund", category="TRAVEL")
        internal.is_internal_transfer = True
        self.assertIsNone(contribution(internal))
        self.assertIsNone(contribution(tx("wrong-sign", "-10", "refund")))

    def test_monthly_components_and_complete_details_reconcile(self):
        rows = [row(tx("expense", "-100", "expense", category="ENTERTAINMENT")),
                row(tx("refund", "20", "refund", category="ENTERTAINMENT")),
                row(tx("repayment", "15", "reimbursement"), category="ENTERTAINMENT"),
                row(tx("benefit", "25", "card_benefit"), benefit="DIGITAL_ENTERTAINMENT_CREDIT"),
                row(tx("uncategorized", "10", "reimbursement")),
                row(tx("removed", "50", "card_benefit"), removed=True)]
        summary = summarize_monthly_transactions(rows)
        groups = summary["category_net_breakdown"]
        for field in ("gross_spending", "refunds", "reimbursements", "card_benefits", "net_spending"):
            self.assertEqual(sum((Decimal(group[field]) for group in groups), Decimal(0)), Decimal(summary[field]))
        self.assertEqual(next(group for group in groups if group["category"] == "ENTERTAINMENT")["net_spending"], "40.00")
        self.assertEqual(next(group for group in groups if group["category"] == "UNCATEGORIZED")["net_spending"], "-10.00")
        with patch("api.routes.analytics._active_month_rows", AsyncMock(return_value=rows)), \
             patch("api.routes.analytics.load_label_overrides", AsyncMock(return_value={})), \
             patch("api.routes.analytics.SessionLocal"):
            async def pages():
                return [await analytics_transactions(month="2026-08", category=None, transaction_type=None,
                    benefit_category=None, canonical_category="ENTERTAINMENT",
                    spending_component="net", limit=2, offset=offset) for offset in (0, 2)]
            responses = asyncio.run(pages())
        details = [detail for response in responses for detail in response["transactions"]]
        self.assertEqual([response["total"] for response in responses], [4, 4])
        self.assertEqual(sum((Decimal(detail["net_contribution"]) for detail in details), Decimal(0)), Decimal("40"))
        self.assertEqual(responses[0]["component_totals"]["net_spending"], "40.00")

    def test_ambiguous_filters_rejected(self):
        for kwargs in ({"category": "TRAVEL", "canonical_category": "TRAVEL"},
                       {"transaction_type": "expense", "spending_component": "gross"},
                       {"benefit_category": "TRAVEL_CREDIT", "spending_component": "net"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(HTTPException) as error:
                asyncio.run(analytics_transactions(month="2026-08", **kwargs))
            self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
