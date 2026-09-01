# Chase 730-day Production backfill runbook

This migration creates a replacement Plaid Item in an isolated candidate database. The current Production pilot database and Item stay unchanged until the candidate is verified. Never merge the two databases: Plaid account and transaction IDs can change when an institution is relinked.

## Local configuration

Create `.env.backend.production-backfill.local`. It is covered by the repository's `.env*.local` ignore rule. Keep all Production credentials and `PLAID_TOKEN_ENCRYPTION_KEY` only in ignored local environment files; never print or commit their values. Loss of the encryption key makes stored Production access tokens unrecoverable.

Configure the candidate file with the existing Production Plaid credentials, the same stable `PLAID_PILOT_USER_ID` and encryption key, the HTTPS OAuth redirect URI, and these candidate-specific values:

```dotenv
PLAID_ENV=production
PLAID_PILOT_LINK_ENABLED=false
PFT_BACKFILL_DB_NAME=pft_production_backfill
PFT_BACKFILL_DB_USER=<local-candidate-user>
PFT_BACKFILL_DB_PASSWORD=<local-candidate-password>
DATABASE_URL=postgresql+asyncpg://<local-candidate-user>:<local-candidate-password>@127.0.0.1:5434/pft_production_backfill
EXPECTED_DATABASE_NAME=pft_production_backfill
```

Do not replace or edit `.env.backend.production.local`; it remains the rollback configuration for the current pilot.

## Capture the current baseline

With the existing pilot in read-only use, record its Item count, account masks/types, active raw and normalized counts, transaction date range, classification counts, internal-transfer matches, and monthly analytics. Do not reset its cursor or call any write endpoint after recording the baseline.

## Create and populate the candidate

1. Start only the candidate database:
   `docker compose --env-file .env.backend.production-backfill.local --profile production-backfill up -d db-production-backfill`.
2. Start FastAPI with the candidate env. Confirm the database-name guard passes, `/ping` works, and the candidate contains zero Items. The guard must fail if this env points at `pft_production_pilot`.
3. Start the unauthenticated HTTPS tunnel needed for Plaid OAuth and register its `/plaid-oauth` redirect URI in the Plaid Dashboard.
4. Set `PLAID_PILOT_LINK_ENABLED=true`, restart FastAPI, and connect Chase exactly once. Production Link requests 730 days when Transactions is first initialized.
5. After exchange succeeds, immediately restore `PLAID_PILOT_LINK_ENABLED=false` and restart FastAPI. Confirm the candidate has exactly one Item and its stored access token starts with `fernet:v1:`.
6. Call `/plaid/accounts` and verify the expected Chase account masks/types before syncing.
7. Call `/plaid/transactions` until a complete call returns no additions, modifications, or removals. Every call must finish all `has_more` pages before its cursor is committed. Retry a sanitized transient Plaid failure without changing the stored cursor.
8. Run normalization and classification only after raw sync is stable.

## Verification and cutover

The candidate is acceptable only when:

- it has one Item and the expected Chase accounts;
- active raw and normalized counts reconcile, primary keys remain unique, and a repeated sync is stable;
- the oldest available transaction is materially older than the old approximately 90-day boundary;
- overlapping recent transactions and monthly totals reconcile with the old pilot, allowing for normal Plaid pending/posted changes;
- transaction-level sums reconcile with monthly analytics and classifications are reviewed;
- a read-only duplicate audit by account mask, date, amount, and merchant/description finds no unexplained duplicates. Never auto-delete suspected duplicates.

`days_requested=730` requests the maximum history but does not guarantee that Chase will return exactly 730 days. If history is unexpectedly short, accounts are missing, sync remains unstable, or analytics do not reconcile, reject the candidate and keep the old pilot active.

After acceptance, stop the old application and start it with the candidate env. Keep the old database volume and Plaid Item intact and offline as the rollback snapshot. Removing the old Plaid Item is a separate, explicitly approved cleanup after the retention period.

## Rollback

Stop the candidate application and restart the backend with `.env.backend.production.local`. Do not copy candidate rows into the pilot, reset either cursor, overwrite either encrypted access token, delete either database volume, or remove either Plaid Item during this migration.
