# Custom transaction labels

Implemented on `feature/custom-labels`, based on main `47183eb`, in the independent
`~/code/pft-custom-labels` worktree. No Production access, Plaid calls, deployment,
main merge, or edits to M5-owned files were performed.

## Behavior and compatibility

- Create labels with a trimmed name (1–80 characters), case-insensitive per-user
  uniqueness, and optional existing badge colors. `china` and `membership` are
  reserved. Archived names remain reserved until the label is renamed.
- Existing Labels editors support multiple labels, single and atomic bulk
  add/remove, and clearing a manual decision. Existing system label IDs `CHINA`
  and `MEMBERSHIP`, automatic rules, include/exclude/restore precedence, and audit
  rows are preserved.
- Rename preserves the ID and all associations. Archive keeps historical labels
  visible/filterable, permits removal and clearing, and prohibits new includes.
  Custom restore only clears the manual decision; custom labels have no automatic
  rule, so restore never establishes an effective association. System restore keeps
  its existing automatic behavior. There is no permanent delete or unarchive.
- Overview transaction details reuse the existing label filter and net-spending
  contribution calculation. Each matching transaction contributes once regardless
  of its number of labels; totals cover the full result, before pagination.
  Narrow/coarse-pointer lists retain 10 rows per page; desktop retains 100.
- No classification, transfer/refund pairing, card benefit, or financial formula
  was changed. Review and Memberships reuse the same label controls and Sheet.

## Schema and ownership

An explicit migration creates `transaction_label_definitions` and seeds the two
system IDs. It replaces the old override-label enumeration CHECK with the named
`fk_manual_transaction_label` foreign key; existing overrides are not rewritten.
Migration is idempotent and runs through the existing `api.db.init_db` migration
path. Apply the explicit migration before starting the new binary; startup checks
require the new table/columns, enabled guards and validated FK. This work does not
execute migrations against any existing environment. Older application binaries
do not manage custom labels; a schema downgrade is not supplied.

Custom definitions use the existing pilot-user identity helper. System definitions
are global; custom definitions and APIs are owner scoped. Three PostgreSQL functions
and four triggers enforce ownership through transaction → raw transaction → Item:

- Label identity and owner are immutable; system definitions cannot be edited;
  definitions cannot be deleted or unarchived.
- Every custom decision must match the transaction's Item owner. Association
  writes lock the definition and provenance rows, so archive cannot race a new
  include. Archived decisions cannot become newly active through direct SQL.
- Item owner changes are rejected while custom label audit associations exist.
  Raw transactions may move between Items of the same owner; a move that would
  invalidate a custom label's owner is rejected, including cleared audit rows.

No ownership columns were added to financial tables and no Auth/M5/M6 work was
implemented. API label options retain `value`/`label` and add color/system/archive
metadata. Registry endpoints: GET/POST `/review/labels`, PATCH
`/review/labels/{id}`, POST `/review/labels/{id}/archive`; transaction mutation
and bulk endpoints retain their existing shapes.

## Verification (2026-10-02)

All database checks used synthetic data in a dedicated PostgreSQL 16 cluster at
`127.0.0.1:55449`. No production credentials or data were loaded.

- Python suite: **313 tests OK, 82 skipped**. Skips are other opt-in database
  scenarios not enabled for this run. Custom-label tests cover duplicate/Unicode
  names, concurrent creation/archive, isolation, direct-SQL ownership and archive
  guards, same-owner provenance movement, multi-label and atomic bulk operations,
  rename/restore audit semantics, built-in regressions, and fail-closed startup.
- Frontend: **68 tests passed in 13 suites**, including archived controls, registry
  errors, stable rename, bulk choices and mobile pagination/full-result totals.
- Legacy upgrade executed twice: historical decisions/IDs and monthly/membership
  totals remained unchanged. Synthetic dump/restore: **15 tables** had identical
  rows; **3 functions / 4 enabled triggers** survived; financial summaries matched
  and restored SQL guards rejected invalid mutations.
- Rendered browser → real API → synthetic DB flows passed at 390×844 and
  1440×1000. Review/Memberships also passed at width 768. At width 320, long names,
  registry error and empty states remained usable without horizontal overflow.
  Keyboard focus trapping and Escape worked; no page errors or external service
  calls occurred. Only deliberate error/empty states and external SDK responses
  were stubbed; label mutations used the actual API and database.
- `npm run build` and `git diff --check` passed.

Reproduce the backend checks from this worktree with an isolated PostgreSQL cluster:

```sh
DATABASE_URL=postgresql+asyncpg://labels_test@127.0.0.1:55449/pft_custom_labels_tests PLAID_ENV=sandbox PFT_LABEL_TEST_PORT=55449 PFT_LABEL_SYNTHETIC_TEST=1 PYTHONDONTWRITEBYTECODE=1 /home/randyli/code/personal-finance-tracker/.venv/bin/python -m unittest discover -s tests
npm test -- --runInBand
npm run build
```

Evidence: [browser results](evidence/custom-labels-2026-10-02/browser-results.json),
[shared-entry QA](evidence/custom-labels-2026-10-02/route-results.json),
[restore results](evidence/custom-labels-2026-10-02/restore-results.json).

| UI | Phone | Desktop |
| --- | --- | --- |
| Transactions and summary | [Screenshot](evidence/custom-labels-2026-10-02/mobile-transactions.png) | [Screenshot](evidence/custom-labels-2026-10-02/desktop-transactions.png) |
| Label management | [Screenshot](evidence/custom-labels-2026-10-02/mobile-manage.png) | [Screenshot](evidence/custom-labels-2026-10-02/desktop-manage.png) |
| Existing bulk bar | [Screenshot](evidence/custom-labels-2026-10-02/mobile-bulk.png) | [Screenshot](evidence/custom-labels-2026-10-02/desktop-bulk.png) |

## M5 handoff (separate owner)

M5 was notified in its existing task; no M5 files are edited on this branch.
Restore ordering requires definitions before manual label overrides and the
existing Item/raw/transaction provenance before associations.

| Dependency | Current coverage / required M5 action |
| --- | --- |
| Backup payload | Whole-database `api/backup.py` and schema pg_dump automatically include the new table, functions and triggers. No fixed table allowlist needs expansion for those dumps. |
| Restore fingerprint | Dynamic table/column/index/constraint fingerprint covers the new table and FK. Function bodies and trigger definitions/enabled states require explicit M5 fingerprint coverage. |
| Table counts and fixtures | Model table count increases from 14 to 15. M5 owns updates to fixed assertions/fixtures and restored active/archived label plus owner-mismatch cases. |
| Runtime restore contract | Startup requires all four enabled guards and the validated FK. A restore that omits/disables them fails closed. |

M5 fingerprint/fixture changes are coordinated separately; completion is not
claimed by this feature branch. See `restore-results.json` for this feature's own
independent restore verification.
