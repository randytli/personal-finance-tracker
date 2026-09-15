# Consumer account scope

`accounts.consumer_transactions_enabled` is a persistent domain decision.
Discovery initializes new credit/depository accounts enabled; all other or missing
types disabled. Refresh preserves the stored decision, even on type/subtype drift.
The safe discovery response includes scope and a `type_drift` list for manual review.
There is no scope-edit API in this phase.

The database default is false. Migration backfills only NULL legacy values and
never resets explicit decisions. A one-time `legacy_consumer_rows` identity snapshot,
guarded by `consumer_scope_migrations`, distinguishes retained historical rows
from new disabled-account ingestion. Migration reruns never expand the snapshot.
Neither migration deletes financial data.

Discover accounts before Item-level transaction sync. Known disabled accounts are
skipped, unknown/conflicting accounts abort the entire batch without saving its
cursor. Refresh account discovery before retrying unknown accounts. Enabled rows
and cursor commit atomically; disabled-only batches still advance the cursor.
Concurrent stale cursors are rejected. Responses contain accepted transaction arrays
and counts plus `skipped_disabled_counts`; absent removals are ignored.

Normalization, classification (including transfer matching), both review modes,
manual mutation scopes and all analytics queries require enabled owned accounts.
Existing disabled rows are retained but excluded. Activation requires at least one
enabled account and rejects non-grandfathered disabled rows or inconsistent ownership.
Legacy rows do not need to be deleted. A later decision to enable an account does
not recover skipped history automatically; that requires an explicitly reviewed
backfill. Investments must use a separate domain pipeline.

## Production acceptance (separate authorization required)

1. Keep Link disabled. Record all Item/account/transaction/override state,
   token/cursor and classification fingerprints, and complete monthly analytics.
2. Apply initialization to the validated production-backfill database twice.
   Verify existing consumer accounts enabled, fingerprints/counts/analytics unchanged,
   and identical legacy snapshots after the second run.
3. Call account discovery with the existing pending Robinhood item_id. Confirm
   card 4378 enabled and all four investment accounts retained disabled.
   Review any type drift or ownership errors before proceeding.
4. Explicitly sync only that Item until stable. Check accepted/skipped counts,
   history range, removals, independent cursor and zero investment consumer rows.
5. Normalize that Item and classify consumer transactions. Inspect unresolved
   transactions and legitimate cross-institution matches without forcing labels.
6. Compare existing institution data and pending-isolated analytics to baseline.
   Stop on unexpected changes. Keep Robinhood pending for separate activation approval.

## Synthetic verification

The full integration suite requires a fresh temporary PostgreSQL database on port
55439, PLAID_ENV=sandbox, PFT_CONSUMER_SYNTHETIC_TEST=1 and
PFT_CATEGORY_SYNTHETIC_TEST=1. Consumer tests use unique disposable schemas and
never call Plaid. Do not run these tests against Production.
