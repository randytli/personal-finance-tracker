"""M5 R13: the bucketed application function must classify exactly like the original quadratic one."""
from datetime import date, timedelta
from decimal import Decimal
import random
import unittest

from api.classification_rules import ClassificationCandidate, build_classifications
from experiments.m5_cloud.classification_quadratic_reference import build_classifications_quadratic
from scripts.pft_m5_classification_profile import synthetic_rows

CATEGORIES = ["FOOD_AND_DRINK", "GENERAL_MERCHANDISE", "TRANSFER_IN", "TRANSFER_OUT", "OTHER", None,
              "INCOME", "LOAN_PAYMENTS"]
DESCRIPTIONS = ["STORE A", "STORE A REFUND", "STORE B", "ONLINE TRANSFER", None, "Z",
                "ZELLE PAYMENT CONF# ABCD1234", "ZELLE PAYMENT CONF# ABCD1234 TO X", "INTEREST PAID"]


def collision_rows(seed, n=400):
    """Few accounts, amounts, dates and texts, so candidates collide often."""
    rng = random.Random(seed)
    rows = []
    for index in range(n):
        amount = Decimal(rng.choice(["10", "10.0", "10.00", "25.5", "0", "7.25"]))
        if rng.random() < 0.6:
            amount = -amount
        rows.append(ClassificationCandidate(
            transaction_id=f"c-{index}", item_id="item", account_id=rng.choice(["a", "b", "c"]),
            transaction_date=date(2026, 1, 1) + timedelta(days=rng.randrange(20)), amount=amount,
            merchant_name=rng.choice([None, "STORE A", "STORE B"]), description=rng.choice(DESCRIPTIONS),
            plaid_category=rng.choice(CATEGORIES), statement_kind=None))
    manual = {row.transaction_id: rng.choice(["transfer", "expense", "payment"])
              for row in rows if rng.random() < 0.05}
    return rows, manual


class BucketedClassificationEquivalenceTests(unittest.TestCase):
    def test_synthetic_ledger_sizes_and_seeds(self):
        for seed in range(5):
            for n in (500, 3000):
                rows = synthetic_rows(n, seed=seed)
                with self.subTest(seed=seed, n=n):
                    self.assertEqual(build_classifications_quadratic(rows), build_classifications(rows))

    def test_colliding_amounts_dates_texts_and_manual_types(self):
        for seed in range(40):
            rows, manual = collision_rows(seed)
            kwargs = {"credit_account_ids": frozenset({"a"}), "active_manual_types": manual}
            with self.subTest(seed=seed):
                self.assertEqual(build_classifications_quadratic(rows, **kwargs),
                                 build_classifications(rows, **kwargs))


if __name__ == "__main__":
    unittest.main()
