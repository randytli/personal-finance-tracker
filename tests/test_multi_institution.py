import unittest
import inspect
from types import SimpleNamespace

from api.models import Item
from api.routes.analytics import _active_analytics_rows
from api.routes.plaid import fetch_transaction_pages, get_accounts, get_transactions, item_metadata, normalize_transactions


class Response:
    def __init__(self, value): self.value = value
    def to_dict(self): return self.value


class SyncClient:
    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []
    def transactions_sync(self, request):
        self.requests.append(request.to_dict())
        return Response(self.pages.pop(0))


class MultiInstitutionTests(unittest.TestCase):
    def test_items_enforce_one_institution_per_user(self):
        names = {constraint.name for constraint in Item.__table__.constraints}
        self.assertIn("uq_items_user_institution", names)
        self.assertIn("ck_items_status", names)

    def test_each_item_starts_from_its_own_cursor(self):
        chase = SyncClient([{"added": [], "modified": [], "removed": [], "next_cursor": "chase-next", "has_more": False}])
        amex = SyncClient([{"added": [], "modified": [], "removed": [], "next_cursor": "amex-next", "has_more": False}])
        chase_result = fetch_transaction_pages(chase, "chase-token", "chase-cursor")
        amex_result = fetch_transaction_pages(amex, "amex-token", None)
        self.assertEqual(chase.requests[0]["cursor"], "chase-cursor")
        self.assertNotIn("cursor", amex.requests[0])
        self.assertEqual(chase_result[3], "chase-next")
        self.assertEqual(amex_result[3], "amex-next")

    def test_active_analytics_query_filters_item_status(self):
        constants = _active_analytics_rows.__code__.co_consts
        self.assertIn("active", constants)

    def test_sync_and_normalization_require_item_id(self):
        for endpoint in (get_accounts, get_transactions, normalize_transactions):
            parameter = inspect.signature(endpoint).parameters["item_id"]
            self.assertTrue(parameter.default.is_required())

    def test_item_metadata_never_exposes_access_token_or_cursor(self):
        metadata = item_metadata(SimpleNamespace(
            item_id="item", institution_id="ins_56", institution_name="Chase",
            status="active", created_at=None, updated_at=None,
            access_token="secret", transactions_cursor="cursor",
        ))
        self.assertNotIn("access_token", metadata)
        self.assertNotIn("transactions_cursor", metadata)


if __name__ == "__main__":
    unittest.main()
