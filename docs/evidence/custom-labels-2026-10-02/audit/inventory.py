import os, sys, unittest, json, collections
from pathlib import Path
sys.path.insert(0, '/home/randyli/code/pft-custom-labels')
os.environ['DATABASE_URL'] = 'postgresql+asyncpg://labels_test@127.0.0.1:55449/pft_custom_labels_tests'
os.environ['PLAID_ENV'] = 'sandbox'
os.environ['PFT_LABEL_SYNTHETIC_TEST'] = '1'
os.environ['PFT_LABEL_TEST_PORT'] = '55449'
suite = unittest.defaultTestLoader.discover('/home/randyli/code/pft-custom-labels/tests')
def walk(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): yield from walk(t)
        else: yield t
cases = list(walk(suite))
skipped = []
labels = []
for t in cases:
    method = getattr(t, t._testMethodName)
    if getattr(t.__class__, '__unittest_skip__', False) or getattr(method, '__unittest_skip__', False):
        skipped.append({'id': t.id(), 'reason': getattr(t.__class__, '__unittest_skip_why__', '') or getattr(method, '__unittest_skip_why__', '')})
    if 'test_transaction_labels.' in t.id(): labels.append(t.id())
result = {'discovery_only': True, 'feature_commit': '7180352', 'total_discovered': len(cases),
          'skipped_count': len(skipped), 'groups': dict(collections.Counter(t['id'].split('.')[0] for t in skipped)),
          'skipped_tests': skipped, 'enabled_label_tests': labels}
Path('/tmp/pft-custom-labels-qa/skip-inventory.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('skipped_tests','enabled_label_tests')}, indent=2))
