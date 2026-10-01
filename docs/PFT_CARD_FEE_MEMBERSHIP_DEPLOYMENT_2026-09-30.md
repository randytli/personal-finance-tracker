# Annual card fee Membership rule — Production release 2026-09-30

Owner authorized deployment after reviewing the local rule change.

## Scope and behavior

Only the API container was recreated. The new image adds one layer replacing `/app/api/labels.py` on the existing Production API image. No other application source or dependencies were replaced.

Removed automatic Membership matches for `MEMBERSHIP FEE`, `RENEWAL MEMBERSHIP FEE`, `CAPITAL ONE MEMBER FEE`, and `GOLD ANNUAL SUBSCRIPTIO`. Existing transactions are evaluated using the updated rule on read. Ordinary expense classification and Overview spending remain unchanged. Explicit manual Membership includes still win. Subscription-related card benefits remain unchanged.

No database migration, financial-data write, Plaid call, sync, web/jobs/DB restart, or Tailscale configuration change was performed.

## Immutable images and rollback

New API: `sha256:d5e5e8a3a67629f4d377ce1b6b3ac3a530a7191a90f875604770c897c4c2d642` (`pft-api:exclude-card-fees-20260930`).

Retained rollback API: `sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961` (`pft-api:card-fee-rollback-20260930`).

Release packet: `/tmp/pft-card-fee-release-20260930/`. It contains explicit forward/rollback API overrides and current web/jobs image pins. Future API recreation must use the new override to avoid unintentionally reverting the rule.

Approved cutover command: `bash /tmp/pft-card-fee-release-20260930/deploy-api.sh forward`.

Rollback command, if authorized: `bash /tmp/pft-card-fee-release-20260930/deploy-api.sh rollback`. It replaces only API and restores prior automatic Membership rules; no data rollback is needed.

## Verification

- Full backend suite: 267 discovered, 181 passed, 86 opt-in integration cases skipped (no synthetic integration database enabled). Focused suite: 74 passed, 11 skipped. Python compilation and `git diff --check` passed.
- API health passed; configured API environment and startup command match the prior deployment. Startup verifies schema read-only and invokes no migration.
- Read-only Production baseline: 15 table fingerprints, 25 monthly Overview outputs, and 50 Membership results (25 ending months × two periods). Candidate rule was evaluated in memory in a separate diagnostic process; Production code remained unchanged until cutover.
- All 50 deployed Membership results match the precomputed expected results. 33 results changed from the old rule as expected.
- All 25 Overview monthly outputs remain byte-identical.
- All 14 non-runtime-state table fingerprints remain identical, including transaction/source rows and manual overrides. `sync_runtime_state` changed while jobs remained active and was excluded from financial preservation comparison; the baseline did not separately capture its fields, so only a whole-table operational difference is recorded.
- Web, jobs, and DB container IDs, images, and start times remain unchanged.
- Local and private HTTPS checks: both Membership summary periods match expected results; all 112 trailing-year Membership detail rows checked per origin. Removed fee descriptions absent unless explicitly manually included.
- No visual changes; existing accepted M4 frontend remains deployed.
