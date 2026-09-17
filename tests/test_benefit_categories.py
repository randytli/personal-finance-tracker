import asyncio
import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.benefit_categories import automatic_benefit_category, effective_benefit_category
from api.routes.analytics import analytics_transactions, summarize_benefit_categories, summarize_breakdown, summarize_monthly_transactions


def tx(identifier, description, amount="10", kind="card_benefit"):
    return SimpleNamespace(transaction_id=identifier, transaction_date=date(2026, 8, 1),
        amount=Decimal(amount), transaction_type=kind, is_spending=False,
        is_internal_transfer=False, description=description, merchant_name=None,
        plaid_category="GENERAL_MERCHANDISE")


class BenefitCategoryTests(unittest.TestCase):
    def test_exact_domains_and_membership_independence(self):
        account = SimpleNamespace(name="Platinum Card", type="credit")
        self.assertEqual(automatic_benefit_category(tx("w", "Walmart", "13.81"), institution_id="ins_10", account_name=account.name, account_type=account.type), "SHOPPING_CREDIT")
        self.assertEqual(automatic_benefit_category(tx("u", "Platinum Uber One Credit"), institution_id="ins_10", account_name=account.name, account_type=account.type), "TRANSPORTATION_CREDIT")
        self.assertEqual(automatic_benefit_category(tx("p", "Peacock TV, LLC Universal City"), institution_id="ins_10", account_name="American Express Gold Card", account_type="credit"), "DIGITAL_ENTERTAINMENT_CREDIT")
        self.assertEqual(automatic_benefit_category(tx("x", "Walmart", "85.26"), institution_id="ins_10", account_name=account.name, account_type=account.type), "UNCATEGORIZED")
        self.assertEqual(automatic_benefit_category(tx("t", "TODAYTIX INC"), institution_id="ins_10", account_name="American Express Gold Card", account_type="credit"), "ENTERTAINMENT_CREDIT")
        self.assertEqual(automatic_benefit_category(tx("i", "INTUIT ORDER CHANNELSAN DIEGO"), institution_id="ins_10", account_name="American Express Gold Card", account_type="credit"), "GENERAL_SERVICES_CREDIT")

    def test_manual_override_wins_and_clear_restores_automatic(self):
        value = tx("w", "Walmart", "13.81")
        override = SimpleNamespace(benefit_category="UNCATEGORIZED", cleared_at=None)
        self.assertEqual(effective_benefit_category(value, override, institution_id="ins_10", account_name="Platinum Card", account_type="credit"), "UNCATEGORIZED")
        override.cleared_at = object()
        self.assertEqual(effective_benefit_category(value, override, institution_id="ins_10", account_name="Platinum Card", account_type="credit"), "SHOPPING_CREDIT")

    def test_breakdown_does_not_change_monthly_card_benefit_metric(self):
        item = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
        account = SimpleNamespace(account_id="a", name="Platinum Card", type="credit", mask="1004", subtype="credit card")
        rows = [(tx("w", "Walmart", "13.81"), False, None, item, account, None, None)]
        summary = summarize_monthly_transactions(rows)
        self.assertEqual(summary["card_benefits"], "13.81")
        self.assertEqual(summarize_benefit_categories(rows)[0]["benefit_category"], "SHOPPING_CREDIT")

    def test_overview_response_reconciles_and_category_drilldown_filters_before_pagination(self):
        item = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
        account = SimpleNamespace(account_id="a", name="Platinum Card", type="credit", mask="1004", subtype="credit card")
        values = [tx("w1", "Walmart", "13.81"), tx("w2", "Walmart", "13.81"),
                  tx("uber", "Platinum Uber One Credit", "9.99"),
                  tx("other", "Unknown credit", "2.00"), tx("refund", "Walmart", "85.26", "refund"),
                  tx("expense", "Walmart", "-100.00", "expense")]
        rows = [(value, False, None, item, account, None, None) for value in values]
        summary = summarize_monthly_transactions(rows)
        self.assertEqual(sum(Decimal(row['benefit_amount']) for row in summary['benefit_category_breakdown']),
                         Decimal(summary['card_benefits']))
        self.assertEqual(summary['card_benefits'], '39.61')
        with patch('api.routes.analytics._active_month_rows', AsyncMock(return_value=rows)), \
             patch('api.routes.analytics.load_label_overrides', AsyncMock(return_value={})), \
             patch('api.routes.analytics.SessionLocal'):
            async def pages():
                return [await analytics_transactions(month='2026-08', category=None,
                        transaction_type='card_benefit', benefit_category='SHOPPING_CREDIT',
                        limit=1, offset=offset) for offset in (0, 1)]
            responses = asyncio.run(pages())
        details = [row for response in responses for row in response['transactions']]
        self.assertEqual([response['total'] for response in responses], [2, 2])
        self.assertEqual({row['transaction_id'] for row in details}, {'w1', 'w2'})
        self.assertTrue(all(row['transaction_type'] == 'card_benefit' for row in details))
        self.assertTrue(all(row['effective_benefit_category'] == 'SHOPPING_CREDIT' for row in details))
        shopping = next(row for row in summary['benefit_category_breakdown'] if row['benefit_category'] == 'SHOPPING_CREDIT')
        self.assertEqual(sum(Decimal(row['amount']) for row in details), Decimal(shopping['benefit_amount']))

    def test_institution_breakdown_uses_the_same_benefit_scope(self):
        item = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
        account = SimpleNamespace(account_id="a", name="Platinum Card", type="credit", mask="1004", subtype="credit card")
        benefit = tx("benefit", "Platinum Uber One Credit", "9.99")
        expense = tx("expense", "Other", "-40", "expense")
        rows = [(benefit, False, None, item, account, None, None),
                (expense, False, None, item, account, None, None)]
        groups = summarize_breakdown(rows, "account", "benefits")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["benefit_amount"], "9.99")
        self.assertEqual(groups[0]["benefit_transaction_count"], 1)

    def test_manual_card_benefit_override_uses_effective_type_in_breakdown_and_details(self):
        item = SimpleNamespace(institution_id="ins_10", institution_name="American Express")
        account = SimpleNamespace(account_id="a", name="Platinum Card", type="credit", mask="1004", subtype="credit card")
        value = tx("manual", "Unknown credit", "104", "expense")
        rows = [(value, False, "card_benefit", item, account, None, None)]
        summary = summarize_monthly_transactions(rows)
        category = summary["benefit_category_breakdown"][0]
        details = __import__("api.routes.analytics", fromlist=["transaction_details"]).transaction_details(
            rows, transaction_type="card_benefit", benefit_category="UNCATEGORIZED")
        self.assertEqual(category["benefit_transaction_count"], len(details))
        self.assertEqual(category["benefit_amount"], "104.00")
        self.assertEqual(sum(Decimal(row["amount"]) for row in details), Decimal(category["benefit_amount"]))


if __name__ == "__main__":
    unittest.main()
