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
4. For the returned Amex `item_id`, call in order:
   `GET /plaid/accounts?item_id=...`, `GET /plaid/transactions?item_id=...`, and
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
   a changed ledger returns 409 and needs a new preview. `PATCH .../status`
   with `{"status":"active"}` is refused. Re-run analytics checks afterwards.

Deactivating an active Item (`/deactivation-preview`, then `/deactivate`) stops
its sync but keeps its transactions in analytics and classification; activating
it again resumes from the saved cursor. See
`docs/PFT_INSTITUTION_LIFECYCLE_DESIGN_2026-10-02.md`.

Do not call Link for Capital One, revoke/reconnect an Item, reset a cursor, or copy
rows between Items as part of this procedure.
