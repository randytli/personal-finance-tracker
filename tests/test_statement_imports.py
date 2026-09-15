import csv
from datetime import date
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from statement_imports.robinhood import RobinhoodGoldCardCSV

FIXTURE = Path(__file__).parent / "fixtures" / "robinhood_gold_card_synthetic.csv"


class StatementImportTests(unittest.TestCase):
    def test_fixture_mapping_and_provenance(self):
        adapter = RobinhoodGoldCardCSV()
        data = FIXTURE.read_bytes()
        result = adapter.parse(data, through=date(2026, 7, 21))
        self.assertEqual(result.rows_read, 6)
        self.assertEqual(result.skipped, {"declined": 1, "after_through_date": 1})
        self.assertEqual([t.kind for t in result.transactions], ["purchase", "refund", "payment", "fee"])
        self.assertEqual([t.amount for t in result.transactions], list(map(Decimal, ["-20", "5", "10", "-2"])))
        self.assertEqual(result.transactions[0].merchant, "Test, Market")
        self.assertEqual(result.transactions[0].source_record, 1)
        self.assertEqual(result.transactions[0].source_line_end, 2)
        self.assertEqual(dict(result.transactions[0].source_fields)["Amount"], "20.00")
        self.assertEqual(len(result.transactions[0].source_file_sha256), 64)
        self.assertEqual(result, adapter.parse(data, through=date(2026, 7, 21)))
        self.assertEqual(result.report()["normalized_amount_total"], "-7.00")
        self.assertEqual(len(adapter.parse(data).transactions), 5)

    def parse_row(self, **changes):
        row = dict(zip(RobinhoodGoldCardCSV.headers, [
            "2026-07-21", "3:00 PM", "Synthetic", "1.00", "0", "0",
            "Posted", "Purchase", "Test", "Synthetic"]))
        row.update(changes)
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
        return RobinhoodGoldCardCSV().parse(stream.getvalue().encode())

    def test_invalid_fields_are_errors_not_guesses(self):
        for changes in ({"Amount": "NaN"}, {"Amount": "Infinity"}, {"Amount": "1.001"},
                        {"Amount": "-1"}, {"Type": "Refund"}, {"Type": "Payment"},
                        {"Type": "Other"}, {"Date": "2026-02-30"}, {"Date": "07/21/2026"}):
            with self.subTest(changes=changes):
                r = self.parse_row(**changes)
                self.assertEqual(len(r.transactions), 0)
                self.assertEqual(r.skipped["parse_error"], 1)
                self.assertEqual(len(r.errors), 1)
        self.assertEqual(len(self.parse_row(Amount="0").transactions), 1)

    def test_nonposted_and_headers(self):
        for status in ("Declined", "Pending", ""):
            self.assertEqual(len(self.parse_row(Status=status).transactions), 0)
        for data in (b"", b"Date,Amount\n2026-01-01,3", b"Date,Date\nx,x", b"\xff"):
            self.assertTrue(RobinhoodGoldCardCSV().parse(data).errors)
        self.assertEqual(len(RobinhoodGoldCardCSV().parse(b"\xef\xbb\xbf" + FIXTURE.read_bytes()).transactions), 5)

    def test_multiline_and_unknown_columns_preserved(self):
        result = self.parse_row(Description="Line one\nLine two", Extra="future")
        self.assertFalse(result.errors)
        self.assertEqual(result.transactions[0].source_line_end, 3)
        self.assertEqual(dict(result.transactions[0].source_fields)["Extra"], "future")
        self.assertIn("extra_columns", [w["code"] for w in result.warnings])

    def test_malformed_csv_and_empty_cutoff(self):
        header = ",".join(RobinhoodGoldCardCSV.headers).encode() + b"\n"
        for tail in (b'"unfinished', b"too,few\n"):
            self.assertTrue(RobinhoodGoldCardCSV().parse(header + tail).errors)
        r = RobinhoodGoldCardCSV().parse(FIXTURE.read_bytes(), through=date(2020, 1, 1))
        self.assertEqual(r.report()["date_range"], {"earliest": None, "latest": None})
        self.assertEqual(r.rows_read, sum(r.skipped.values()))

    def test_cli_without_database_or_credentials(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PLAID_", "DATABASE_", "EXPECTED_DATABASE"))}
        result = subprocess.run([sys.executable, "-m", "statement_imports", "dry-run",
            str(FIXTURE), "--adapter", "robinhood-gold-card", "--through", "2026-07-21"],
            env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["eligible_rows"], 4)
        self.assertNotIn("Synthetic User", result.stdout)
        self.assertNotIn("source_fields", result.stdout)
