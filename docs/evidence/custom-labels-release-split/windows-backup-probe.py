import asyncio, os, sys, json, uuid, tempfile, subprocess
from pathlib import Path
from datetime import date, datetime
from unittest.mock import patch
sys.path.insert(0,'/home/randyli/code/pft-custom-labels')
os.environ.update(DATABASE_URL='postgresql+asyncpg://labels_test:synthetic@127.0.0.1:55449/pft_custom_labels_tests',PLAID_ENV='sandbox',PYTHONDONTWRITEBYTECODE='1')
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.exc import IntegrityError
from api import db,backup,backup_crypto
from api.models import Item,Account,RawTransaction,Transaction,TransactionLabelDefinition,ManualTransactionLabelOverride
from api.routes import analytics,review,plaid
def no_client(*a,**k):raise AssertionError('No Plaid clients allowed')
plaid.get_client=no_client
USER='synthetic-windows-label-owner'
args=['-h','127.0.0.1','-p','55449','-U','labels_test']
env={**os.environ,'PGPASSWORD':'synthetic'}
def pg(tool,*extra):return subprocess.run(['/usr/lib/postgresql/16/bin/'+tool,*args,*extra],env=env,check=True,capture_output=True)
async def snapshot(engine):
    async with engine.connect() as c:
        names=(await c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
        rows={name:(await c.execute(text(f'SELECT to_jsonb(t)::text FROM "{name}" t ORDER BY to_jsonb(t)::text COLLATE "C"'))).scalars().all() for name in names}
        functions=(await c.execute(text("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND proname LIKE 'pft_label_%' ORDER BY proname"))).scalars().all()
        triggers=(await c.execute(text("SELECT tgname,tgenabled,pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND tgname LIKE 'pft_label_%' ORDER BY tgname"))).all()
        return rows,functions,[tuple(t) for t in triggers]
async def totals(engine):
    with patch.object(analytics,'SessionLocal',async_sessionmaker(engine)),patch.dict(os.environ,{'PLAID_PILOT_USER_ID':USER}):
        return await analytics.monthly_spending('2026-10'),await analytics.membership_costs('2026-10','ytd')
async def main():
    suffix=uuid.uuid4().hex[:12];source='pft_m3_tests_labels_'+suffix;target='pft_restore_labels_'+suffix
    pg('createdb',source)
    src=create_async_engine(db.engine.url.set(database=source));dst=create_async_engine(db.engine.url.set(database=target))
    try:
        with patch.object(db,'engine',src):await db.init_db()
        sessions=async_sessionmaker(src,expire_on_commit=False)
        async with sessions.begin() as s:
            s.add(Item(item_id='win-item',user_id=USER,institution_id='synthetic',institution_name='Synthetic',status='active',access_token='synthetic-only'))
            await s.flush();s.add(Account(account_id='win-card',item_id='win-item',name='Synthetic',type='credit',consumer_transactions_enabled=True));await s.flush()
            for tid,amount,kind in [('monitor',-100,'expense'),('mic',-30,'expense'),('refund',10,'refund')]:
                s.add(RawTransaction(transaction_id=tid,item_id='win-item',account_id='win-card',transaction_date=date(2026,10,1),payload={'synthetic':True},source='plaid'))
                await s.flush();s.add(Transaction(transaction_id=tid,account_id='win-card',transaction_date=date(2026,10,1),amount=amount,description=tid,transaction_type=kind,is_spending=amount<0))
            archived=TransactionLabelDefinition(label_id='win-archived',user_id=USER,name='Old gear',normalized_name='old gear',is_system=False,created_by=USER,updated_by=USER)
            s.add_all([archived,TransactionLabelDefinition(label_id='win-tech',user_id=USER,name='Tech',normalized_name='tech',is_system=False,created_by=USER,updated_by=USER)])
            await s.flush()
            for tid,label,decision in [('monitor','CHINA','include'),('mic','MEMBERSHIP','include'),('monitor','win-tech','include'),('mic','win-tech','include'),('mic','win-archived','include'),('monitor','win-archived',None)]:
                s.add(ManualTransactionLabelOverride(transaction_id=tid,label=label,decision=decision,cleared_at=datetime(2026,10,1) if decision is None else None,created_by=USER,updated_by=USER))
            await s.flush();archived.archived_at=datetime(2026,10,2)
        baseline=await snapshot(src);financial=await totals(src)
        with tempfile.TemporaryDirectory(prefix='pft-win-labels-') as directory,patch.dict(os.environ,{
            'DATABASE_URL':db.engine.url.set(database=source).render_as_string(hide_password=False),
            'EXPECTED_DATABASE_NAME':source,'POSTGRES_DB':source,'PFT_BACKUP_TEST_MODE':'true',
            'PFT_BACKUP_DIR':directory,'PFT_APP_COMMIT':'7180352'}):
            meta=backup.backup('extra');dump=next(Path(directory).glob('*.dump'))
            # The schema payload hashed by api.backup includes definitions/guards.
            schema=pg('pg_restore','--schema-only','-f','-',str(dump)).stdout.decode()
            assert 'CREATE TABLE public.transaction_label_definitions' in schema
            assert 'CREATE FUNCTION public.pft_label_association_guard' in schema
            assert 'CREATE TRIGGER pft_label_association_guard' in schema
            encrypted=Path(directory)/'copy.pftenc'
            with patch('getpass.getpass',return_value='synthetic-test-password'):
                backup_crypto.encrypt(dump,encrypted);dump.unlink();dump.with_suffix('.json').unlink()
                recovered=Path(directory)/'recovered.dump';backup_crypto.decrypt(encrypted,recovered)
            backup.restore(recovered,target)
        assert await snapshot(dst)==baseline
        assert await totals(dst)==financial
        with patch.object(db,'engine',dst):await db.verify_runtime_schema()
        async def rejected(sql,params=None):
            try:
                async with dst.begin() as c:await c.execute(text(sql),params or {})
            except IntegrityError:return
            raise AssertionError('Expected restored database guard rejection')
        async with dst.begin() as c:
            await c.execute(text("INSERT INTO transaction_label_definitions (label_id,user_id,name,normalized_name,is_system,created_by,updated_by) VALUES ('foreign','other-user','Foreign','foreign',false,'test','test')"))
        insert="INSERT INTO manual_transaction_label_overrides(transaction_id,label,decision,created_by,updated_by) VALUES('refund',:label,'include','test','test')"
        await rejected(insert,{'label':'foreign'});await rejected(insert,{'label':'win-archived'})
        with patch.object(review,'SessionLocal',async_sessionmaker(dst,expire_on_commit=False)),patch.dict(os.environ,{'PLAID_PILOT_USER_ID':USER}):
            result=await review.mutate_label('mic','win-archived',None);assert 'win-archived' not in result['effective_labels']
        await rejected("UPDATE manual_transaction_label_overrides SET decision='include',cleared_at=NULL WHERE transaction_id='mic' AND label='win-archived'")
        await rejected("UPDATE items SET user_id='other-user' WHERE item_id='win-item'")
        assert await totals(dst)==financial
        assert await snapshot(src)==baseline
        report={'code_input':'e63c58e22da9526e7ab8eb53b59e80a85062a095','minimal_feature_commit':'7180352',
            'backup_implementation':'unchanged Windows runtime api.backup + api.backup_crypto',
            'environment':'PostgreSQL16 local synthetic 127.0.0.1:55449; not Windows host release',
            'm5_code_imported':False,'pftenc2_recovery_without_original_dump':True,
            'tables_preserved':len(baseline[0]),'guard_functions_preserved':len(baseline[1]),
            'guard_triggers_and_enabled_states_preserved':len(baseline[2]),
            'custom_active_archived_and_cleared_associations_preserved':True,
            'schema_payload_and_manifest_cover_new_table_and_guards':bool(meta['schema_sha256']),
            'monthly_and_membership_totals_unchanged':True,'runtime_schema_passed':True,
            'restored_cross_user_archive_and_owner_guards_passed':True,'source_unchanged':True,
            'production_plaid_cloud_operations':False}
        Path('/tmp/pft-labels-windows-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:
        await src.dispose();await dst.dispose();pg('dropdb','--if-exists',target);pg('dropdb','--if-exists',source)
asyncio.run(main())
