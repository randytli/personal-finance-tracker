"""Synthetic Plaid client driven by database fixture rows (M5 cron acceptance).

Never performs network I/O. Each Item's behaviour comes from one
``pft_m5_cron.fixture_plan`` row read at the start of the delivery:

- ``noop``: one empty page, cursor unchanged.
- ``pages``: ``pages`` pages of ``rows_per_page`` added rows for the current
  ``generation``. Cursors and transaction IDs are deterministic, so a retry
  from the original cursor (after a rollback or a pagination restart) sees the
  same rows; once the last page's cursor is stored the Item is a no-op again.
- ``mutation``: like ``pages``, but page 2 raises
  TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION for the first ``failures``
  attempts of this delivery (sync_all restarts at most twice).
- ``plaid_error``: every call raises INSTITUTION_DOWN.
- ``slow``: like ``pages``, sleeping ``delay_s`` in the SDK thread per page.

The event-loop hang used to force platform termination lives in the app,
not here: it must block publication, which this client cannot reach.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import json
import threading
import time

import plaid

MODES = {"noop", "pages", "mutation", "plaid_error", "slow"}
TOKEN_PREFIX = "synthetic-token-"


@dataclass(frozen=True)
class Plan:
    item_id: str
    mode: str
    account_id: str
    pages: int = 1
    rows_per_page: int = 0
    generation: int = 0
    failures: int = 0
    delay_s: float = 0.0

    def __post_init__(self):
        if (self.mode not in MODES or not 0 <= self.pages <= 100 or not 0 <= self.rows_per_page <= 500
                or not 0 <= self.failures <= 5 or not 0 <= self.delay_s <= 60):
            raise ValueError("fixture plan out of bounds")


def _error(code):
    error = plaid.ApiException(status=400, reason="synthetic")
    error.body = json.dumps({"error_code": code, "request_id": "m5-synthetic-request"})
    return error


class Response:
    def __init__(self, value):
        self.value = value

    def to_dict(self):
        return self.value


class FixtureClient:
    """Plans are keyed by access token (``synthetic-token-<n>``)."""

    def __init__(self, plans_by_token):
        self.plans = dict(plans_by_token)
        self.calls = 0
        self.added_rows = 0
        self._mutations = {token: plan.failures for token, plan in self.plans.items()}
        self._lock = threading.Lock()

    def _prefix(self, plan):
        return f"m5cron:{plan.item_id}:g{plan.generation}:p"

    def transactions_sync(self, request, *, _request_timeout):
        data = request.to_dict()
        token = data["access_token"]
        plan = self.plans.get(token)
        if plan is None or not token.startswith(TOKEN_PREFIX):
            raise RuntimeError("Non-synthetic token rejected")
        with self._lock:
            self.calls += 1
        cursor = data.get("cursor")
        empty = {"added": [], "modified": [], "removed": [], "next_cursor": cursor,
                 "has_more": False, "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"}
        if plan.mode == "plaid_error":
            raise _error("INSTITUTION_DOWN")
        if plan.mode == "noop" or plan.pages == 0:
            return Response(empty)
        prefix = self._prefix(plan)
        if cursor == prefix + str(plan.pages):
            return Response(empty)  # This generation was already published.
        number = int(cursor.removeprefix(prefix)) + 1 if cursor and cursor.startswith(prefix) else 1
        if plan.mode == "mutation" and number == 2:
            with self._lock:
                remaining = self._mutations[token]
                self._mutations[token] = max(0, remaining - 1)
            if remaining:
                raise _error("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")
        if plan.mode == "slow" and plan.delay_s:
            time.sleep(plan.delay_s)
        added = [{
            "transaction_id": f"{prefix}{number}:r{row}", "account_id": plan.account_id,
            "date": date(2026, 9, 1) + timedelta(days=(number + row) % 28),
            "amount": 5 + (row % 50), "name": "Synthetic cron fixture", "merchant_name": "Synthetic",
            "personal_finance_category": {"primary": "GENERAL_MERCHANDISE"},
        } for row in range(plan.rows_per_page)]
        with self._lock:
            self.added_rows += len(added)
        return Response({"added": added, "modified": [], "removed": [], "next_cursor": prefix + str(number),
                         "has_more": number < plan.pages,
                         "transactions_update_status": "HISTORICAL_UPDATE_COMPLETE"})

    def accounts_get(self, request, *, _request_timeout):
        raise RuntimeError("Unexpected metadata request: fixture rows use known accounts")
