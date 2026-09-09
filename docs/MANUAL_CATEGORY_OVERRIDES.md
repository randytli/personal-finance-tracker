# Manual category overrides

Transaction Details can edit categories for included effective expenses/refunds.
Allowed destinations come from `api.categories.MANUAL_CATEGORIES`; the listing API,
request validator, and database check constraint share this vocabulary.

`GET /review/categories` lists choices. `PUT /review/transactions/{id}/category-override`
accepts `{"category":"GENERAL_MERCHANDISE"}`. DELETE on the same path restores Plaid.
Responses and analytics details include original_category, override_category, and
effective_category. Original means the latest Plaid category, not an immutable snapshot.

An override is active when category is non-null and cleared_at is null. Clears retain
the row and creation metadata; reactivation removes clear metadata. Identical operations
are no-ops. The table records creation and latest update/clear metadata, not every revision.

Analytics groups and filters by effective category. Overall metrics and classification
continue unchanged; the classifier always reads the original Plaid category. Overrides
stay attached to their transaction ID and are not copied to replacement transactions.

The editor refreshes category totals and details; a moved transaction disappears from its
old category. The confirmation outside the list offers Undo to restore the previous manual
choice (or clear it). Restore Plaid always clears. Existing type overrides are independent.

Production migration and the reversible real-data acceptance write remain a separate step:
identify a user-confirmed miscategorized expense, record amount and category totals, move
it to GENERAL_MERCHANDISE, verify exact amount/count movement and unchanged overall metrics,
then clear and verify rollback. Implementation tests use synthetic data only.

The opt-in PostgreSQL integration test requires an isolated instance on port 55439 and
PFT_CATEGORY_SYNTHETIC_TEST=1; it must run against a fresh synthetic database, never Production.
