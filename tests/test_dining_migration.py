import os
import asyncio
import unittest
import uuid
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import patch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from api.db import engine as default_engine
from api import db as database
from api.categories import effective_category, MANUAL_CATEGORIES
from api.services.category_attribution import contribution
from api.services.dining_migration import prepare, change, snapshot


class DiningVocabularyTests(unittest.TestCase):
    def test_source_preserved_and_derived_dining(self):
        tx=SimpleNamespace(plaid_category='FOOD_AND_DRINK',merchant_name=None,
            transaction_type='expense',amount=Decimal('-10'),is_spending=True,is_internal_transfer=False)
        self.assertEqual(effective_category(tx),'DINING')
        self.assertEqual(contribution(tx)['canonical_category'],'DINING')
        self.assertEqual(tx.plaid_category,'FOOD_AND_DRINK')
        self.assertNotIn('FOOD_AND_DRINK',MANUAL_CATEGORIES)
        tx.plaid_category='GROCERIES'
        self.assertEqual(effective_category(tx),'GROCERIES')


    def test_obsolete_manual_and_filter_codes_rejected(self):
        from pydantic import ValidationError
        from fastapi import HTTPException
        from api.routes.review import CategoryRequest
        from api.routes.analytics import category_spending, analytics_transactions
        with self.assertRaises(ValidationError):CategoryRequest(category='FOOD_AND_DRINK')
        self.assertEqual(CategoryRequest(category='DINING').category,'DINING')
        for function in (category_spending, analytics_transactions):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(function(month='2026-08',category='FOOD_AND_DRINK'))
            self.assertEqual(error.exception.status_code,422)


@unittest.skipUnless(os.environ.get('PFT_CATEGORY_SYNTHETIC_TEST')=='1','isolated PostgreSQL opt-in')
class DiningMigrationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.assertEqual(default_engine.url.port,55439)
        self.assertNotEqual(os.environ.get('PLAID_ENV'),'production')
        self.name='pft_dining_'+uuid.uuid4().hex
        self.admin=create_async_engine(default_engine.url,isolation_level='AUTOCOMMIT')
        async with self.admin.connect() as c:await c.execute(text(f'CREATE DATABASE {self.name}'))
        self.engine=create_async_engine(default_engine.url.set(database=self.name))
        self.sessions=async_sessionmaker(self.engine,expire_on_commit=False)
        with patch.object(database,'engine',self.engine):await database.init_db()
        async with self.sessions.begin() as db:
            await db.execute(text("ALTER TABLE manual_category_overrides DROP CONSTRAINT ck_manual_category"))
            from api.categories import CATEGORY_CHECK
            old=CATEGORY_CHECK.replace("'DINING'","'FOOD_AND_DRINK'")
            await db.execute(text('ALTER TABLE manual_category_overrides ADD CONSTRAINT ck_manual_category CHECK ('+old+')'))
            await db.execute(text("INSERT INTO items(item_id,user_id,institution_id,institution_name,status,access_token) VALUES ('i','test','i','Synthetic','active','synthetic')"))
            await db.execute(text("INSERT INTO accounts(account_id,item_id,name,type,consumer_transactions_enabled) VALUES ('a','i','Synthetic','credit',true)"))
            for ident,category in [('target','FOOD_AND_DRINK'),('other','GROCERIES')]:
                await db.execute(text("INSERT INTO raw_transactions(transaction_id,item_id,account_id,transaction_date,payload) VALUES (:id,'i','a','2026-08-01','{}')"),{'id':ident})
                await db.execute(text("INSERT INTO transactions(transaction_id,account_id,transaction_date,amount,plaid_category,transaction_type,is_spending,is_internal_transfer) VALUES (:id,'a','2026-08-01',-10,'FOOD_AND_DRINK','expense',true,false)"),{'id':ident})
                await db.execute(text("INSERT INTO manual_category_overrides(transaction_id,category,created_by,updated_by) VALUES (:id,:cat,'owner','owner')"),{'id':ident,'cat':category})
        async with self.sessions() as db:self.manifest=await prepare(db)

    async def asyncTearDown(self):
        await self.engine.dispose()
        async with self.admin.connect() as c:await c.execute(text(f'DROP DATABASE {self.name}'))
        await self.admin.dispose()

    async def test_forward_reverse_and_rerun_guard(self):
        async with self.sessions.begin() as db:after=await change(db,self.manifest,user_id='test')
        self.assertEqual(after['after']['counts'],{'DINING:active':1,'GROCERIES:active':1})
        async with self.sessions.begin() as db:
            with self.assertRaises(ValueError):await change(db,self.manifest,user_id='test')
        async with self.sessions.begin() as db:restored=await change(db,after,rollback=True,user_id='test')
        self.assertEqual(restored,self.manifest['before'])

    async def test_dormant_decision_and_financial_totals_preserved(self):
        from api.routes import analytics
        async with self.sessions.begin() as db:
            await db.execute(text("UPDATE transactions SET transaction_type='transfer', is_spending=false, is_internal_transfer=true WHERE transaction_id='target'"))
        async with self.sessions() as db:
            manifest=await prepare(db)
            with patch.dict(os.environ, {'PLAID_PILOT_USER_ID':'test'}):
                rows=await analytics._active_month_rows('2026-08',db=db)
            before=analytics.summarize_monthly_transactions(rows)
        async with self.sessions.begin() as db:await change(db,manifest,user_id='test')
        async with self.sessions() as db:
            with patch.dict(os.environ, {'PLAID_PILOT_USER_ID':'test'}):
                rows=await analytics._active_month_rows('2026-08',db=db)
            after=analytics.summarize_monthly_transactions(rows)
        self.assertEqual(before,after)
        self.assertEqual(after['net_spending'],'10.00')

    async def test_cleared_row_refused(self):
        async with self.sessions.begin() as db:
            await db.execute(text("UPDATE manual_category_overrides SET cleared_at=now() WHERE transaction_id='target'"))
        async with self.sessions() as db:
            with self.assertRaises(ValueError):await prepare(db)

    async def test_changed_row_rollback_refused(self):
        async with self.sessions.begin() as db:after=await change(db,self.manifest,user_id='test')
        async with self.sessions.begin() as db:
            await db.execute(text("UPDATE manual_category_overrides SET updated_by='later-owner' WHERE transaction_id='target'"))
        async with self.sessions.begin() as db:
            with self.assertRaises(ValueError):await change(db,after,rollback=True,user_id='test')

    async def test_validation_failure_restores_ddl_and_rows(self):
        original=snapshot
        calls=0
        async def tampered(db):
            nonlocal calls
            result=await original(db);calls+=1
            if calls==2:result['overrides'][0]['updated_by']='bad-trigger'
            return result
        with self.assertRaises(ValueError):
            async with self.sessions.begin() as db:
                with patch('api.services.dining_migration.snapshot',tampered):
                    await change(db,self.manifest,user_id='test')
        async with self.sessions() as db:self.assertEqual(await snapshot(db),self.manifest['before'])

    async def test_generic_migration_refuses_legacy_rows(self):
        with self.assertRaises(RuntimeError):
            with patch.object(database,'engine',self.engine):await database.init_db()
