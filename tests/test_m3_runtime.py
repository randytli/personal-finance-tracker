import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock
from types import SimpleNamespace

from api import backup, backup_crypto
from scripts import pft_volume_preflight


class RuntimeBackupTests(unittest.TestCase):
    def test_wrong_database_and_host_rejected(self):
        environment = {"DATABASE_URL": "postgresql+asyncpg://u:p@db:5432/wrong",
                       "EXPECTED_DATABASE_NAME": "expected", "POSTGRES_DB": "expected"}
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                backup.connection()
        environment["DATABASE_URL"] = "postgresql+asyncpg://u:p@external:5432/expected"
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(RuntimeError, "internal db"):
                backup.connection()

    def test_interrupted_dump_keeps_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "pft-daily-prior"
            prior.with_suffix(".dump").write_bytes(b"valid prior")
            prior.with_suffix(".json").write_text("{}")
            def interrupted(command, env, stdout=None):
                stdout.write(b"incomplete")
                raise subprocess.CalledProcessError(1, command)
            with patch.object(backup, "connection", return_value=("db", [], {})), \
                 patch.object(backup, "run", side_effect=interrupted), \
                 patch.dict(os.environ, {"PFT_BACKUP_DIR": directory}):
                with self.assertRaises(subprocess.CalledProcessError):
                    backup.backup("daily")
            self.assertEqual(prior.with_suffix(".dump").read_bytes(), b"valid prior")
            self.assertTrue(prior.with_suffix(".json").exists())
            self.assertEqual(list(root.glob(".pft-incomplete-*")), [])

    def test_successful_backup_prunes_only_excess_daily_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day in range(1, 9):
                stem = root / f"pft-daily-202601{day:02d}T000000000000Z"
                stem.with_suffix(".dump").write_bytes(b"old")
                stem.with_suffix(".json").write_text("{}")
            extra = root / "pft-extra-20260101T000000000000Z"
            extra.with_suffix(".dump").write_bytes(b"keep")
            extra.with_suffix(".json").write_text("{}")
            def successful(command, env, stdout=None):
                if command[0].endswith("pg_dump"):
                    stdout.write(b"synthetic dump")
                elif "--schema-only" in command:
                    stdout.write(b"synthetic schema")
            with patch.object(backup, "connection", return_value=("db", [], {})), \
                 patch.object(backup, "run", side_effect=successful), \
                 patch.dict(os.environ, {"PFT_BACKUP_DIR": directory,
                                      "PFT_APP_COMMIT": "test-commit"}):
                backup.backup("daily")
            self.assertEqual(len(list(root.glob("pft-daily-*.json"))), 7)
            self.assertEqual(len(list(root.glob("pft-daily-*.dump"))), 7)
            self.assertTrue(extra.with_suffix(".dump").exists())

    def test_encrypted_external_copy_round_trip_and_wrong_password(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "daily.dump"
            content = b"isolated synthetic archive" * 100
            source.write_bytes(content)
            source.with_suffix(".json").write_text(json.dumps({
                "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}))
            encrypted = root / "daily.pftenc"
            recovered = root / "recovered.dump"
            with patch("getpass.getpass", side_effect=["test password", "test password"]):
                backup_crypto.encrypt(source, encrypted)
            # Whole-machine loss must not require the original sidecar file.
            source.unlink()
            source.with_suffix(".json").unlink()
            with patch("getpass.getpass", return_value="wrong"):
                with self.assertRaises(Exception):
                    backup_crypto.decrypt(encrypted, recovered)
            self.assertFalse(recovered.exists())
            with patch("getpass.getpass", return_value="test password"):
                backup_crypto.decrypt(encrypted, recovered)
            self.assertEqual(recovered.read_bytes(), content)
            self.assertEqual(json.loads(recovered.with_suffix(".json").read_text())["size"], len(content))
            self.assertEqual(list(root.glob(".pft-decrypt-*")), [])

    def test_manifest_flush_failure_does_not_prune_prior_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for day in range(1, 9):
                (root / f"pft-daily-202601{day:02d}.json").write_text("{}")
                (root / f"pft-daily-202601{day:02d}.dump").write_bytes(b"old")
            def successful(command, env, stdout=None):
                if command[0].endswith("pg_dump") or "--schema-only" in command:
                    stdout.write(b"synthetic")
            with patch.object(backup, "connection", return_value=("db", [], {})), \
                 patch.object(backup, "run", side_effect=successful), \
                 patch.dict(os.environ, {"PFT_BACKUP_DIR": directory, "PFT_APP_COMMIT": "test"}), \
                 patch.object(backup.os, "fsync", side_effect=[None, OSError("interrupted")]):
                with self.assertRaises(OSError):
                    backup.backup("daily")
            self.assertEqual(len(list(root.glob("pft-daily-202601*.json"))), 8)
            self.assertEqual(len(list(root.glob("pft-daily-202601*.dump"))), 8)


class ProductionVolumePreflightTests(unittest.TestCase):
    def test_missing_old_mount_cannot_verify_a_recreated_volume(self):
        with patch.object(pft_volume_preflight, "docker", side_effect=[json.dumps([{
            "Name": pft_volume_preflight.VOLUME, "Driver": "local"}]), ""]):
            with self.assertRaisesRegex(RuntimeError, "evidence is missing"):
                pft_volume_preflight.main()

    def test_running_old_container_blocks_reuse(self):
        container = {"Name": "/" + pft_volume_preflight.OLD_CONTAINER, "State": {"Running": True},
                     "Mounts": [{"Name": pft_volume_preflight.VOLUME, "Destination": "/var/lib/postgresql/data"}]}
        with patch.object(pft_volume_preflight, "docker", side_effect=[json.dumps([{
            "Name": pft_volume_preflight.VOLUME, "Driver": "local"}]), "old-container", json.dumps([container])]):
            with self.assertRaisesRegex(RuntimeError, "running container"):
                pft_volume_preflight.main()


class LocalOriginTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_origin_configuration_rejects_writes(self):
        from api.main import local_request_boundary
        next_handler = AsyncMock()
        request = SimpleNamespace(method="POST", headers={"host": "api:8000"})
        with patch.dict(os.environ, {"PFT_STRICT_LOCAL_HTTP": "true"}, clear=True):
            response = await local_request_boundary(request, next_handler)
        self.assertEqual(response.status_code, 403)
        next_handler.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
