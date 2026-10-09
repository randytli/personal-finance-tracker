"""Run the existing suite with a fixed disposable identity and fail on skips.

Never source an env file. PostgreSQL must be a NEW disposable cluster on 55439.
"""
from contextlib import contextmanager
from http.server import HTTPServer
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import unittest
from unittest.mock import patch
from weakref import WeakSet

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_OPT_INS = {
    "PFT_CATEGORY_SYNTHETIC_TEST",
    "PFT_CONSUMER_SYNTHETIC_TEST",
    "PFT_LABEL_SYNTHETIC_TEST",
    "PFT_STATEMENT_SYNTHETIC_TEST",
    "PFT_SYNC_SYNTHETIC_TEST",
    "PFT_M3_SYNTHETIC_TEST",
    "PFT_M4_SYNTHETIC_TEST",
    "PFT_LIFECYCLE_SYNTHETIC_TEST",
}
# M5 tests are present on integration branches before they reach main.
OPT_INS = REQUIRED_OPT_INS | {
    "PFT_M5_BACKUP_SYNTHETIC_TEST",
    "PFT_M5_TRIGGER_SYNTHETIC_TEST",
}
REQUIRED_CLASSES = {
    "test_category_overrides.CategoryDatabaseTests",
    "test_consumer_scope.ConsumerDatabaseTests",
    "test_transaction_labels.LabelDatabaseTests",
    "test_statement_persistence.StatementDatabaseTests",
    "test_sync_all.SyncAllDatabaseTests",
    "test_derivation_writes.DerivationWriteTests",
    "test_dining_migration.DiningMigrationDatabaseTests",
    "test_m3_recovery.RecoveryDatabaseTests",
    "test_m4_jobs.JobsDatabaseTests",
    "test_institution_lifecycle.LifecycleDatabaseTests",
}
REQUIRED_TESTS = {
    "test_sync_all.SyncAllDatabaseTests.test_global_failure_rolls_back_every_item_and_marker",
    "test_sync_all.SyncAllDatabaseTests.test_migration_preserves_existing_cursor_and_is_idempotent",
    "test_sync_all.SyncAllDatabaseTests.test_full_active_classification_cost_on_synthetic_history",
    "test_derivation_writes.DerivationWriteTests.test_diff_writes_match_full_rewrite_across_sync_scenarios",
    "test_dining_migration.DiningMigrationDatabaseTests.test_forward_reverse_and_rerun_guard",
    "test_dining_migration.DiningMigrationDatabaseTests.test_validation_failure_restores_ddl_and_rows",
    "test_m3_recovery.RecoveryDatabaseTests.test_populated_encrypted_backup_recovers_without_source_files",
    "test_m3_recovery.RecoveryDatabaseTests.test_schema_check_rejects_missing_override_table_and_m2_column",
    "test_m4_jobs.JobsDatabaseTests.test_global_rollback_records_retry_without_publication",
}


def cases(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from cases(test)
        else:
            yield test


def discover_opt_ins(root):
    found = set()
    for path in (root / "tests").glob("test_*.py"):
        found.update(re.findall(r"PFT_[A-Z0-9_]*SYNTHETIC_TEST", path.read_text()))
    mismatch = (found - OPT_INS) | (REQUIRED_OPT_INS - found)
    if mismatch:
        raise RuntimeError(f"Update CI opt-in inventory: {mismatch}")
    return found


class Result(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = set()

    def startTest(self, test):
        self.started.add(test.id())
        super().startTest(test)


@contextmanager
def isolated_network():
    """Allow the disposable DB and live HTTP fixtures created inside this scope."""
    servers = WeakSet()
    server_bind = HTTPServer.server_bind
    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex
    loopback = {"127.0.0.1", "localhost", "::1"}

    def bind(server):
        if server.server_address[0] not in loopback:
            raise AssertionError("Test HTTP servers must bind to loopback")
        server_bind(server)
        servers.add(server)

    def guarded(original):
        def call(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                database = address[0] in loopback and address[1] == 55439
                fixture = any(server.socket.fileno() != -1 and
                              address[:2] == server.server_address[:2] for server in servers)
                if not (database or fixture):
                    raise AssertionError(f"Unmocked network connection forbidden: {address}")
            return original(sock, address)
        return call

    with patch.object(HTTPServer, "server_bind", bind), \
         patch("socket.socket.connect", guarded(connect)), \
         patch("socket.socket.connect_ex", guarded(connect_ex)):
        yield


def main():
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    # Discard inherited application settings; every value below is synthetic.
    for name in list(os.environ):
        if name.startswith(("PFT_", "PLAID_", "DATABASE_", "POSTGRES_", "EXPECTED_DATABASE")):
            del os.environ[name]
    os.environ.update({
        "DATABASE_URL": "postgresql+asyncpg://pft_ci:synthetic@127.0.0.1:55439/pft_ci_synthetic",
        "EXPECTED_DATABASE_NAME": "pft_ci_synthetic",
        "POSTGRES_DB": "pft_ci_synthetic",
        "PLAID_ENV": "sandbox",
        "PLAID_PILOT_USER_ID": "local-sandbox-user",
        "PLAID_CLIENT_ID": "synthetic-client",
        "PLAID_SECRET": "synthetic-secret",
        "PLAID_PILOT_LINK_ENABLED": "false",
        "PFT_PG_BIN_DIR": "/usr/lib/postgresql/16/bin",
        "PFT_AGE_BIN": shutil.which("age") or "",
        **{name: "1" for name in discover_opt_ins(ROOT)},
    })

    # Tests provide their own fake Plaid clients. Fail any missed SDK mock.
    with isolated_network(), \
         patch("plaid.rest.RESTClientObject.request", side_effect=AssertionError("Unmocked Plaid call forbidden")):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
        planned = {test.id() for test in cases(suite)}
        missing = REQUIRED_TESTS - planned
        missing_classes = REQUIRED_CLASSES - {ident.rsplit(".", 1)[0] for ident in planned}
        if missing or missing_classes:
            raise RuntimeError(f"Missing required tests/classes: {missing | missing_classes}")
        result = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
    summary = (
        f"backend: executed={result.testsRun - len(result.skipped)}, "
        f"failures={len(result.failures)}, errors={len(result.errors)}, skipped={len(result.skipped)}"
    )
    print(summary, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write(summary + "\n")
    return 0 if (result.wasSuccessful() and not result.skipped and result.started == planned) else 1


if __name__ == "__main__":
    sys.exit(main())
