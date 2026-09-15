# Statement imports

# Phase 1: database-free parsing

The `dry-run` command imports no database or Plaid application code and needs no
environment configuration or credentials. It never persists transactions. Keep real exports outside the repository;
committed fixtures contain synthetic data only.

Run from the repository root:

```sh
.venv/bin/python -m statement_imports dry-run /path/to/statement.csv --adapter robinhood-gold-card --through 2026-07-21
```

Omit --through to preview the whole export. The cutoff is inclusive and uses the
CSV Date, with no timezone inference from Time. JSON output includes eligible
date range, kind counts, signed totals, skip reasons, and safe row-indexed issues.
Exit code 2 means parsing errors (the preview may be partial); 0 permits warnings.
Output does not contain source rows, cardholder names, or per-transaction details.
Signed totals include payments and are not spending analytics.

Adapters implement StatementImportAdapter.parse(bytes, through=...) and return
Preview containing ImportedTransaction records. Canonical records contain date,
Decimal signed amount, currency, source transaction kind, merchant/description,
adapter/version, file SHA-256, CSV record number, ending physical line number,
original amount, and original header/value pairs. Source record numbers exclude
the header. Original pairs and the private source file preserve provenance; hashes
are not a deduplication policy.

The initial adapter accepts the observed Robinhood Gold Card UTF-8 export columns:
Date, Time, Cardholder, Amount, Points, Balance, Status, Type, Merchant, Description.
Column order may vary; missing/duplicate headers are errors. Additional columns
are preserved with a warning. Blank/malformed records produce errors.

Only Posted records qualify. Declined and other statuses are skipped; other statuses
raise a warning. Date must be YYYY-MM-DD. Purchase/Fee amounts must be nonnegative
and Refund/Payment amounts nonpositive; normalized amount is the negated source
amount. Zero is retained with a warning. Amounts use exact decimal arithmetic.
Unknown kinds, contradictory signs, and malformed values are not guessed.
USD is an explicit assumption/warning because this export has no currency column.

Kinds purchase/refund/payment/fee describe explicit source events. Parsing alone
does not write classifications or categories.

## Phase 2: reviewed database persistence

No UI, implicit migration, sync, activation, or Plaid calls. Database commands
require the existing backend environment and an already migrated database.
Production commands verify EXPECTED_DATABASE_NAME and require an explicit
PLAID_PILOT_USER_ID. **Do not run Production migration/apply/rollback without
separate authorization.** Implementation verification uses synthetic fixtures only.

### Preview and apply

```sh
.venv/bin/python -m statement_imports preview /private/statement.csv \
  --adapter robinhood-gold-card --account-id EXISTING_ACCOUNT_ID \
  --through 2026-07-21 --output /private/preview.json

.venv/bin/python -m statement_imports apply /private/statement.csv \
  --adapter robinhood-gold-card --account-id EXISTING_ACCOUNT_ID \
  --through 2026-07-21 --manifest /private/preview.json --confirm REVIEWED_DIGEST
```

Preview uses a repeatable-read, read-only transaction. The output manifest shows
the target institution/name/mask, row-level canonical evidence and dispositions,
source-kind classifications, advisory payment counterparts, totals, warnings, and
snapshot digest. It excludes source payloads, cardholder fields, and credentials.
Treat it as private financial data: `--output` creates a new mode-0600 file and
never overwrites one. Without `--output`, the manifest is printed to stdout.
Do not commit manifests or real exports.

Read the full manifest before copying its digest. Confirmation explicitly
acknowledges the target and parser warnings, including the USD assumption.
Only USD persistence is supported; no exchange-rate conversion is performed.
Parsing errors, unsupported currency, ambiguity, and changed account eligibility
block the entire apply. Preview exit 2 means blockers; exit 0 permits warnings.

Targets must belong to the configured user, be consumer-enabled, and belong to a
pending/active Item. Each adapter declares compatible type/subtype pairs; the
initial adapter accepts credit/credit card. Account masks are display evidence,
never lookup keys. Repeated discovery does not change account scope.

### Identity, provenance, and conflict policy

`statement_import_batches` records account/Item/user, file hash, adapter/version,
cutoff, reviewed digest/manifest, actor/time, and applied/rolled-back state.
`statement_import_rows` preserves canonical fields, original amount/header values,
source-record and physical-line numbers, fingerprint, and disposition. Original
source evidence is stored privately in PostgreSQL, not returned by consumer APIs.
The file hash and record index identify the source file/row without storing its path.

Raw statement rows use explicit `source=statement` and a unique provenance FK.
Their namespaced `statement:<sha256>` identity derives from account, adapter,
file hash, and source record—not merchant/date/amount. Existing raw rows remain
`source=plaid`, with original IDs/payloads unchanged. A statement payload is the
canonical source record, not an invented Plaid response.

- Same account/file/adapter/settings: retry returns the existing batch, zero inserts.
- Same file with changed cutoff/version, or a rolled-back batch: blocked in Phase 2.
- Identical persisted source-row identity: duplicate.
- Different exports, including identical-looking records: possible overlaps, not
  auto-merged duplicates. Exact signed amount and currency within seven calendar
  days on the same account creates ambiguity, regardless of merchant wording.
- Raw-only Plaid rows participate in comparison. Removed/withdrawn matches,
  indistinguishable repeated CSV rows, malformed nearby evidence, and matching
  amounts with unknown currency are surfaced conservatively.

Any ambiguous row blocks every new row. Narrow the cutoff and regenerate preview
where appropriate; there is no force-import or per-row resolution option. This
window cannot prove that differently dated/valued records are unrelated. Stable
source IDs for future adapters require a separately reviewed extension; the current
CSV provides no trustworthy transaction ID.

Apply locks the user derivation scope and target Item/account, rechecks the
reviewed snapshot, and commits batch/provenance/raw/normalized rows atomically.
No existing Plaid row, override, cursor, or token is changed. A failed transaction
has no partial import. Exact retries work after a lost success response.

### Normalization, classifications, and categories

Source-dispatched normalization uses canonical signed statement amounts directly;
Plaid amounts continue to be negated. `transactions.statement_kind` preserves the
source kind for classifier reruns. Original Plaid categories remain untouched;
statement rows have no fabricated Plaid category.

Consistent nonzero statement kinds seed automatic classification:
Purchase/Fee -> expense; Refund -> refund; Payment -> payment. Zero amounts and
unknown kinds receive no seed and fall through to existing conservative rules.
Manual classification overrides still win. Existing Plaid rules are unchanged.

Categories use manual override > existing merchant rule > original Plaid category
> UNCATEGORIZED. Therefore most uncategorized statement expenses initially use
UNCATEGORIZED; existing Weee rules still apply. Spending formulas do not change.

Import classifies only its new rows. Payment-counterpart candidates are advisory;
the importer never writes existing institutions' matching flags. Normalization,
classification, import, and rollback coordinate through a per-user advisory lock.
An explicitly requested later global classifier run can reconcile counterparts.

All existing enabled-account, Item status, user, and removal filters still apply.
Pending imports are absent from active analytics. Disabled investment accounts
remain out of consumer review, classification, matching, and analytics.

### Rollback

```sh
.venv/bin/python -m statement_imports rollback-preview --batch-id BATCH_ID \
  --output /private/rollback-preview.json
.venv/bin/python -m statement_imports rollback --batch-id BATCH_ID \
  --confirm REVIEWED_ROLLBACK_DIGEST --reason 'Acceptance test rollback'
```

Rollback soft-withdraws only the batch's statement raw rows via `is_removed`.
Normalized rows, provenance, overrides, and original applied metadata remain;
rolled-back actor/time/reason are recorded. Consumer queries and later classifier
runs exclude withdrawn rows. No Plaid row is withdrawn or deleted.
Repeated rollback is a no-op; Phase 2 deliberately has no restoration operation.

Rollback previews include affected override counts. The guard fingerprints all
other user transaction classifications: if they changed after apply, rollback
blocks for separately reviewed reconciliation. This intentionally also blocks
unrelated subsequent classification changes/new transactions; Phase 2 does not
claim precise dependency tracking or silently repair counterpart flags.

### Temporary future-Plaid overlap guard

Until explicit reconciliation exists, incoming enabled-account Plaid additions or
modifications matching a live statement row by signed amount/currency within seven
days block the entire persistence transaction. Cursor remains unchanged. Missing
Plaid currency is treated conservatively as potentially matching. This is a
temporary Phase-2 restriction, not a permanent source precedence policy.
Plaid mutation/removal paths also reject statement IDs. Do not bypass the guard
or manually advance a cursor to resolve an overlap.

## Verification and separately authorized Production acceptance

Tests opt in to disposable PostgreSQL schemas on loopback port 55439 using
PFT_STATEMENT_SYNTHETIC_TEST=1; never point these tests at Production. Run the
existing category integration test in a fresh synthetic database because its
fixture is not reusable. Unit-only runs intentionally skip database integration.

Before Production acceptance, record existing data/override/classification,
token/cursor, and complete monthly-analytics fingerprints. Apply migration twice
and verify preservation. Then generate the account-targeted Robinhood 4378
preview through 2026-07-21. Expect 171 parser-eligible records, but do not assume
171 new rows until DB comparison passes. Review all warnings/conflicts first.

Only after separate write approval: apply, verify exact counts/totals and pending
analytics isolation, repeat apply with zero additions, preview rollback, and
rollback. Verify baseline financial analytics and preserved audit rows. Leave
Robinhood pending. Do not automatically restore, activate, or call Plaid.

Deployment note: the backend must be restarted after the separately authorized
migration/deployment. Startup initialization applies migrations; do not restart a
Production-configured backend as part of synthetic implementation verification.
