import asyncio
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.labels import label_result
from api.routes.analytics import (
    analytics_transactions, summarize_memberships, summarize_monthly_transactions,
)


def transaction(identifier, day, amount, kind, *, spending=False, internal=False, category='ENTERTAINMENT'):
    return SimpleNamespace(
        transaction_id=identifier, transaction_date=day, amount=Decimal(amount),
        transaction_type=kind, is_spending=spending, is_internal_transfer=internal,
        merchant_name=identifier, description=identifier, plaid_category=category,
    )


def account(identifier):
    return SimpleNamespace(account_id=identifier, name=identifier, mask='1234',
                           type='credit', subtype='credit card')


class MembershipTests(unittest.TestCase):
    def test_instacart_exact_description_labels_refund_without_changing_type_or_monthly_totals(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        card = account('card')
        charge = transaction('charge', date(2026, 4, 3), '-10.65', 'expense',
                             spending=True, category='FOOD_AND_DRINK')
        refund = transaction('refund', date(2026, 4, 7), '10.65', 'refund',
                             category='GENERAL_SERVICES')
        for tx in (charge, refund):
            tx.merchant_name = 'Instacart' if tx is charge else None
            tx.description = 'IC Instacart Subscrip'
        rows = [(tx, False, None, bank, card) for tx in (charge, refund)]
        monthly_before = summarize_monthly_transactions(rows)
        summary = summarize_memberships(rows, {}, '2025-05', '2026-04')
        self.assertEqual(summary['overall']['gross_charges'], '10.65')
        self.assertEqual(summary['overall']['refunds'], '10.65')
        self.assertEqual(summary['overall']['net_cost'], '0.00')
        self.assertEqual(summary['overall']['membership_transaction_count'], 2)
        self.assertEqual(summarize_monthly_transactions(rows), monthly_before)
        self.assertEqual((charge.transaction_type, refund.transaction_type),
                         ('expense', 'refund'))

    def test_exact_automatic_label_changes_cost_view_not_monthly_spending(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        card = account('card')
        charge = transaction('charge', date(2026, 7, 1), '-20', 'expense',
                             spending=True, category='GENERAL_SERVICES')
        charge.description = 'OpenAI ChatGPT Subscr'
        charge.merchant_name = 'OpenAI'
        row = (charge, False, None, bank, card)
        monthly_before = summarize_monthly_transactions([row])
        automatic = summarize_memberships([row], {}, '2025-08', '2026-07')
        self.assertEqual(automatic['overall']['gross_charges'], '20.00')
        excluded = SimpleNamespace(label='MEMBERSHIP', decision='exclude', cleared_at=None)
        self.assertEqual(
            summarize_memberships([row], {'charge': [excluded]}, '2025-08', '2026-07')
            ['overall']['gross_charges'], '0.00')
        excluded.cleared_at = datetime.now()
        self.assertEqual(
            summarize_memberships([row], {'charge': [excluded]}, '2025-08', '2026-07')
            ['overall']['gross_charges'], '20.00')
        self.assertEqual(summarize_monthly_transactions([row]), monthly_before)

    def test_account_ownership_manual_labels_and_economic_exclusions(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        first, second = account('first'), account('second')
        rows = [
            (transaction('fee', date(2026, 2, 1), '-100', 'expense', spending=True), False, None, bank, first),
            (transaction('refund', date(2026, 4, 1), '20', 'refund'), False, None, bank, first),
            (transaction('benefit', date(2026, 4, 2), '10', 'card_benefit'), False, None, bank, second),
            (transaction('excluded', date(2026, 6, 1), '90', None), False, None, bank, second),
            (transaction('payment', date(2026, 6, 2), '90', 'payment', internal=True), False, None, bank, second),
            (transaction('other', date(2026, 6, 3), '-50', 'expense', spending=True), False, None, bank, first),
            (transaction('removed', date(2026, 6, 4), '-70', 'expense', spending=True), True, None, bank, first),
        ]
        include = lambda: [SimpleNamespace(label='MEMBERSHIP', decision='include', cleared_at=None)]
        decisions = {row[0].transaction_id: include() for row in rows if row[0].transaction_id != 'other'}
        result = summarize_memberships(rows, decisions, '2025-10', '2026-09')
        self.assertEqual(result['overall'], {
            'gross_charges': '100.00', 'refunds': '20.00', 'card_benefits': '10.00',
            'net_cost': '70.00', 'membership_transaction_count': 5,
            'excluded_transaction_count': 2, 'unclassified_count': 1,
        })
        by_account = {value['account_id']: value for value in result['accounts']}
        self.assertEqual(by_account['first']['net_cost'], '80.00')
        self.assertEqual(by_account['second']['net_cost'], '-10.00')
        self.assertEqual(by_account['second']['excluded_transaction_count'], 2)
        self.assertEqual(len(result['months']), 12)
        self.assertEqual(result['months'][0]['net_cost'], '0.00')
        self.assertEqual(result['months'][4]['net_cost'], '100.00')
        self.assertEqual(sum(Decimal(month['net_cost']) for month in result['months']), Decimal('70.00'))
        self.assertEqual(sum(Decimal(item['net_cost']) for item in result['accounts']), Decimal('70.00'))
        self.assertEqual(summarize_monthly_transactions([rows[0]])['gross_spending'], '100.00')
        self.assertEqual(label_result(rows[0][0])['effective_labels'], [])

    def test_manual_exclude_and_explicit_credit_ownership(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        card = account('card')
        row = (transaction('credit', date(2026, 8, 1), '15', 'card_benefit'), False, None, bank, card)
        include = SimpleNamespace(label='MEMBERSHIP', decision='include', cleared_at=None)
        exclude = SimpleNamespace(label='MEMBERSHIP', decision='exclude', cleared_at=None)
        self.assertEqual(summarize_memberships([row], {'credit': [include]}, '2025-09', '2026-08')
                         ['overall']['net_cost'], '-15.00')
        self.assertEqual(summarize_memberships([row], {'credit': [exclude]}, '2025-09', '2026-08')
                         ['overall']['net_cost'], '0.00')
        include.cleared_at = datetime.now()
        self.assertEqual(summarize_memberships([row], {'credit': [include]}, '2025-09', '2026-08')
                         ['overall']['membership_transaction_count'], 0)

    def test_range_validation_and_existing_month_endpoint(self):
        with (
            patch('api.routes.analytics._active_month_rows', AsyncMock(return_value=[])),
            patch('api.routes.analytics._active_analytics_rows', AsyncMock(return_value=[])),
            patch('api.routes.analytics.load_label_overrides', AsyncMock(return_value={})),
        ):
            one = asyncio.run(analytics_transactions('2026-08', None, None, 50, 0))
            year = asyncio.run(analytics_transactions(None, None, None, 50, 0,
                start_month='2025-09', end_month='2026-08', label='MEMBERSHIP'))
            self.assertEqual((one['total'], year['total']), (0, 0))
            self.assertEqual(year['start_month'], '2025-09')
            for kwargs in (
                {'month': '2026-08', 'start_month': '2026-01', 'end_month': '2026-08'},
                {'start_month': '2026-08'},
                {'start_month': '2025-08', 'end_month': '2026-08'},
                {'start_month': '2026-09', 'end_month': '2026-08'},
            ):
                with self.subTest(kwargs=kwargs), self.assertRaises(HTTPException) as error:
                    asyncio.run(analytics_transactions(**kwargs))
                self.assertEqual(error.exception.status_code, 422)

    def test_range_drilldown_pagination_and_account_filter(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        first, second = account('first'), account('second')
        rows = [
            (transaction('old', date(2026, 2, 1), '-40', 'expense', spending=True), False, None, bank, first),
            (transaction('new', date(2026, 8, 1), '-60', 'expense', spending=True), False, None, bank, first),
            (transaction('other', date(2026, 8, 2), '-80', 'expense', spending=True), False, None, bank, second),
        ]
        include = lambda: [SimpleNamespace(label='MEMBERSHIP', decision='include', cleared_at=None)]
        decisions = {'old': include(), 'new': include(), 'other': include()}
        with (
            patch('api.routes.analytics._active_analytics_rows', AsyncMock(return_value=rows)),
            patch('api.routes.analytics.load_label_overrides', AsyncMock(return_value=decisions)),
        ):
            first_page = asyncio.run(analytics_transactions(
                month=None, start_month='2025-09', end_month='2026-08',
                category=None, transaction_type=None, limit=1, offset=0,
                institution_id=None, account_id='first', label='MEMBERSHIP'))
            second_page = asyncio.run(analytics_transactions(
                month=None, start_month='2025-09', end_month='2026-08',
                category=None, transaction_type=None, limit=1, offset=1,
                institution_id=None, account_id='first', label='MEMBERSHIP'))
        self.assertEqual(first_page['total'], 2)
        self.assertEqual(first_page['transactions'][0]['transaction_id'], 'new')
        self.assertEqual(second_page['transactions'][0]['transaction_id'], 'old')
