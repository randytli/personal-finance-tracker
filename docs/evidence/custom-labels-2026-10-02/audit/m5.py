import asyncio, os, sys, json, uuid, importlib.util, subprocess
from pathlib import Path
sys.path.insert(0,'/home/randyli/code/pft-custom-labels')
os.environ['DATABASE_URL']='postgresql+asyncpg://labels_test@127.0.0.1:55449/pft_custom_labels_tests'
os.environ['PLAID_ENV']='sandbox'
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from unittest.mock import patch
from api import db
from api.models import Base
path=Path('/home/randyli/code/pft-m5-remaining/experiments/m5_cloud/cron_fixture.py')
spec=importlib.util.spec_from_file_location('audit_m5_fixture',path)
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
async def main():
    source='labels_audit_source_'+uuid.uuid4().hex[:8]
    target='labels_audit_cron_'+uuid.uuid4().hex[:8]
    role='labels_audit_jobs_'+uuid.uuid4().hex[:8]
    admin=create_async_engine(os.environ['DATABASE_URL'])
    source_engine=create_async_engine(os.environ['DATABASE_URL'],connect_args={'server_settings':{'search_path':source}})
    target_engine=create_async_engine(os.environ['DATABASE_URL'],connect_args={'server_settings':{'search_path':target}})
    try:
        async with admin.begin() as c:
            await c.execute(text(f'CREATE SCHEMA {source}'))
            await c.execute(text(f'CREATE ROLE {role}'))
        async with source_engine.begin() as c: await c.run_sync(Base.metadata.create_all)
        sql=fixture.migration_sql('m5-'+uuid.uuid4().hex,schema=target,source=source,jobs_role=role)
        async with admin.begin() as c:
            raw=await c.get_raw_connection();await raw.driver_connection.execute(sql)
        async with target_engine.connect() as c:
            seeds=await c.scalar(text('SELECT count(*) FROM transaction_label_definitions'))
            guards=await c.scalar(text("SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=:s AND t.tgname LIKE 'pft_label_%'"),{'s':target})
        error=''
        with patch.object(db,'engine',target_engine):
            try: await db.verify_runtime_schema()
            except RuntimeError as e: error=str(e)
        assert seeds==0 and guards==0 and 'pft_label_association_guard' in error
        fingerprint=subprocess.run(['/usr/lib/postgresql/16/bin/psql','-X','-q','-v','ON_ERROR_STOP=1','-v','schemas={public}',
            '-h','127.0.0.1','-p','55449','-U','labels_test','-d','pft_custom_labels_browser_final','-f',
            '/home/randyli/code/pft-m5-remaining/deploy/backup_runner/fingerprint.sql'],capture_output=True,text=True,check=True).stdout
        assert 'table|public.transaction_label_definitions|' in fingerprint
        assert not any(line.startswith(('function|','trigger|')) for line in fingerprint.splitlines())
        result={'run':'I1: isolated composition probe; expected integration rejection',
                'feature_commit':'7180352','m5_head':'6395882','m5_fingerprint_origin_commit':'e648e4e',
                'feature_application_table_count':len(Base.metadata.tables),
                'cron_fixture_system_definitions':seeds,'cron_fixture_label_guards':guards,
                'cron_runtime_schema_rejected':error,'fingerprint_includes_definition_table':True,
                'fingerprint_includes_guard_functions_and_triggers':False,
                'production_or_external_access':False,'main_or_m5_files_modified':False}
        Path('/tmp/pft-custom-labels-qa/audit/m5-integration-results.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    finally:
        await source_engine.dispose();await target_engine.dispose()
        async with admin.begin() as c:
            await c.execute(text(f'DROP SCHEMA IF EXISTS {target} CASCADE'))
            await c.execute(text(f'DROP SCHEMA IF EXISTS {source} CASCADE'))
            await c.execute(text(f'DROP ROLE {role}'))
        await admin.dispose()
asyncio.run(main())
