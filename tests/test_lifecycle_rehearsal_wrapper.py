"""Rehearsal wrapper checks using synthetic files only, never a database or Plaid."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/pft_lifecycle_restore_rehearsal.sh'


class RehearsalWrapperTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='pft-wrapper-synthetic-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        scripts = self.root / 'scripts'
        scripts.mkdir()
        self.script = scripts / SCRIPT.name
        self.script.write_text(SCRIPT.read_text())
        git_env = {'PATH': os.defpath}
        subprocess.run(['git', '-C', str(self.root), 'init', '-q'], env=git_env, check=True,
                       capture_output=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Synthetic Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '--allow-empty',
                        '-qm', 'Synthetic rehearsal fixture'], env=git_env, check=True, capture_output=True)
        self.commit = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'],
                                              env=git_env, text=True).strip()
        self.source = self.root / 'backups'
        self.source.mkdir()
        self.pg = self.root / 'bin'
        self.pg.mkdir()
        # Only archive listing is invoked; no PostgreSQL server is involved.
        self.restore = self.pg / 'pg_restore'
        self.restore.write_text('#!/bin/sh\n[ "$1" = "-l" ] || exit 9\n'
                                'echo "1; 0 1 TABLE DATA public items owner"\n'
                                'echo "2; 0 2 TABLE DATA public accounts owner"\n')
        self.restore.chmod(0o700)
        self.archive = self.source / 'synthetic.dump'
        self.archive.write_bytes(b'synthetic archive fixture')
        self.manifest = self.archive.with_suffix('.json')
        self.metadata = {'created_at': '2026-10-02T00:00:00+00:00', 'kind': 'extra',
                         'size': self.archive.stat().st_size,
                         'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest(),
                         'schema_sha256': 'a' * 64, 'application_commit': self.commit,
                         'format': 'pg_dump-custom'}
        self.write_manifest()
        # Do not inherit credentials, database configuration or local env files.
        self.env = {'PATH': os.defpath, 'PFT_PYTHON': sys.executable,
                    'PFT_PG_BIN_DIR': str(self.pg), 'PFT_REHEARSAL_DIR': str(self.root / 'rehearsal'),
                    'PFT_BACKUP_SOURCE_DIR': str(self.source), 'PFT_REHEARSAL_BACKUP': str(self.archive)}

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.metadata))

    def run_step(self, step):
        return subprocess.run(['bash', str(self.script), step], env=self.env,
                              capture_output=True, text=True)

    def test_s0_creates_owned_private_directory(self):
        parent_mode = self.root.stat().st_mode
        parent_entries = set(self.root.iterdir())
        result = self.run_step('S0')
        self.assertEqual(result.returncode, 0, result.stderr)
        info = Path(self.env['PFT_REHEARSAL_DIR']).stat()
        self.assertEqual(info.st_mode & 0o7777, 0o700)
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(list(Path(self.env['PFT_REHEARSAL_DIR']).iterdir()), [])
        self.assertEqual(self.root.stat().st_mode, parent_mode)
        self.assertEqual(set(self.root.iterdir()) - parent_entries, {Path(self.env['PFT_REHEARSAL_DIR'])})

    def test_s0_missing_parent_fails_without_creating_any_directory(self):
        parent = self.root / 'missing-parent'
        self.env['PFT_REHEARSAL_DIR'] = str(parent / 'rehearsal')
        result = self.run_step('S0')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('parent must already exist', result.stderr)
        self.assertFalse(parent.exists())
        self.assertFalse(Path(self.env['PFT_REHEARSAL_DIR']).exists())

    def test_s0_refuses_symlink_without_changing_target(self):
        target = self.root / 'target'
        target.mkdir(mode=0o755)
        Path(self.env['PFT_REHEARSAL_DIR']).symlink_to(target)
        self.assertNotEqual(self.run_step('S0').returncode, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)

    def test_r1_orders_by_mtime_and_limits_to_twelve_without_reading_contents(self):
        self.manifest.unlink()
        for index in range(14):
            manifest = self.source / f'{14 - index:02}.json'
            manifest.write_text('invalid JSON must not be read')
            os.utime(manifest, (100 + index, 100 + index))
        result = self.run_step('R1')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([row['filename'] for row in rows], [f'{index:02}.json' for index in range(1, 13)])
        self.assertTrue(all(set(row) == {'filename', 'size', 'modified_at'} for row in rows))

    def test_r2_matching_checksum_and_size(self):
        before = (self.archive.read_bytes(), self.manifest.read_bytes())
        result = self.run_step('R2')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['actual_sha256'], self.metadata['sha256'])
        self.assertEqual(report['actual_size'], self.metadata['size'])
        self.assertEqual(report['table_data_count'], 2)
        self.assertEqual(before, (self.archive.read_bytes(), self.manifest.read_bytes()))

    def test_r2_checksum_mismatch(self):
        self.metadata['sha256'] = '0' * 64
        self.write_manifest()
        result = self.run_step('R2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum mismatch', result.stderr)
        self.assertEqual(result.stdout, '')

    def test_r2_size_mismatch(self):
        self.metadata['size'] += 1
        self.write_manifest()
        result = self.run_step('R2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('size mismatch', result.stderr)

    def test_r2_size_optional(self):
        del self.metadata['size']
        self.write_manifest()
        result = self.run_step('R2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)['size'])

    def assert_metadata_refused(self, field, values):
        for value in values:
            with self.subTest(field=field, value=value):
                self.metadata[field] = value
                self.write_manifest()
                result = self.run_step('R2')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('refusing:', result.stderr)

    def test_r2_invalid_timestamps(self):
        self.assert_metadata_refused('created_at', ('not-a-timestamp', '2026-02-30T00:00:00+00:00',
                                                   '2026-10-02', '2026-10-02T00:00:00',
                                                   '2026-10-02T00:00:00+01:00', 123))

    def test_r2_valid_emitted_timestamp_formats(self):
        for timestamp in ('2026-10-02T00:00:00+00:00', '2026-10-02T00:00:00.123456+00:00'):
            with self.subTest(timestamp=timestamp):
                self.metadata['created_at'] = timestamp
                self.write_manifest()
                result = self.run_step('R2')
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_r2_malformed_sha256_fields(self):
        for field in ('sha256', 'schema_sha256'):
            original = self.metadata[field]
            self.assert_metadata_refused(field, ('a' * 63, 'g' * 64, 123))
            self.metadata[field] = original

    def test_r2_invalid_recorded_size(self):
        self.assert_metadata_refused('size', ('123', 'not-a-number', -1, 1.5, True, None))

    def test_r2_malformed_application_commit(self):
        self.assert_metadata_refused('application_commit', ('arbitrary-text', 'b' * 7, 'g' * 40, 123))

    def test_r2_rejects_unknown_commit_and_non_commit_object(self):
        blob = subprocess.check_output(['git', '-C', str(self.root), 'hash-object', '-w', '--stdin'],
                                       input='synthetic blob', text=True, env={'PATH': os.defpath}).strip()
        self.assert_metadata_refused('application_commit', ('0' * 40, blob))

    def test_r2_rejects_release_label(self):
        self.assert_metadata_refused('application_commit', ('sdw-p1-a047b0f-labels-over-' + 'a' * 64,))

    def test_r2_exact_verified_label_and_source_mismatch(self):
        self.metadata['application_commit'] = ('sdw-p2-b646fb9-derivation-over-'
                                              '1d17e2b59fa4be74af41f60125f41084698049424e0b4d77376db1fe41cc74c7')
        self.write_manifest()
        # Synthetic Git responses exercise the reviewed mapping without accessing
        # real backups or depending on production image contents.
        fake_git = self.pg / 'git'
        fake_git.write_text('#!' + sys.executable + '\nimport sys\n'
                            'args=sys.argv[3:]\n'
                            'if args[0]=="diff": print("api/services/derivation.py")\n'
                            'elif args[-1].endswith("^{commit}"): print("6ac9612f97479ed96eb69be55864437652f33a00")\n'
                            'else: print("a"*40)\n')
        fake_git.chmod(0o700)
        self.env['PATH'] = str(self.pg) + os.pathsep + os.defpath
        result = self.run_step('R2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['resolved_application_commit'],
                         '6ac9612f97479ed96eb69be55864437652f33a00')
        fake_git.write_text(fake_git.read_text().replace('api/services/derivation.py', 'api/models.py'))
        self.assertNotEqual(self.run_step('R2').returncode, 0)
        self.metadata['application_commit'] += '-unknown'
        self.write_manifest()
        self.assertNotEqual(self.run_step('R2').returncode, 0)

    def test_r2_malformed_kind_or_format(self):
        for field in ('kind', 'format'):
            original = self.metadata[field]
            self.assert_metadata_refused(field, ('unsupported', 123))
            self.metadata[field] = original

    def test_r2_refuses_traversal_or_malformed_dump_path(self):
        nested = self.source / 'nested'
        nested.mkdir()
        for selected in (str(nested / '..' / self.archive.name), str(self.manifest), 'synthetic.dump'):
            with self.subTest(selected=selected):
                self.env['PFT_REHEARSAL_BACKUP'] = selected
                self.assertNotEqual(self.run_step('R2').returncode, 0)

    def test_r2_invalid_or_missing_manifest(self):
        for content in ('{', '[]', '{}', '{"sha256":"a","sha256":"b"}'):
            with self.subTest(content=content):
                self.manifest.write_text(content)
                self.assertNotEqual(self.run_step('R2').returncode, 0)
        self.manifest.unlink()
        self.assertNotEqual(self.run_step('R2').returncode, 0)

    def test_r2_refuses_dump_outside_source_or_symlink(self):
        outside = self.root / 'outside.dump'
        outside.write_bytes(self.archive.read_bytes())
        self.env['PFT_REHEARSAL_BACKUP'] = str(outside)
        self.assertNotEqual(self.run_step('R2').returncode, 0)
        self.archive.unlink()
        self.archive.symlink_to(outside)
        self.env['PFT_REHEARSAL_BACKUP'] = str(self.archive)
        self.assertNotEqual(self.run_step('R2').returncode, 0)

    def test_r2_archive_failure_does_not_print_archive_details(self):
        self.restore.write_text('#!/bin/sh\necho "private archive detail" >&2\nexit 1\n')
        result = self.run_step('R2')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('private archive detail', result.stderr)

    def test_result_json_is_private_from_creation(self):
        results = Path(self.env['PFT_REHEARSAL_DIR']) / 'results'
        results.mkdir(parents=True)
        fingerprint = dict.fromkeys(('status_counts', 'items_digest', 'table_digests',
                                     'classification_digest', 'analytics_rows',
                                     'analytics_months', 'analytics_digest'), 0)
        for name in ('before', 'before_reclassified', 'after', 'after_reclassified'):
            (results / f'{name}.json').write_text(json.dumps(fingerprint))
        result = self.run_step('R7')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((results / 'compare.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue(json.loads(result.stdout)['all_identical'])


if __name__ == '__main__':
    unittest.main()
