"""The CI inventory supports main and integration branches without hiding drift."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.ci_backend_tests import REQUIRED_OPT_INS, discover_opt_ins


class CIInventoryTests(unittest.TestCase):
    def discover(self, flags):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "tests/test_fixture.py").write_text("\n".join(sorted(flags)))
            return discover_opt_ins(root)

    def test_existing_main_inventory(self):
        self.assertEqual(self.discover(REQUIRED_OPT_INS), REQUIRED_OPT_INS)

    def test_m5_inventory(self):
        flags = REQUIRED_OPT_INS | {"PFT_" + name + "_SYNTHETIC_TEST"
                                    for name in ("M5_BACKUP", "M5_TRIGGER", "M5_AUTH")}
        self.assertEqual(self.discover(flags), flags)

    def test_unknown_flag_is_rejected(self):
        unknown = "PFT_" + "UNKNOWN_SYNTHETIC_TEST"
        with self.assertRaisesRegex(RuntimeError, unknown):
            self.discover(REQUIRED_OPT_INS | {unknown})

    def test_missing_required_flag_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "PFT_LABEL_SYNTHETIC_TEST"):
            self.discover(REQUIRED_OPT_INS - {"PFT_LABEL_SYNTHETIC_TEST"})
