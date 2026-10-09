# Multi-institution Production runbook

The existing Chase Item is the active baseline. New Items are created as `pending`,
may be synced manually for review, and do not contribute to analytics or
published classification until explicitly activated. Never reconnect Chase.

## Connect Amex manually

1. Confirm `PLAID_PILOT_LINK_ENABLED=false` and `GET /plaid/items` returns exactly
   the expected active Chase Item (`institution_id=ins_56`). Record the existing
   counts and analytics.
2. Set `PLAID_PILOT_LINK_ENABLED=true`, restart only the API, open Link, select the
   consumer **American Express** entry inside Plaid, and complete Link once.
   Link returns the selected institution metadata; the backend rejects an existing
   institution before exchange, then independently verifies the exchanged Item's
   institution through Plaid and saves a valid new Item as `pending`.
3. Immediately set `PLAID_PILOT_LINK_ENABLED=false` and restart the API. Confirm
   `GET /plaid/items` shows Chase active and Amex pending; no token is returned.
4. For the returned Amex `item_id` (Pending only — these split onboarding calls
   refuse Active, Deactivated and Rejected Items), call in order:
   `POST /plaid/accounts?item_id=...`, `POST /plaid/transactions?item_id=...`, and
   `POST /plaid/transactions/normalize?item_id=...`. Repeat transaction sync until
   stable, then call `POST /plaid/transactions/classify`.
5. Review Amex accounts, masks, date range, raw/normalized counts, and transfer
   matches. Confirm Chase cursor/token fingerprints, counts, and analytics have not
   changed. Pending Amex data must still be absent from analytics.
6. Activate only after review, from `/plaid/items/{amex_item_id}` in the web app:
   resolve every failed pre-activation check, open **Activate**, review the
   whole-ledger impact preview, and confirm. Over the API this is
   `POST /plaid/items/{amex_item_id}/activation-preview`, then
   `POST /plaid/items/{amex_item_id}/activate` with `{"preview_digest": ...}`;
   a changed ledger returns 409 and needs a new preview. The generic
   `PATCH .../status` is retired and returns 410. Re-run analytics checks afterwards.

Pending Items never join scheduled, catch-up or normal manual sync; steps 4 and
5 are the only way they ingest. To stop onboarding, use **Cancel onboarding** on
the institution page (`POST /plaid/items/{id}/reject`). A rejected Item cannot
be activated; **Retry onboarding** (`POST /plaid/items/{id}/retry-onboarding`)
only returns it to Pending, without importing, normalizing, publishing or
activating anything, and steps 4–6 must then be repeated.

Active Items ingest only through the atomic sync. If an Active Item's account
names or masks must be refreshed, use the maintenance operation
`POST /plaid/items/{id}/maintenance/account-metadata`; it refuses any change to
the account set or account types and never imports or moves the cursor.

Deactivating an active Item (`/deactivation-preview`, then `/deactivate`) stops
its sync but keeps its transactions in analytics and classification;
reactivation (`/reactivation-preview`, then `/reactivate`) resumes from the saved
cursor. Deactivation keeps the Plaid connection by default, so Plaid keeps
billing the Item's monthly Transactions subscription. **Deactivate and
disconnect** (or **Disconnect from Plaid** on a Deactivated Item) also calls
`/item/remove`, which ends the subscription; a disconnected Item cannot be
reactivated until a reconnect flow exists.

## Lifecycle release window (M-1)

`feature/institution-lifecycle` is **not merged** until the restored-backup
rehearsal (D15, `docs/PFT_LIFECYCLE_RESTORE_REHEARSAL_PACKET_2026-10-02.md`)
has passed. After the merge, `main`'s api, jobs and backup checks refuse to start
until the lifecycle migration has run, so every step below happens in **one
window**, each command approved separately:

1. Confirm the rehearsal passed: `compare.json` reports `all_identical: true`,
   and the preview/activation timings were accepted.
2. Confirm no sync or backup is running and the next scheduled sync is at least
   two hours away. Take a fresh `extra` backup and record its manifest.
3. Merge `feature/institution-lifecycle` into `main` (owner).
4. Build the api, jobs and web images from the merged commit; do not start them.
5. Run the read-only gate against Production with the **new** image:
   `python -m api.lifecycle_preflight`. Exit 2 means stop: no Item is promoted or
   rewritten, the old images keep running, and the window ends.
6. Run the migration once with the new image: `python -m api.migrate_once`.
7. Recreate api, jobs and web **together** from the new images, never one alone.
   Verify `/sync/status`, analytics fingerprints and Item flags.
8. Do not deactivate any Item until step 7 is verified. Old images do not know
   the `deactivated` status, so a rollback after a deactivation would hide that
   institution from analytics.

Rollback before step 6 is the old images. After step 6, old images still start
(they ignore the generated columns), as long as no Item has been deactivated.

## Backups across the lifecycle migration

A backup taken **before** the migration has the old `items` shape. Check a
restored copy with
`SELECT count(*) FROM pg_attribute WHERE attrelid='items'::regclass AND attname='published'`
(0 means pre-migration), or compare the manifest's `application_commit` with the
merge commit. Then choose one path:

- **Restore with the old images.** Restore as usual (`python -m api.backup restore
  FILE pft_restore_<name>`) and run only the images pinned at that backup's
  `application_commit` (the release pins and rollback tags) against it. New images
  refuse to start on it (`verify_runtime_schema`), which is the intended fail-safe.
- **Migrate the restored copy first.** Restore into a new `pft_restore_<name>`
  database, then run, with the **new** image and its runtime env, both commands
  against that database only:

  ```sh
  sh -c 'DATABASE_URL="${DATABASE_URL%/*}/pft_restore_<name>" \
         EXPECTED_DATABASE_NAME=pft_restore_<name> python -m api.lifecycle_preflight'
  sh -c 'DATABASE_URL="${DATABASE_URL%/*}/pft_restore_<name>" \
         EXPECTED_DATABASE_NAME=pft_restore_<name> python -m api.migrate_once'
  ```

  The URL is derived inside the container, so credentials are never printed.
  If the preflight exits 2, the backup contains non-active Items: do not migrate
  it; use the old-images path or resolve those Items by an explicit owner decision.
  Only after `migrate_once` succeeds may new images use the restored database.

A backup taken **after** the migration restores directly for the new images.
With old images it works only while no Item is Deactivated.

See `docs/PFT_INSTITUTION_LIFECYCLE_DESIGN_2026-10-02.md`.

Do not call Link for Capital One, revoke/reconnect an Item, reset a cursor, or copy
rows between Items as part of this procedure.
