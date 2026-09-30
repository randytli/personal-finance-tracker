# Overview category UX — web-only Production deployment

Completed September 29 EDT / September 30 UTC. Owner reported **all physical-iPhone checks passed** after deployment.

## Verification

- Full frontend suite: **10 suites / 44 tests passed, zero skipped**.
- TypeScript (`npx tsc --noEmit --incremental false`), Next.js build, and `git diff --check`: passed. Existing Next.js metadata viewport/themeColor warnings remain.
- Synthetic local rendered QA at **390 / 768 / 1440px**: passed before cutover.
- Read-only Production rendered QA at the same widths passed on both localhost and actual private Tailscale HTTPS. The 390px automated check used Chromium with iPhone-sized touch emulation; physical-iPhone verification was separately confirmed by the owner.
- Desktop/tablet: primary category rows expand one vertical component block at a time; no Sheet, Drawer, backdrop, or floating panel. Height increases only by the expanded block. Row/chevron toggles; metric amounts and component rows open transaction details.
- Mobile: compact category list and near-full-height “View full breakdown” Sheet preserved; disclosures, independent scrolling, focus trap, Escape, close/reopen, and drill-down focus transfer passed.
- Net selected by default; all five spending cards work. Gross / Refunds / Reimbursements / Card Benefits / Net values and counts match source payloads. Negative and zero values stay visible. No horizontal overflow, browser runtime errors, failed API responses, or attempted browser mutations.
- Overview, Review, Membership HTML and all 10 deployed JavaScript assets match between localhost and private Tailscale; monthly API responses match.

## Deployment and preservation

Only `pft-runtime-web-1` was recreated, using Compose `--no-deps --no-build --pull never --force-recreate web` and an exact image override.

New web image:
`sha256:5f269ec4ff7d83d5809625e6c84c1c05d5ffe902ee79e85dffff892dad7462ca`
Tag: `pft-web:overview-inline-20260929`.

Retained rollback web image:
`sha256:27ebccc049961a588f5fc8ced6c56bdcbe596920cdef41d2a1d4740550fb63f3`
Tag: `pft-web:rollback-overview-20260929`.

New web is running and healthy, with zero restarts and clean startup logs. API, jobs, and database container IDs, images, start times, and restart counts remain identical to the baseline. **33 analytics fingerprints match**, covering monthly outputs for all 25 months, representative account/institution outputs, and YTD/trailing-12-month Membership outputs.

No financial semantics, category attribution, Dining migration, persisted data, schema, jobs, or Plaid behavior changed. Deployment and browser checks performed no Production data writes or Plaid calls. Existing jobs continued running untouched. No M4 work began.

## Evidence and rollback

Owner-only local evidence directory:
`/tmp/pft-overview-web-release-20260929`.

Contains source fingerprints, exact image identities, before/after container identities and analytics hashes, HTTP checks, local/private Production browser results/screenshots, owner iPhone confirmation, pinned Compose image overrides, and forward/reverse web commands. Synthetic local QA remains under `/tmp/pft-overview-inline-qa`.

Retained web-only rollback command (execute only with rollback authorization):

```bash
bash /tmp/pft-overview-web-release-20260929/deploy-web.sh rollback
```

This selects the retained image with `--no-deps`; it performs no database reversal or Dining migration. Preserve the release overrides when recreating web so the earlier Dining packet’s old web pin does not accidentally replace this release.
