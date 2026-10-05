import os, sys, json, unittest, hashlib, socket
from pathlib import Path

ROOT=Path('/home/randyli/code/pft-custom-labels')
OUT=Path('/tmp/pft-custom-labels-qa/audit')
OUT.mkdir(parents=True, exist_ok=True)
selections=[
'test_category_overrides.CategoryDatabaseTests.test_migration_api_normalization_and_reclassification',
'test_consumer_scope.ConsumerDatabaseTests.test_legacy_migration_preserves_rows_and_decisions',
'test_consumer_scope.ConsumerDatabaseTests.test_ownership_and_disabled_transfer_counterpart',
'test_derivation_writes.DerivationWriteTests.test_diff_writes_match_full_rewrite_across_sync_scenarios',
'test_dining_migration.DiningMigrationDatabaseTests.test_dormant_decision_and_financial_totals_preserved',
'test_dining_migration.DiningMigrationDatabaseTests.test_validation_failure_restores_ddl_and_rows',
'test_m3_recovery.RecoveryDatabaseTests.test_populated_encrypted_backup_recovers_without_source_files',
'test_m3_recovery.RecoveryDatabaseTests.test_schema_check_rejects_missing_override_table_and_m2_column',
'test_m4_jobs.JobsDatabaseTests.test_m4_upgrade_preserves_m2_state_and_is_idempotent',
'test_statement_persistence.StatementDatabaseTests.test_migration_with_existing_import_and_overrides',
'test_statement_persistence.StatementDatabaseTests.test_apply_rerun_override_rollback_and_analytics',
'test_sync_all.SyncAllDatabaseTests.test_migration_preserves_existing_cursor_and_is_idempotent',
]
sources={}
for module in sorted({x.split('.')[0] for x in selections}):
    path=ROOT/'tests'/f'{module}.py'
    source=path.read_text()
    sources[module]={'sha256':hashlib.sha256(source.encode()).hexdigest(),
                     'harness_only_change':'test port assertion 55439 -> dedicated 55449',
                     'substitutions':source.count('55439')}
    (OUT/f'{module}.py').write_text(source.replace('55439','55449'))
sys.path[:0]=[str(OUT),str(ROOT),str(ROOT/'tests')]
os.environ['DATABASE_URL']='postgresql+asyncpg://labels_test@127.0.0.1:55449/pft_custom_labels_tests'
os.environ['PLAID_ENV']='sandbox'
for name in ['CATEGORY','CONSUMER','SYNC','M3','M4','STATEMENT']:
    os.environ[f'PFT_{name}_SYNTHETIC_TEST']='1'
original_connect=socket.socket.connect
def local_connect(sock,address):
    if sock.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in ('127.0.0.1','localhost','::1'):
        raise AssertionError('Audit forbids external connections')
    return original_connect(sock,address)
socket.socket.connect=local_connect
from api.routes import plaid
def forbidden_client(*args,**kwargs): raise AssertionError('Audit forbids real Plaid clients')
plaid.get_client=forbidden_client
class RecordedResult(unittest.TextTestResult):
    passed=[]
    def addSuccess(self,test): super().addSuccess(test); self.passed.append(test.id())
with (OUT/'gap-tests.log').open('w') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=RecordedResult).run(
        unittest.defaultTestLoader.loadTestsFromNames(selections))
report={'feature_commit':'7180352','run':'R2: targeted original-skipped integration gaps',
        'database':'127.0.0.1:55449/pft_custom_labels_tests','synthetic_only':True,
        'source_manifest':sources,'tests_run':result.testsRun,'passed':result.passed,
        'skipped':[(t.id(),reason) for t,reason in result.skipped],
        'failures':[(t.id(),trace) for t,trace in result.failures],
        'errors':[(t.id(),trace) for t,trace in result.errors]}
(OUT/'gap-results.json').write_text(json.dumps(report,indent=2)+'\n')
print((OUT/'gap-tests.log').read_text())
sys.exit(not result.wasSuccessful())
