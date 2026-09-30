# M3 Dining vocabulary migration and rollback plan

Status: owner accepted the plan and service-cutover refinement; local implementation
and isolated validation are authorized. Production migration and release remain
unexecuted and require separate authorization.

## Intended result

`DINING` is the only canonical/manual spending code for Dining. `GROCERIES`
remains separate. `DINING_CREDIT` maps to `DINING`.

Preserve Plaid/raw `FOOD_AND_DRINK` values exactly. Derived spending categories
translate that source code to `DINING`, after active manual and merchant-rule
precedence. Source classification and refund-matching rules continue to recognize
the original Plaid vocabulary. This migration changes a category name, not
transaction classification, monetary eligibility, account attribution, or meaning.

The preceding read-only Production audit found 80 active manual
`FOOD_AND_DRINK` overrides, no cleared overrides retaining that code, and 573
normalized source rows with that code. These are observed counts, not execution
preconditions to assume later: refresh and review exact counts before apply.

## Compatibility and implementation scope

- Replace `FOOD_AND_DRINK` with `DINING` in `MANUAL_CATEGORIES`, the final manual
  constraint, the three dining merchant rules, frontend metadata/selectors, and
  M3 benefit attribution. Display the label `Dining`.
- Normalize source `FOOD_AND_DRINK` to derived `DINING` in effective spending
  category responses and the pure canonical contribution path. Preserve source
  fields such as `original_category` and `plaid_category`; they can still return
  `FOOD_AND_DRINK`. Reimbursements continue to require an active manual category.
- Coordinate category options, single/bulk edit validation, review results,
  legacy effective-category aggregation/filtering, and new canonical filters.
  Post-cutover manual writes and category filters use `DINING`; reject obsolete
  manual/filter code `FOOD_AND_DRINK` rather than silently returning an empty set.
  No permanent manual alias. Refresh open clients after cutover.
- Retain classification rules and classification fixtures that intentionally
  represent Plaid `FOOD_AND_DRINK`. Update effective/manual/canonical fixtures
  to `DINING` and add explicit source-to-derived compatibility coverage.
- Retain legacy API fields and their formulas. Their derived category key changes
  to `DINING`; their net still excludes benefits. This is an explicit vocabulary
  compatibility change, separate from M3's additive API fields.
- Update financial docs, the architecture plan, frontend tests, and release
  evidence consistently. The previous Food & Drink preview remains historical
  evidence; generate a new Dining preview after local validation.

## Atomic migration design

Implement a dedicated, explicitly invoked one-time migration command. Never run
this data update during runtime startup or an unrelated generic migration.
Adjust `migrate_manual_categories` so it cannot replace the constraint with the
new vocabulary before existing rows have been reviewed and converted. Fresh
synthetic databases use the final constraint directly.

Prepare and test both forward and reverse commands before requesting Production
execution. Use expected database identity, an explicit migration identifier,
bounded lock/statement timeouts, and reviewed before-state fingerprints. There is
no new persistent evidence table; keep evidence securely outside the repository.

For a future authorized maintenance window:

1. Capture service/image identities and prepare the revised API/web images and
   exact previous images for rollback. Quiesce category edits and background
   financial writers; prevent old clients from writing through the old API.
   Scheduler/sync suspension must preserve Item settings and Plaid cursors.
2. Open one database transaction. Acquire the existing consumer derivation lock
   and required table locks in the repository's established order. Lock the manual
   category table for the constraint change. Prevent concurrent financial writes
   while recording and checking the preservation baseline. Abort on timeout.
3. Reverify Production identity and the reviewed override manifest. Record counts
   by category and active/cleared state across the entire table, plus the exact
   existing constraint definition. If any cleared override still stores
   `FOOD_AND_DRINK`, abort: an active-only migration cannot satisfy a final strict
   `DINING` constraint while leaving that row unchanged. Request separate owner
   direction rather than rewriting cleared audit history.
4. Save the exact target transaction IDs and complete before rows in a private
   manifest. Drop the old category constraint inside the transaction. Update only
   `category` on those reviewed IDs where `category='FOOD_AND_DRINK'` and
   `cleared_at IS NULL`. Do not call the category-edit API: it would overwrite
   `updated_by` and `updated_at`. Inspect database triggers before implementation
   to ensure a direct update preserves every other column.
5. Add and validate the final constraint with `DINING` and without
   `FOOD_AND_DRINK`. It retains all other allowed codes and null handling.
6. Verify exact counts and row identities before commit. If N reviewed rows move,
   active old-code count becomes zero and active Dining count rises by exactly N.
   The table count stays constant. Target before/after projections differ only
   in `category`; all creation/update/clear actors and timestamps are identical.
7. Verify the financial and audit invariants below within the transaction. On
   any mismatch, roll back the whole operation, including the DDL. Save validated
   before/after evidence before attempting commit; record the commit result and
   re-read committed state. Resolve an uncertain commit by inspecting the exact
   manifest and constraint, never by blindly replaying the command.
8. Activate only the tested matching API/web versions and verify readiness before
   reopening writers. This coordinated release remains separately authorized.

The exact-state guard makes accidental reruns fail safely. A verified already
applied manifest can be reported as complete without touching rows. Any other
mixed state requires investigation.

## Evidence and financial invariants

Use stable ordering, explicit columns, exact Decimal money, and SHA-256 hashes.
Do not publish raw financial rows, transaction IDs, credentials, tokens, or cursors
in the repository. The private manifest records migration ID, code/image identity,
database identity, timestamps, exact counts, target IDs, constraint definitions,
and before/after fingerprints.

For raw and normalized transactions, classification decisions, benefit decisions,
label decisions, Items, accounts, statement/import records, and other persisted
financial tables, row counts and complete financial-row fingerprints must match.
Hash token/cursor-bearing rows without exposing their values. Preserve unrelated
manual category rows byte-for-byte; hash target rows both in full and with the
category column excluded. No classification or normalized-source row is updated.

Compare baseline and revised analytics using the same input snapshot for every
available month: monthly metrics, institution/account metrics in all modes, and
Membership monthly, YTD, and trailing-12-month outputs must match exactly.
Derived category comparisons normalize the old code to `DINING` before equality
checks. Existing categories must neither split nor merge beyond that rename.
Compare old and new M3 attribution under the same Dining rename independently
from the preserved legacy formula. All canonical component sums and net sums
must reconcile exactly, including Uncategorized and negative categories.

## Rollback

Before commit, ordinary transaction rollback restores rows and constraint.
After commit, keep writers closed until acceptance. In a separately authorized
reverse transaction, lock the same scope and require the exact recorded after
state, target rows, and schema. Drop the new constraint, change only manifest
target IDs from `DINING` back to `FOOD_AND_DRINK`, restore the exact previous
constraint, and verify the original fingerprints/counts before commit. Restore
the previous API/web images before reopening writers.

Never reverse all Dining rows: preexisting/new Dining decisions may be unrelated
to this migration. If writers have reopened, or any target row/audit field changed,
the automatic rollback must abort. New Dining rows cannot satisfy the old strict
constraint without another reviewed decision; prepare a fresh owner-reviewed
rollback plan instead of overwriting user changes or restoring a whole database.

## Required validation and approval sequence

1. Implement locally only after this plan is accepted. Test the forward/reverse
   commands against fresh synthetic PostgreSQL, including preservation of audit
   metadata, mixed categories, dormant active decisions, cleared-row refusal,
   failed validation rollback, rerun guards, and changed-row rollback refusal.
2. Run the full backend suite with all seven required PostgreSQL opt-ins and zero
   skipped required database tests. Verify canonical category summaries against
   complete paginated details and account/institution filters. Run frontend tests,
   build, and rendered mobile/desktop QA for the changed category labels.
3. Refresh the read-only Production count/constraint audit and produce the revised
   Dining preview with exact reconciliation and preservation comparisons. Review
   the generated migration manifest and forward/reverse action packet.
4. Stop for explicit Production migration/release authorization. Plan acceptance
   or local implementation approval alone does not authorize Production writes.

## Service dependency audit and cutover refinement

API imports `api.categories` directly through review/analytics and transitively
through models, database/schema verification, and migration/restore tooling. Web
uses the shared category metadata, manual selector, and category API contracts.
Jobs imports `api.models → api.categories`; its sync path imports derivation,
classification, database models, and shared schema verification. Its image also
contains migration and restore modules. Therefore API, web, and jobs must all be
built from the same reviewed Dining revision and tested as matching images.
PostgreSQL has no Python/category-module dependency; its constraint changes in
place. No PostgreSQL image replacement is required. Any ad-hoc API, worker,
import, restore, or migration process sharing this database must be inventoried
and stopped too; container inventory alone is insufficient.

There must be no mixed-version serving window. Close application ingress first,
drain outstanding requests and jobs, then stop all old affected API/web/jobs and
ad-hoc processes before the database migration begins. Verify their termination.
Do not start matching services until the atomic migration and evidence checks
succeed. Start matching API and web behind closed ingress. Verify the jobs image
using a non-mutating schema/import check before starting its scheduler; no Plaid
run is part of verification. Check all image identities, Dining options, source
preservation, read-only analytics, and readiness. Only then reopen application
access and writers and resume the matching jobs scheduler. If verification fails,
keep ingress/writers closed and perform the reviewed rollback before restoring
old services. No rolling replacement or old-image fallback may serve against the
new constraint. Production operations still require separate authorization.

Observed running service inventory during local implementation: affected
`pft-runtime-api-1`, `pft-runtime-web-1`, and `pft-runtime-jobs-1`; unaffected database
processes `pft-runtime-db-1`, `personal-finance-tracker-db-production-pilot-1`, and
`personal-finance-tracker-db-1`. The disposable `pft-m3-release-tests-20260929`
PostgreSQL service is isolated on port 55439. Runtime services were not replaced.

Local matching image tags are `pft-m3-dining-api:local`,
`pft-m3-dining-web:local`, and `pft-m3-dining-jobs:local`. Pin their final content
digests and reviewed source revision in the future action packet; local tags alone
are not a release identity. Recheck all container and host-process inventory at
cutover, including processes outside Compose.
