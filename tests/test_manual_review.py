import inspect
import unittest
from decimal import Decimal
from types import SimpleNamespace

from api.classification import (
    ALLOWED_TRANSACTION_TYPES,
    effective_classification,
    validate_manual_override,
)
from api.migrations import migrate_multi_institution
from api.models import ManualClassificationOverride
from api.routes.analytics import summarize_monthly_transactions
from api.routes.review import _review_ordering
from sqlalchemy.dialects import postgresql
from sqlalchemy import select


def transaction(
    amount,
    transaction_type=None,
    *,
    is_spending=None,
    is_internal_transfer=None,
    category="GENERAL_MERCHANDISE",
):
    return SimpleNamespace(
        transaction_id="transaction",
        transaction_date=None,
        amount=Decimal(amount),
        transaction_type=transaction_type,
        is_spending=is_spending,
        is_internal_transfer=is_internal_transfer,
        plaid_category=category,
    )


class ManualReviewTests(unittest.TestCase):
    def test_review_order_prioritizes_non_credit_then_date_and_id(self):
        statement = select(ManualClassificationOverride).order_by(*_review_ordering())
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        order_by = sql.split("ORDER BY ", 1)[1]
        self.assertIn("CASE WHEN (accounts.type = 'credit') THEN 1 ELSE 0 END", order_by)
        self.assertLess(order_by.index("CASE WHEN"), order_by.index("transactions.transaction_date"))
        self.assertLess(
            order_by.index("transactions.transaction_date"),
            order_by.index("transactions.transaction_id"),
        )

    def test_override_is_separate_one_to_one_model(self):
        self.assertTrue(ManualClassificationOverride.transaction_id.primary_key)
        self.assertTrue(ManualClassificationOverride.cleared_at.nullable)
        constraints = {
            constraint.name for constraint in ManualClassificationOverride.__table__.constraints
        }
        self.assertIn("ck_manual_override_transaction_type", constraints)

    def test_migration_is_additive_and_idempotent(self):
        source = inspect.getsource(migrate_multi_institution)
        self.assertIn("CREATE TABLE IF NOT EXISTS manual_classification_overrides", source)
        self.assertIn("CREATE INDEX IF NOT EXISTS ix_manual_overrides_updated_at", source)
        self.assertNotIn("DROP TABLE", source)
        self.assertNotIn("DELETE FROM", source)

    def test_override_wins_and_clear_restores_latest_automatic_result(self):
        value = transaction("-25", "transfer", is_spending=False)
        self.assertEqual(effective_classification(value, "expense"), ("expense", True, None))

        # A later classifier run changes only automatic fields; the override still wins.
        value.transaction_type = "payment"
        value.is_spending = False
        self.assertEqual(effective_classification(value, "expense"), ("expense", True, None))
        self.assertEqual(effective_classification(value, None), ("payment", False, None))

    def test_all_supported_types_can_override_compatible_transactions(self):
        self.assertEqual(
            ALLOWED_TRANSACTION_TYPES,
            {
                "expense",
                "refund",
                "income",
                "card_benefit",
                "payment",
                "transfer",
                "adjustment",
            },
        )
        for classification in ("refund", "income", "card_benefit", "payment", "transfer"):
            with self.subTest(classification=classification):
                self.assertIsNone(validate_manual_override(transaction("10"), classification))
        self.assertIsNone(validate_manual_override(transaction("-10"), "expense"))

    def test_adjustment_accepts_zero_positive_and_negative_amounts(self):
        for amount in ("0", "12.34", "-12.34"):
            with self.subTest(amount=amount):
                value = transaction(amount)
                self.assertIsNone(validate_manual_override(value, "adjustment"))
                self.assertEqual(
                    effective_classification(value, "adjustment"),
                    ("adjustment", False, None),
                )

    def test_adjustment_resolves_review_without_changing_analytics(self):
        value = transaction("0")
        before = summarize_monthly_transactions([(value, False, None)])
        after = summarize_monthly_transactions([(value, False, "adjustment")])
        self.assertEqual(before["unclassified_count"], 1)
        self.assertEqual(after["unclassified_count"], 0)
        for field in (
            "gross_spending",
            "refunds",
            "card_benefits",
            "net_spending",
        ):
            self.assertEqual(after[field], before[field])

    def test_adjustment_survives_classifier_change_and_clear_restores_automatic(self):
        value = transaction("0")
        self.assertEqual(effective_classification(value, "adjustment")[0], "adjustment")
        value.transaction_type = "income"
        value.is_spending = False
        self.assertEqual(effective_classification(value, "adjustment")[0], "adjustment")
        self.assertEqual(effective_classification(value, None), ("income", False, None))

    def test_sign_validation_rejects_unsafe_totals(self):
        self.assertEqual(
            validate_manual_override(transaction("10"), "expense"),
            "expense requires a negative amount",
        )
        for classification in ("refund", "income", "card_benefit"):
            with self.subTest(classification=classification):
                self.assertIn(
                    "requires a positive amount",
                    validate_manual_override(transaction("-10"), classification),
                )

    def test_internal_transfer_cannot_be_changed_into_spending(self):
        value = transaction("-10", "transfer", is_internal_transfer=True)
        self.assertIn("internal transfers", validate_manual_override(value, "expense"))
        self.assertIsNone(validate_manual_override(value, "transfer"))
        self.assertIsNone(validate_manual_override(value, "payment"))
        self.assertIn("internal transfers", validate_manual_override(value, "adjustment"))

    def test_analytics_uses_effective_override(self):
        rows = [
            (transaction("-20"), False, "expense"),
            (transaction("8"), False, "refund"),
            (transaction("5"), False, "card_benefit"),
            (transaction("100"), False, "income"),
            (transaction("-50"), False, "payment"),
            (transaction("-60"), False, "transfer"),
        ]
        result = summarize_monthly_transactions(rows)
        self.assertEqual(result["gross_spending"], "20.00")
        self.assertEqual(result["refunds"], "8.00")
        self.assertEqual(result["card_benefits"], "5.00")
        self.assertEqual(result["net_spending"], "7.00")
        self.assertEqual(result["unclassified_count"], 0)

    def test_internal_transfer_stays_excluded_even_with_override(self):
        value = transaction("-40", "transfer", is_internal_transfer=True)
        result = summarize_monthly_transactions([(value, False, "expense")])
        self.assertEqual(result["gross_spending"], "0.00")
        self.assertEqual(result["net_spending"], "0.00")

    def test_no_override_preserves_automatic_flags(self):
        value = transaction("-40", "expense", is_spending=False)
        self.assertEqual(effective_classification(value), ("expense", False, None))


if __name__ == "__main__":
    unittest.main()
