from pathlib import Path
import tempfile
import unittest

from scripts.pft_m1_http_env import update, validate_origin


class M1RuntimeEnvTests(unittest.TestCase):
    def test_apply_and_rollback_preserve_private_contents(self):
        original = ("PLAID_SECRET=synthetic-secret\nDATABASE_URL=synthetic-url\n"
                    "PFT_STRICT_LOCAL_HTTP=true\n"
                    "PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text(original)
            path.chmod(0o600)
            update(path, "https://pft-host.tailc4d964.ts.net")
            changed = path.read_text()
            self.assertIn("PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000\n", changed)
            self.assertIn("https://pft-host.tailc4d964.ts.net\n", changed)
            self.assertIn("PLAID_SECRET=synthetic-secret\n", changed)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ValueError):
                update(path, "https://pft-host.tailc4d964.ts.net")
            update(path, "https://pft-host.tailc4d964.ts.net", rollback=True)
            self.assertEqual(path.read_text(), original)

    def test_rejects_unsafe_origin_and_public_file(self):
        for value in ("http://pc.tailnet.ts.net", "https://*.ts.net",
                      "https://pc.tailnet.ts.net:443", "https://pc.tailnet.ts.net/path",
                      "https://-pc.tailnet.ts.net", "https://evil.test"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_origin(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            path.write_text("PFT_STRICT_LOCAL_HTTP=true\n"
                            "PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000\n")
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "not private"):
                update(path, "https://pc.tailnet.ts.net")

    def test_exact_origin_replacement_preserves_other_private_lines(self):
        old = "https://randy-pc.tailc4d964.ts.net"
        new = "https://pft-host.tailc4d964.ts.net"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            original = ("PLAID_SECRET=synthetic-secret\n"
                        "PFT_STRICT_LOCAL_HTTP=true\n"
                        "PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000\n"
                        "PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000\n"
                        f"PFT_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,{old}\n")
            path.write_text(original)
            path.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "differ"):
                update(path, new, previous_origin="https://wrong.tailc4d964.ts.net")
            self.assertEqual(path.read_text(), original)
            update(path, new, previous_origin=old)
            changed = path.read_text()
            self.assertEqual(changed, original.replace(old, new))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            update(path, old, previous_origin=new)
            self.assertEqual(path.read_text(), original)


if __name__ == "__main__":
    unittest.main()
