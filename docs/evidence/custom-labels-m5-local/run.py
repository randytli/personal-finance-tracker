import os,sys,unittest,json,socket
from pathlib import Path
root=Path('/home/randyli/code/pft-labels-m5-candidate')
sys.path[:0]=[str(root),str(root/'tests')]
os.environ.update(DATABASE_URL='postgresql+asyncpg://labels_test@127.0.0.1:55449/pft_custom_labels_tests',
                  PLAID_ENV='sandbox',PFT_M5_TRIGGER_TEST_PORT='55449',
                  PFT_M5_TRIGGER_SYNTHETIC_TEST='1',PFT_M5_BACKUP_SYNTHETIC_TEST='1',
                  PFT_AGE_BIN='/tmp/pft-labels-m5-tools/age/age')
connect=socket.socket.connect
def local(sock,address):
    if sock.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in ('127.0.0.1','localhost','::1'):
        raise AssertionError('Integration test forbids external connections')
    return connect(sock,address)
socket.socket.connect=local
from api.routes import plaid
def forbid(*args,**kwargs):raise AssertionError('No real Plaid clients in local acceptance')
plaid.get_client=forbid
names=sys.argv[1:] or [
'test_m5_backup_age.RunnerBundleTests.test_sha256sums_match_runner_files',
'test_m5_backup_age.RunnerBundleTests.test_stage_backup_repo_layout_and_fail_closed_recipients',
'test_m5_backup_age.FullChainTests.test_age_chain_with_emergency_key_only_matches_snapshot',
'test_m5_backup_age.FullChainTests.test_custom_labels_restore_startup_permissions_and_financial_totals',
'test_m5_backup_age.FullChainTests.test_fingerprint_detects_function_and_trigger_loss_modification_and_disable',
'test_m5_backup_age.FullChainTests.test_write_committed_during_dump_is_in_neither_dump_nor_fingerprint',
'test_m5_cron_adapter.SettingsAndPackagingTests.test_bundle_has_one_entrypoint_and_no_financial_app',
'test_m5_cron_adapter.CronAdapterDatabaseTests.test_migration_copies_fixture_and_grants_only_jobs',
'test_m5_cron_adapter.CronAdapterDatabaseTests.test_label_schema_jobs_role_startup_and_synthetic_tick',
]
out=Path('/tmp/pft-labels-m5-acceptance');out.mkdir(exist_ok=True)
class Result(unittest.TextTestResult):
    passed=[]
    def addSuccess(self,test):super().addSuccess(test);self.passed.append(test.id())
with (out/'tests.txt').open('w') as log:
    r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromNames(names))
report={'inputs':{'custom_labels':'e63c58e22da9526e7ab8eb53b59e80a85062a095','m5':'97c8ba33fb9e790dabcd16226879907e249069cb'},
        'database':'127.0.0.1:55449 (synthetic only)','external_calls':False,
        'run':r.testsRun,'passed':r.passed,'skips':[(t.id(),s) for t,s in r.skipped],
        'failures':[(t.id(),s) for t,s in r.failures],'errors':[(t.id(),s) for t,s in r.errors]}
(out/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print((out/'tests.txt').read_text())
sys.exit(not r.wasSuccessful())
