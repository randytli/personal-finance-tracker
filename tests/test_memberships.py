import asyncio
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.labels import label_result
from api.routes.analytics import (
    analytics_transactions, membership_costs, summarize_memberships,
    summarize_monthly_transactions,
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
    def test_membership_detail_views_filter_before_pagination_and_reconcile_benefits(self):
        bank = SimpleNamespace(institution_id='ins_10', institution_name='American Express')
        card = account('card'); card.name = 'Platinum Card'
        rows = []
        for ident, amount, kind in [('charge', '-20', 'expense'), ('refund', '3', 'refund'),
                                    ('benefit', '7', 'card_benefit')]:
            tx = transaction(ident, date(2026, 9, 1), amount, kind,
                             spending=kind == 'expense')
            tx.description = {'charge': 'Walmart', 'refund': 'IC Instacart Subscrip',
                              'benefit': 'PLATINUM UBER ONE CREDIT'}[ident]
            rows.append((tx, False, None, bank, card))

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return False

        decisions = {row[0].transaction_id: [SimpleNamespace(label='MEMBERSHIP',
            decision='include', cleared_at=None)] for row in rows}
        with (patch('api.routes.analytics._active_month_rows', AsyncMock(return_value=rows)),
              patch('api.routes.analytics.load_label_overrides', AsyncMock(return_value=decisions)),
              patch('api.routes.analytics.SessionLocal', return_value=Session())):
            result = asyncio.run(analytics_transactions(
                month='2026-09', category=None, transaction_type=None, limit=1, offset=0,
                institution_id=None, account_id=None, label='MEMBERSHIP',
                membership_view='card_benefits'))
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['transactions'][0]['transaction_id'], 'benefit')
        self.assertEqual(result['membership_counts'],
                         {'charges': 1, 'refunds': 1, 'card_benefits': 1, 'all': 3})

    def test_confirmed_benefit_credits_follow_account_and_posting_month(self):
        amex = SimpleNamespace(institution_id='ins_10', institution_name='American Express')
        other = SimpleNamespace(institution_id='ins_other', institution_name='Other')
        platinum = account('platinum')
        platinum.name = 'Platinum Card'
        gold = account('gold')
        gold.name = 'American Express Gold Card'
        fee = transaction('fee', date(2026, 8, 5), '-13.81', 'expense', spending=True)
        fee.merchant_name = fee.description = 'Walmart'
        benefit = transaction('benefit', date(2026, 9, 5), '13.81', 'card_benefit')
        benefit.merchant_name = benefit.description = 'Walmart'
        refund = transaction('refund', date(2026, 9, 6), '2', 'refund')
        refund.description = 'IC Instacart Subscrip'
        other_benefit = transaction('dining', date(2026, 9, 7), '10', 'card_benefit')
        other_benefit.description = 'AMEX DINING CREDIT'
        rows = [(fee, False, None, amex, platinum),
                (benefit, False, None, amex, platinum),
                (refund, False, None, amex, platinum),
                (other_benefit, False, None, amex, platinum)]
        before = summarize_monthly_transactions(rows)
        summary = summarize_memberships(rows, {}, '2026-08', '2026-09', 'ytd')
        self.assertEqual(summary['overall']['gross_charges'], '13.81')
        self.assertEqual(summary['overall']['refunds'], '2.00')
        self.assertEqual(summary['overall']['card_benefits'], '13.81')
        self.assertEqual(summary['overall']['net_cost'], '-2.00')
        self.assertEqual(summary['months'][0]['net_cost'], '13.81')
        self.assertEqual(summary['months'][1]['net_cost'], '-15.81')
        self.assertEqual(summary['overall']['membership_transaction_count'], 3)
        self.assertEqual(summarize_monthly_transactions(rows), before)
        self.assertNotIn('MEMBERSHIP', label_result(other_benefit,
            institution_id=amex.institution_id, account_type='credit',
            account_name=platinum.name)['effective_labels'])
        for item, card in ((other, platinum), (amex, gold)):
            wrong = summarize_memberships([(benefit, False, None, item, card)], {},
                                           '2026-09', '2026-09', 'ytd')
            self.assertEqual(wrong['overall']['card_benefits'], '0.00')

    def test_uber_one_benefit_manual_label_and_type_precedence(self):
        amex = SimpleNamespace(institution_id='ins_10', institution_name='American Express')
        platinum = account('platinum')
        platinum.name = 'Platinum Card'
        credit = transaction('uber-credit', date(2026, 9, 3), '9.99', 'card_benefit')
        credit.description = 'PLATINUM UBER ONE CREDIT'
        rows = [(credit, False, None, amex, platinum)]
        self.assertEqual(summarize_memberships(rows, {}, '2026-09', '2026-09', 'ytd')
                         ['overall']['card_benefits'], '9.99')
        excluded = {'uber-credit': [SimpleNamespace(label='MEMBERSHIP',
            decision='exclude', cleared_at=None)]}
        self.assertEqual(summarize_memberships(rows, excluded, '2026-09', '2026-09', 'ytd')
                         ['overall']['card_benefits'], '0.00')
        excluded['uber-credit'][0].cleared_at = datetime.now()
        self.assertEqual(summarize_memberships(rows, excluded, '2026-09', '2026-09', 'ytd')
                         ['overall']['card_benefits'], '9.99')
        overridden = [(credit, False, 'refund', amex, platinum)]
        changed = summarize_memberships(overridden, {}, '2026-09', '2026-09', 'ytd')
        self.assertEqual((changed['overall']['refunds'], changed['overall']['card_benefits']),
                         ('9.99', '0.00'))

    def test_ytd_and_trailing_summary_use_the_same_period_for_all_metrics(self):
        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        old_card, current_card = account('old'), account('current')
        rows = [
            (transaction('old', date(2025, 12, 2), '-100', 'expense', spending=True),
             False, None, bank, old_card),
            (transaction('refund', date(2026, 1, 3), '20', 'refund'),
             False, None, bank, current_card),
            (transaction('charge', date(2026, 9, 4), '-30', 'expense', spending=True),
             False, None, bank, current_card),
            (transaction('benefit', date(2026, 9, 5), '5', 'card_benefit'),
             False, None, bank, current_card),
            (transaction('payment', date(2026, 9, 6), '40', 'payment', internal=True),
             False, None, bank, current_card),
            (transaction('unknown', date(2026, 9, 7), '7', None),
             False, None, bank, current_card),
        ]
        include = lambda: [SimpleNamespace(label='MEMBERSHIP', decision='include', cleared_at=None)]
        decisions = {row[0].transaction_id: include() for row in rows}
        trailing = summarize_memberships(rows, decisions, '2025-10', '2026-09')
        ytd = summarize_memberships(rows, decisions, '2026-01', '2026-09', 'ytd')
        self.assertEqual((trailing['period'], trailing['start_month'], len(trailing['months'])),
                         ('trailing_12m', '2025-10', 12))
        self.assertEqual((ytd['period'], ytd['start_month'], len(ytd['months'])),
                         ('ytd', '2026-01', 9))
        self.assertEqual(trailing['overall'], {
            'gross_charges': '130.00', 'refunds': '20.00', 'card_benefits': '5.00',
            'net_cost': '105.00', 'membership_transaction_count': 6,
            'excluded_transaction_count': 2, 'unclassified_count': 1,
        })
        self.assertEqual(ytd['overall'], {
            'gross_charges': '30.00', 'refunds': '20.00', 'card_benefits': '5.00',
            'net_cost': '5.00', 'membership_transaction_count': 5,
            'excluded_transaction_count': 2, 'unclassified_count': 1,
        })
        self.assertEqual([entry['account_id'] for entry in ytd['accounts']], ['current'])
        self.assertEqual(ytd['accounts'][0]['net_cost'], '5.00')
        self.assertEqual(ytd['months'][0]['month'], '2026-01')
        self.assertEqual(ytd['months'][-1]['month'], '2026-09')
        self.assertEqual(sum(Decimal(month['net_cost']) for month in ytd['months']), Decimal('5'))

    def test_membership_endpoint_defaults_to_trailing_and_queries_ytd_bounds(self):
        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        with (
            patch('api.routes.analytics._active_analytics_rows', AsyncMock(return_value=[])) as active_rows,
            patch('api.routes.analytics.load_label_overrides', AsyncMock(return_value={})),
            patch('api.routes.analytics.SessionLocal', return_value=Session()),
        ):
            trailing = asyncio.run(membership_costs('2026-09'))
            active_rows.assert_awaited_with(date(2025, 10, 1), date(2026, 9, 30))
            ytd = asyncio.run(membership_costs('2026-09', 'ytd'))
            active_rows.assert_awaited_with(date(2026, 1, 1), date(2026, 9, 30))
            january = asyncio.run(membership_costs('2026-01', 'ytd'))
            active_rows.assert_awaited_with(date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual((trailing['start_month'], len(trailing['months'])), ('2025-10', 12))
        self.assertEqual((ytd['start_month'], len(ytd['months'])), ('2026-01', 9))
        self.assertEqual((january['start_month'], len(january['months'])), ('2026-01', 1))
        with self.assertRaises(HTTPException) as invalid:
            asyncio.run(membership_costs('2026-09', 'custom'))
        self.assertEqual(invalid.exception.status_code, 422)

    def test_ytd_drilldown_excludes_prior_year_and_keeps_account_pagination(self):
        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

        bank = SimpleNamespace(institution_id='ins_test', institution_name='Test Bank')
        card = account('card')
        rows = [
            (transaction('old', date(2025, 12, 1), '-10', 'expense', spending=True),
             False, None, bank, card),
            (transaction('jan', date(2026, 1, 1), '-20', 'expense', spending=True),
             False, None, bank, card),
            (transaction('sep', date(2026, 9, 1), '-30', 'expense', spending=True),
             False, None, bank, card),
        ]
        decisions = {row[0].transaction_id: [
            SimpleNamespace(label='MEMBERSHIP', decision='include', cleared_at=None)]
            for row in rows}

        async def rows_in_range(start, end):
            return [row for row in rows if start <= row[0].transaction_date <= end]

        with (
            patch('api.routes.analytics._active_analytics_rows',
                  AsyncMock(side_effect=rows_in_range)) as active_rows,
            patch('api.routes.analytics.load_label_overrides',
                  AsyncMock(return_value=decisions)),
            patch('api.routes.analytics.SessionLocal', return_value=Session()),
        ):
            kwargs = dict(month=None, start_month='2026-01', end_month='2026-09',
                          label='MEMBERSHIP', category=None, transaction_type=None,
                          institution_id=None, account_id='card', limit=1)
            first = asyncio.run(analytics_transactions(offset=0, **kwargs))
            second = asyncio.run(analytics_transactions(offset=1, **kwargs))
            active_rows.assert_awaited_with(date(2026, 1, 1), date(2026, 9, 30))
        self.assertEqual(first['total'], 2)
        self.assertEqual(first['transactions'][0]['transaction_id'], 'sep')
        self.assertEqual(second['transactions'][0]['transaction_id'], 'jan')
        self.assertEqual(first['start_month'], '2026-01')

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
