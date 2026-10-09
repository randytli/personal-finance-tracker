"""Synthetic fixture and fail-closed checks; no database or Plaid access."""
import tempfile
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import pft_lifecycle_restore_rehearsal as rehearsal
from scripts.pft_lifecycle_restore_rehearsal import _guard, pending_fixture_rows, require_pending_invariant


class PendingRehearsalTests(unittest.TestCase):
    def test_representative_fixture_is_valid_unique_purchase_payload(self):
        rows = pending_fixture_rows('synthetic-account', 2640)
        self.assertEqual(len({row['transaction_id'] for row in rows}), 2640)
        self.assertEqual(len({row['date'].strftime('%Y-%m') for row in rows}), 26)
        self.assertTrue(all(row['account_id'] == 'synthetic-account' and row['amount'] > 0
                            and row['personal_finance_category']['primary'] == 'GENERAL_MERCHANDISE'
                            for row in rows))

    def test_failed_preservation_is_not_reported_as_success(self):
        require_pending_invariant('preservation', {'table': 'hash'}, {'table': 'hash'})
        with self.assertRaisesRegex(RuntimeError, 'Pending rehearsal invariant failed: preservation'):
            require_pending_invariant('preservation', {'table': 'changed'}, {'table': 'hash'})

    def test_guard_refuses_production_and_noncopy_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory).chmod(0o700)
            base = {'DATABASE_URL': f'postgresql+asyncpg://fixture@:55441/pft_restore_fixture?host={directory}'}
            with patch.dict('os.environ', base, clear=True):
                _guard()
            for extra in ({'PLAID_ENV': 'production'}, {'EXPECTED_DATABASE_NAME': 'anything'},
                          {'DATABASE_URL': f'postgresql+asyncpg://fixture@:55441/ordinary?host={directory}'},
                          {'DATABASE_URL': 'postgresql+asyncpg://fixture@127.0.0.1:55441/pft_restore_fixture'}):
                with self.subTest(extra=extra), patch.dict('os.environ', {**base, **extra}, clear=True):
                    with self.assertRaises(SystemExit):
                        _guard()

    def test_failure_output_does_not_expose_sql_parameters_or_rows(self):
        output = io.StringIO()
        with patch.object(rehearsal, '_guard'), patch.object(
                rehearsal, 'pending_timing', new=AsyncMock(side_effect=ValueError('private row parameters'))), \
                patch('sys.argv', ['rehearsal', 'pending-timing']), redirect_stdout(output):
            self.assertEqual(rehearsal.main(), 2)
        self.assertFalse(json.loads(output.getvalue())['passed'])
        self.assertNotIn('private row parameters', output.getvalue())
