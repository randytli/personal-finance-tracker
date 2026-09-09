import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, text

from api.categories import MANUAL_CATEGORIES, active_category, effective_category
from api.models import Account, Item, RawTransaction, Transaction, ManualCategoryOverride
from api.routes.analytics import summarize_monthly_transactions, transaction_details
from api.routes.review import CategoryRequest, mutate_category


class CategoryTests(unittest.TestCase):
    def test_vocabulary_and_active_semantics(self):
        for category in MANUAL_CATEGORIES:
            self.assertEqual(CategoryRequest(category=category).category, category)
        with self.assertRaises(ValidationError):
            CategoryRequest(category='MEMBERSHIP')
        transaction = SimpleNamespace(plaid_category='ENTERTAINMENT')
        override = SimpleNamespace(category='GENERAL_MERCHANDISE', cleared_at=None)
        self.assertEqual(effective_category(transaction, override), 'GENERAL_MERCHANDISE')
        override.cleared_at = datetime.now()
        self.assertIsNone(active_category(override))
        transaction.plaid_category = 'TRAVEL'
        self.assertEqual(effective_category(transaction, override), 'TRAVEL')

    def test_category_movement_preserves_metrics_and_type(self):
        for kind, amount in [('expense', '-12.34'), ('refund', '12.34')]:
            transaction = SimpleNamespace(transaction_id='t', transaction_date=date(2026, 8, 1),
                amount=Decimal(amount), plaid_category='ENTERTAINMENT', transaction_type=kind,
                is_spending=kind == 'expense', is_internal_transfer=False,
                merchant_name=None, description='Synthetic')
            override = SimpleNamespace(category='GENERAL_MERCHANDISE', cleared_at=None)
            before = summarize_monthly_transactions([(transaction, False)])
            rows = [(transaction, False, None, None, None, override)]
            after = summarize_monthly_transactions(rows)
            for key in before:
                if key != 'category_breakdown':
                    self.assertEqual(before[key], after[key])
            self.assertEqual(after['category_breakdown'][0]['category'], 'GENERAL_MERCHANDISE')
            self.assertEqual(transaction_details(rows, 'ENTERTAINMENT', kind), [])
            self.assertEqual(len(transaction_details(rows, 'GENERAL_MERCHANDISE', kind)), 1)
            self.assertEqual(transaction.plaid_category, 'ENTERTAINMENT')


@unittest.skipUnless(os.environ.get('PFT_CATEGORY_SYNTHETIC_TEST') == '1', 'isolated PostgreSQL opt-in')
class CategoryDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_migration_api_normalization_and_reclassification(self):
        from api.db import engine, init_db, SessionLocal
        from api.routes.plaid import normalize_transactions, classify_transactions
        # Explicit guard: this integration test must never target Production.
        self.assertEqual(engine.url.port, 55439)
        self.assertNotEqual(os.environ.get('PLAID_ENV'), 'production')
        await init_db()
        async with SessionLocal() as db:
            async with db.begin():
                db.add(Item(item_id='synthetic', user_id='local-sandbox-user', institution_id='ins_test',
                    institution_name='Synthetic', status='active', access_token='synthetic-only'))
            async with db.begin():
                db.add(Account(account_id='account', item_id='synthetic', name='Test', type='credit'))
                db.add(RawTransaction(transaction_id='t', item_id='synthetic', account_id='account',
                    transaction_date=date(2026, 8, 1), payload={'amount': 12.34, 'name': 'Synthetic',
                    'personal_finance_category': {'primary': 'ENTERTAINMENT'}}))
        await normalize_transactions('synthetic')
        await classify_transactions()
        async def snapshot():
            async with engine.connect() as connection:
                return (await connection.execute(text('SELECT * FROM manual_category_overrides'))).all()
        await mutate_category('t', 'GENERAL_MERCHANDISE')
        saved = await snapshot()
        await mutate_category('t', 'GENERAL_MERCHANDISE')
        self.assertEqual(saved, await snapshot())
        await init_db()
        self.assertEqual(saved, await snapshot())
        await normalize_transactions('synthetic')
        await classify_transactions()
        self.assertEqual(saved, await snapshot())
        async with SessionLocal() as db:
            async with db.begin():
                transaction = await db.get(Transaction, 't')
                transaction.plaid_category = 'TRAVEL'
        result = await mutate_category('t', None)
        self.assertEqual(result['effective_category'], 'TRAVEL')
        cleared = await snapshot()
        await mutate_category('t', None)
        self.assertEqual(cleared, await snapshot())
        await mutate_category('t', 'GENERAL_MERCHANDISE')
        async with SessionLocal() as db:
            override = await db.get(ManualCategoryOverride, 't')
            self.assertEqual(override.created_at, saved[0].created_at)
            self.assertIsNone(override.cleared_at)
            self.assertIsNone(override.cleared_by)
            async with db.begin_nested():
                transaction = await db.get(Transaction, 't')
                transaction.is_internal_transfer = True
            await db.commit()
        with self.assertRaises(HTTPException) as error:
            await mutate_category('t', 'TRAVEL')
        self.assertEqual(error.exception.status_code, 422)
        await mutate_category('t', None)
        with self.assertRaises(HTTPException) as error:
            await mutate_category('missing', 'TRAVEL')
        self.assertEqual(error.exception.status_code, 404)
        await engine.dispose()
