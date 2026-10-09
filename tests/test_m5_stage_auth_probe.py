"""Staging of the M5 owner-auth probe upload directories (design §3 unit 4). No cloud calls."""
import hashlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from scripts import pft_m5_stage_auth_probe as staging

ROOT = Path(__file__).resolve().parents[1]


def sums(path):
    return dict(reversed(line.split("  ", 1)) for line in path.read_text().splitlines())


class StageTests(unittest.TestCase):
    def test_layout_requirements_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "stage"
            staging.stage(target)
            api = target / "api"
            self.assertEqual((api / "main.py").read_text(), staging.MAIN_PY)
            for relative in staging.API_SOURCES:
                self.assertEqual((api / relative).read_bytes(), (ROOT / relative).read_bytes())
            self.assertEqual(sums(api / "SHA256SUMS")["experiments/m5_cloud/auth_probe.py"],
                             hashlib.sha256((ROOT / "experiments/m5_cloud/auth_probe.py").read_bytes()).hexdigest())
            requirements = (api / "requirements.txt").read_text().splitlines()
            self.assertEqual(requirements[-2:], ["PyJWT[crypto]==2.10.1", "httpx==0.28.1"])
            self.assertFalse(any(line.lower().startswith(("plaid", "uvicorn")) for line in requirements))
            self.assertIn("BEGIN CERTIFICATE", (api / "supabase-ca.crt").read_text())
            web = target / "web"
            self.assertTrue((web / "package.json").exists() and (web / "package-lock.json").exists())
            self.assertFalse([p for p in web.rglob("*") if {"node_modules", ".next"} & set(p.parts)])
            self.assertIn("lib/forward.mjs", sums(web / "SHA256SUMS"))
            self.assertEqual(sorted(sums(web / "SHA256SUMS")), sorted(staging.WEB_FILES))

    def test_refuses_repository_or_existing_destination(self):
        with self.assertRaises(RuntimeError):
            staging.stage(ROOT / "tmp-stage")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                staging.stage(Path(directory))

    def web_source(self, directory):
        """A web source tree holding every manifest file as a placeholder."""
        root = Path(directory)
        for relative in staging.WEB_FILES:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("placeholder\n")
        return root

    def test_rejects_unlisted_web_files_before_creating_the_destination(self):
        # Env files, npm credentials, keys, logs, unlisted sources and symlinks are never uploaded.
        def write(root, relative):
            (root / relative).write_text("fake-secret-marker\n")

        def link(root, relative):
            (root / relative).unlink(missing_ok=True)
            (root / relative).symlink_to(root / "package.json")

        cases = {".env.local": write, ".npmrc": write, "lib/supabase/service.key": write,
                 "npm-debug.log": write, "lib/extra.js": write, "lib/config.js": link}
        for relative, plant in cases.items():
            with self.subTest(relative), tempfile.TemporaryDirectory() as source, \
                    tempfile.TemporaryDirectory() as directory:
                root, target = self.web_source(source), Path(directory) / "stage"
                plant(root, relative)
                with patch.object(staging, "WEB_SOURCE", root):
                    with self.assertRaisesRegex(RuntimeError, f"Rejected web file: {re.escape(relative)}$"):
                        staging.stage(target)
                self.assertFalse(target.exists())

    def test_missing_manifest_file_stops_staging(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as directory:
            root, target = self.web_source(source), Path(directory) / "stage"
            (root / "middleware.js").unlink()
            with patch.object(staging, "WEB_SOURCE", root):
                with self.assertRaisesRegex(RuntimeError, "Missing web file: middleware.js"):
                    staging.stage(target)
            self.assertFalse(target.exists())

    def test_build_directories_are_skipped(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as directory:
            root, target = self.web_source(source), Path(directory) / "stage"
            for build in ("node_modules/.bin", ".next/cache", ".vercel"):
                (root / build).mkdir(parents=True)
            (root / "node_modules/.bin/next").symlink_to(root / "package.json")
            (root / ".next/cache/data").write_text("x")
            (root / ".vercel/project.json").write_text("{}")
            with patch.object(staging, "WEB_SOURCE", root):
                staging.stage(target)
            self.assertEqual(sorted(sums(target / "web" / "SHA256SUMS")), sorted(staging.WEB_FILES))
