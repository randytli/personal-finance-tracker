# M3 Dining local verification — 2026-09-29

Local implementation completed under the accepted migration plan and service
cutover refinement. Production migration and release remain pending authorization.

The manual/canonical vocabulary is `DINING`, label Dining. Source Plaid
`FOOD_AND_DRINK` and its classification behavior remain preserved. Effective
spending attribution translates that source code to Dining. Groceries stays
separate. Obsolete manual writes and spending-category filters return validation
errors. Existing legacy fields retain their formulas.

The explicit migration operator is `python -m scripts.pft_dining_migration`.
It requires an expected database, owner ID, private output, and a reviewed manifest
for apply/reverse. Production mutations additionally require its explicit
Production authorization flag, which is an operator guard rather than permission
in itself. This command is included in API and jobs images and never runs at
service startup. Generic schema migration refuses existing old-code override rows.

Migration evidence records complete target audit rows, exact category counts,
constraints, and SHA-256 table fingerprints. Apply updates only active target
category values; reverse targets only manifest IDs. Any unexpected row, metadata,
or unrelated-table change aborts. Atomic validation failures restore DDL and rows.
Separate durable commit and committed-state verification receipts distinguish
validated evidence from a confirmed commit. Runtime writers must remain stopped
through these checks, as required by the accepted cutover plan.

Validation:

- Fresh isolated PostgreSQL 16 database on port 55439: full backend suite,
  **265 passed, zero skipped**, all seven synthetic opt-ins enabled.
- Eight Dining tests cover source preservation, strict manual/filter vocabulary,
  forward/reverse fingerprints, rerun guards, cleared-row refusal, later-edit
  rollback refusal, failed-validation atomic rollback, generic migration refusal,
  and dormant manual decision/financial-total preservation.
- Exact CLI prepare/apply/rollback sequence passed on a disposable database;
  evidence permissions were 0600 and committed-state checks passed.
- Final matching jobs image: eight Dining tests and 20 jobs integration tests
  passed against synthetic PostgreSQL. No real Plaid calls or scheduler started.
- Frontend: 10 suites / 36 tests passed; Next.js build passed.
- Mocked rendered browser QA: 390, 768, 1440 pixels, Dining label and category
  detail interaction/footer passed; no horizontal overflow or page errors.
- Python compilation and `git diff --check` passed.

Matching local image content IDs:

| Service | Image | Content ID |
| --- | --- | --- |
| API | `pft-m3-dining-api:local` | `sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961` |
| Web | `pft-m3-dining-web:local` | `sha256:27ebccc049961a588f5fc8ced6c56bdcbe596920cdef41d2a1d4740550fb63f3` |
| Jobs | `pft-m3-dining-jobs:local` | `sha256:b1ae3322ba3ab7683d46b4026dda5f57ecd43463e8bbc1a6e4d51272ce59de6c` |

API image migration-command import/help check passed without database access.
Web was built with the same reviewed local frontend. No Production containers
were rebuilt, replaced, restarted, or stopped.

The revised Dining preview was replayed offline from the previously recorded
read-only Production snapshot (2026-09-29 19:40:01 UTC), with the approved manual
rename simulated in memory. All 25 months reconcile exactly; deployed monthly,
institution/account, and Membership totals are unchanged. Legacy category values
match after the intended rename and category sort-order change. This is historical
snapshot evidence, not a refreshed current Production count or executed migration.
Private preview tables: `/tmp/pft_dining_release_review.md` and
`/tmp/pft_dining_preview.json`. Final backend log:
`/tmp/pft-dining-release-tests.log`.

Next gate: refreshed read-only Production manifest/count/constraint audit and
reviewed forward/reverse action packet, then explicit Production migration/release
approval. Close ingress, drain and stop all affected old services before migration;
activate and verify matching API/web/jobs behind closed access before reopening
application access/writers. No mixed-version serving is permitted.
