"""Local guard/bundle checks; no provider login, DB, SDK or cloud calls."""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from experiments.m5_cloud import runtime_probe as probe
from scripts.pft_m5_prepare_cloud_bundle import check_entrypoints, stage


def environment(role="reader"):
    ref = "a" * 20
    return {"PLAID_ENV": "sandbox", "M5_PROBE_ROLE": role,
        "M5_SUPABASE_PROJECT_REF": ref, "M5_VERCEL_PROJECT_NAME": f"pft-m5-{role}-20261001",
        "DATABASE_URL": f"postgresql+asyncpg://pft_m5_{role}.{ref}:synthetic@aws-0-us-east-1.pooler.supabase.com:5432/postgres",
        "M5_DATASET_ID": "m5-" + "b" * 32, "M5_DEPLOYMENT_ID": "m5-" + "c" * 32,
        "M5_PROBE_TOKEN": "synthetic-test-capability-" + "d" * 32}


class CloudGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_settings_reject_production_credentials_and_wrong_target(self):
        env = environment()
        self.assertEqual(probe.settings(env).role, "reader")
        for key, value in (("PLAID_ENV", "production"), ("PLAID_SECRET", "forbidden"),
            ("M5_VERCEL_PROJECT_NAME", "existing-project"), ("M5_SUPABASE_PROJECT_REF", "invalid"),
            ("M5_DATASET_ID", "missing"), ("DATABASE_URL", env["DATABASE_URL"].replace(":5432/", ":6543/")),
            ("DATABASE_URL", env["DATABASE_URL"].replace("pft_m5_reader.", "postgres.")),
            ("DATABASE_URL", env["DATABASE_URL"].replace(".pooler.supabase.com", ".example.com"))):
            with self.subTest(key=key, value=value), self.assertRaises(Exception):
                probe.settings({**env, key: value})

    async def test_unauthenticated_request_cannot_initialize_db(self):
        with patch.dict("os.environ", environment(), clear=True), patch.object(probe, "settings") as config:
            for token in ("", "Bearer wrong", "Bearer \u2603"):
                request = Request({"type": "http", "headers": [(b"authorization", token.encode())]})
                with self.assertRaises(HTTPException) as rejected:
                    await probe.capability(request)
                self.assertEqual(rejected.exception.status_code, 401)
            config.assert_not_called()

    async def test_authenticated_reader_cannot_take_jobs_lock(self):
        config = probe.settings(environment())
        with patch.object(probe, "new_engine") as factory:
            with self.assertRaises(HTTPException) as rejected:
                await probe.lock_probe(config)
            self.assertEqual(rejected.exception.status_code, 403)
            factory.assert_not_called()

    async def test_identity_rejects_wrong_role_and_tls(self):
        config = probe.settings(environment())
        for row in (("postgres", "postgres", 42, True), ("postgres", "pft_m5_reader", 42, False)):
            result = type("Row", (), {"one": lambda self: row})()
            connection = type("Connection", (), {"execute": AsyncMock(return_value=result)})()
            with self.assertRaises(RuntimeError):
                await probe.identity(connection, config)

    def test_no_financial_routes_exported(self):
        paths = {route.path for route in probe.app.routes}
        self.assertEqual(paths, {"/probe/runtime", "/probe/imports", "/probe/connection", "/probe/locks"})

    async def test_import_probe_loads_role_modules_without_financial_app(self):
        for role in ("reader", "jobs"):
            env = environment(role)
            with self.subTest(role=role), patch.dict("os.environ", env):
                result = await probe.import_probe(probe.settings(env))
                self.assertTrue(result["all_ok"], result["modules"])
                modules = [entry["module"] for entry in result["modules"]]
                self.assertIn("statement_imports.persistence", modules)
                self.assertNotIn("api.main", modules)
                self.assertEqual(result["global_engine"]["checked_out"], 0)
        self.assertNotIn("api.services.sync_all", probe.ROLE_MODULES["reader"])

    def test_bundle_contains_every_probed_module(self):
        with tempfile.TemporaryDirectory(prefix="pft-m5-bundle-test-") as parent:
            names = {entry["path"] for entry in stage(Path(parent) / "bundle")["files"]}
        modules = probe.SHARED_MODULES + sum(probe.ROLE_MODULES.values(), ())
        for module in modules:
            path = module.replace(".", "/")
            with self.subTest(module=module):
                self.assertTrue({path + ".py", path + "/__init__.py"} & names)

    def test_entrypoint_guard_rejects_ambiguous_or_servable_modules(self):
        main = "from fastapi import FastAPI\napp = FastAPI()\n"
        check_entrypoints(["main.py", "api/db.py"], {"main.py": main, "api/db.py": "engine = 1\n"})
        for extra, source in (("src/app.py", "x = 1\n"), ("index.py", "x = 1\n"),
                              ("api/db.py", "app = object()\n"), ("api/jobs.py", "class handler: pass\n"),
                              ("api/x.py", "async def application(): pass\n")):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                check_entrypoints(["main.py", extra], {"main.py": main, extra: source})

    def test_bundle_excludes_runtime_env_and_public_app(self):
        with tempfile.TemporaryDirectory(prefix="pft-m5-bundle-test-") as parent:
            destination = Path(parent) / "bundle"
            result = stage(destination)
            names = {entry["path"] for entry in result["files"]}
            self.assertIn("main.py", names)
            self.assertIn("statement_imports/persistence.py", names)
            self.assertNotIn("api/main.py", names)
            self.assertFalse(any(".env" in name or name.endswith((".csv", ".dump")) for name in names))
            with self.assertRaises(RuntimeError):
                stage(destination)
