# Phase 2 M4 responsive acceptance — 2026-09-30

Source: `PFT_PHASE_2_ARCHITECTURE_PLAN.md`, section 11. Starting code: `b2c5553` (`Unify Review and Memberships with Overview design`). This milestone preserves that accepted design; it does not replace the pages or change financial behavior.

Current status: **PASS — owner confirmed real-iPhone portrait/landscape M4 acceptance on the current private preview build `p0EpAkwaWKXRWo3aiFdKA`.** The preview has been removed. The owner subsequently approved frontend-only Production deployment; cutover and verification passed. See `PFT_PHASE_2_M4_WEB_DEPLOYMENT_2026-09-30.md`. Earlier pending statements below describe historical checkpoints and are superseded by the final acceptance entry.

## Initial gap audit

| Requirement | Before M4 | Evidence / remaining gap |
| --- | --- | --- |
| Shared navigation, shell, headers, primary/secondary metrics | PASS | Overview visual language already present on all three routes. Overview duplicated the otherwise shared navigation markup. |
| Responsive transaction cards and disclosures | PASS / PARTIAL | Review/Membership used cards with narrow-screen editing disclosures; Overview had category sheets/component disclosures. Long text beside very large amounts could squeeze merchant text; oversized secondary metrics clipped. |
| Required viewport coverage | PARTIAL | Previous acceptance covered 390/768/1440, not the full M4 matrix. |
| No page horizontal overflow | GAP | Synthetic large Overview values produced document widths 362 at 320, 389 at 375, 397 at 390, and 398 at 393. Review save feedback also overflowed with an unbroken description at 768. |
| Mobile touch targets and input text | GAP | Several controls were below 44×44; compact selects used small type. |
| Viewport, zoom, safe areas | GAP | Deprecated metadata viewport/theme export, source-level maximum-scale restriction, and a referenced absent manifest. Next ignored the legacy viewport shape at runtime; supported explicit configuration was still required. |
| Charts on phones | PARTIAL | Sized parents and minimum-width protection existed. Needed fewer ticks, touch tooltips, compact Membership axis labels, and exact textual totals with negative values. |
| Mobile sync health | PARTIAL | Existing collapsible summary, publication marker, and institution freshness. Needed individual disclosures, clearer API-failure wording, bounded long mobile warnings, and retry. |
| Bulk toolbar | PARTIAL | Existing fixed fallback remained immediately visible. Hardcoded spacer heights did not track expanded confirmation/errors; clipping ancestors, keyboard geometry, and footer clearance needed hardening. |
| Loading/error/empty recovery | PARTIAL | Most states existed. Overview detail loading/empty feedback and explicit read/status retries were incomplete; benefit-option rejection lacked feedback. |
| Range/filter/page preservation on focus | PASS | Existing publication-aware refresh preserved current view parameters and applied selection reset rules. No URL persistence or new navigation-state contract was added. |
| Individual/bulk edits and financial semantics | PASS | Existing APIs, formulas, precedence, eligibility, confirmation, and atomic edits retained. |
| Real iPhone acceptance | OPEN | Browser emulation cannot establish real Safari/native keyboard/cutout behavior. |

## Minimal hardening

- Supported Next Viewport export with unrestricted zoom and safe-area coverage; removed the missing manifest reference. Shared mobile/coarse-pointer hit areas and 16px form text.
- Wrapped long text, save feedback, and large amounts; let oversized summary values span narrow metric grids; retained compact desktop hierarchy.
- Reused Overview's navigation component and compact currency formatter. Added a collapsed monthly totals alternative; configured narrower chart ticks, accessible charts and touch tooltips.
- Added per-institution sync disclosures and explicit distinction between API availability, publication time, and bank checks. Preserved paused, partial, metadata, backup, and error signals. Mobile warnings can scroll without consuming the entire page.
- Portaled the bulk toolbar outside clipping containers, reserved measured space after the page footer, adjusted to visualViewport keyboard geometry, and kept failed-save feedback beside confirmation.
- Added read/status retries and Overview detail loading/empty feedback. Read retries do not replay mutations.
- Added focused component tests and isolated, synthetic browser acceptance automation. No new dependency or backend change.

## Changed files

- `app/layout.tsx`, `app/globals.css`
- `app/page.tsx`, `app/review/page.tsx`, `app/memberships/page.tsx`
- `components/page-presentation.tsx`, `components/account-badge.tsx`, `components/category-display.tsx`, `components/spending-category-view.tsx`
- `components/bulk-transaction-editor.tsx`, `components/sync-health.tsx`
- `app/overview.test.ts`, `app/review/review.test.ts`, `components/bulk-transaction-editor.ui.test.ts`, `components/sync-health.test.ts`
- `scripts/pft_m4_browser_qa.cjs`, this acceptance record

## Verification

Frontend: `npm test -- --runInBand` — 10 suites / 48 tests passed. `npx tsc --noEmit` passed. `npm run build` passed, including Next lint/type validation and static generation. `git diff --check` passed.

Browser: local production build in Chromium. All 27 route/viewport cases passed: 320, 375, 390, 393, 430, 768, 1280 and 1440 on Overview, Review and Memberships, plus touch landscape 844×390. No page-level horizontal overflow or browser runtime exceptions. Visible phone/coarse-pointer controls met 44×44 checks and mobile form text met 16px checks. Screenshots and machine-readable results are in `/tmp/pft-m4-20260930/browser/`; baseline screenshots are in `/tmp/pft-m4-20260930/baseline/`.

The browser harness intercepts every API response, rejects nonlocal origins and the Production port, and performs edits only against its in-memory fixture. Fixtures include ordinary and long/unbroken descriptions, eight-digit amounts, negative chart totals, partial/paused/error bank states, and paginated lists. It exercises loading, expanded sync details, filter/range/page retention on focus, Overview drill-down/category/benefit edits, Membership period/account/view/paging/benefit/label edits, chart tooltips on both analytics pages, and both Review bulk flows. Review checks cover selecting near the top/middle/end, toolbar visibility throughout scrolling, footer clearance, confirmation and simulated keyboard resizing on narrow viewports. Overview checks verify sheet focus and stacking above the bulk toolbar. Empty/read-failure/status-retry checks run at 393 and 1440.

To reproduce, build and start an isolated local server on port 3003, then run `node scripts/pft_m4_browser_qa.cjs` with Playwright available. This workspace used `PFT_PLAYWRIGHT_MODULE=/home/randyli/.npm/_npx/e41f203b7505f1fb/node_modules/playwright` and the existing local Chromium library directory via `LD_LIBRARY_PATH`. The API URL for the local server was the unreachable `http://127.0.0.1:9`; browser responses were intercepted before reaching it.

## Acceptance boundary

No deployment, Production API call, Plaid call, financial-data write, schema change, job change, or formula change occurred. Backend tests are outside this frontend-only change.

Owner real-iPhone Safari acceptance remains required: portrait/landscape complete flows; native month/select menus; actual keyboard and browser chrome transitions; notch/home-indicator clearance; pinch zoom and enlarged text; touch chart tooltips; sheet focus/scroll restoration; network failures and long descriptions/amounts. Keyboard geometry in this browser run is simulated, and emulated safe-area insets are zero. No claim of Safari, PWA, offline, or overall Phase 2 Core acceptance is made.

The local implementation is ready for owner acceptance review. A frontend-only Production release remains a separate explicitly authorized step after real-device acceptance; this work does not authorize deployment.

## Real-iPhone follow-up — bottom spacing and mobile page size

The owner reported excess bottom space even before selecting transactions. Inspection ruled out an unselected bulk spacer: it is absent until selection and is removed when cleared. Both pages retain their 40px bottom padding. The page shell's minimum height fills short viewports; it does not add another viewport after a long list.

Two shared issues were found and hardened:

- `TransactionTools` relied solely on native `<details>` to hide editor bodies. In desktop WebKit, closed Review editor bodies still had 200px layout/scroll bounds; closed Membership editor bodies also remained laid out. The body now uses `hidden={!open}`, yielding zero layout/scroll height while closed without unmounting editors or losing draft state. This removes a candidate source of Safari native scroll overflow. Desktop WebKit did **not** reproduce the owner's entire native iPhone gap, so an iPhone retest remains necessary to establish that this resolves that symptom.
- Bulk compensation reserved toolbar height, bottom offset, and a 16px gap **in addition to** existing page and body safe-area padding. A strict reduced-viewport check reproduced pagination becoming unreachable after confirmation. The measured spacer now subtracts padding already present. Toolbar positioning, keyboard offset, safe-area CSS and legitimate page padding remain intact.

At the owner's initial request, this follow-up used 20 transactions per page on narrow or coarse-pointer devices, including phone landscape, and 50 on desktop. The subsequent request below changes the local phone default to 10. A shared hook controls the existing request limit, range labels, page stepping and out-of-range clamp. Existing filters, range state, mutation payloads and financial calculations are unchanged; changing the displayed page size clears selection.

Follow-up files: `components/page-presentation.tsx`, `components/bulk-transaction-editor.tsx`, both Review/Membership page files, their tests, `components/page-presentation.test.ts`, `components/bulk-transaction-editor.ui.test.ts`, `scripts/pft_m4_browser_qa.cjs`, `scripts/pft_m4_bottom_qa.cjs`, and this record.

Verification: 54 frontend tests across 11 suites, typecheck, production build, and `git diff --check` passed. The new bottom harness passed all 54 cases in Chromium and all 54 in WebKit at 320/375/390/393/430/768/1280/1440 and touch landscape 844×390. It checks empty, 3-row and 110-row lists, last partial pages, explicit closed-panel geometry, selection/confirmation/clearance, simulated keyboard opening/closing and default page sizes. The complete M4 flow matrix also passed all 27 cases with the revised phone pagination.

Final local production-build smoke checks passed at 390 and 1440: 12 bottom cases per engine and six complete flow cases. Nonzero safe-area emulation at 390 verified 47px top / 34px bottom padding, toolbar home-indicator clearance, and natural unselected tails of 74px on Review and 75px on Memberships (including its border). The spacer unit test independently verifies that page padding and safe-area padding are counted only once. No frontend source change followed these checks.

Artifacts: full spacing matrix `/tmp/pft-m4-bottom-20260930/browser/`; full flows `/tmp/pft-m4-bottom-20260930/flows/`; production-build spacing screenshots/results `/tmp/pft-m4-bottom-20260930/built/`; production-build flow screenshots/results `/tmp/pft-m4-bottom-20260930/built-flows/`. For a focused rerun, both browser scripts accept `PFT_QA_WIDTHS=390,1440`; the bottom script accepts `PFT_QA_ENGINE=webkit`.

The exact unselected native iPhone blank-area symptom remains subject to owner retest. The code changes remove measured closed-editor overflow and confirmed duplicate toolbar compensation, but desktop WebKit is not iPhone UIKit/Safari acceptance. No deployment or live financial operation occurred.

## Subsequent retest: frontend identity and 10-row phone preference

The owner reported that the gap persisted, identified the tested URL as `https://pft-host.tailc4d964.ts.net`, and confirmed that it still displayed **50** transactions per page. Read-only static HTML inspection established that this URL serves the earlier deployed build, not the local M4 implementation or its bottom-spacing follow-up:

- Deployed Review asset: `/_next/static/chunks/app/review/page-61d07f1acb619cbf.js`, matching the Production loopback frontend. Deployed build ID: `m4hF_dPXouWoFU-MYDsAy`.
- Deployed viewport meta: `width=device-width, initial-scale=1`. The local M4 build adds `viewport-fit=cover`.
- The deployed frontend still uses fixed 50-row pagination, a selected-only `h-64 sm:h-32` placeholder (256px/128px **before** pagination), and editor bodies hidden only by native disclosures. Local M4 already replaces these with responsive pagination, measured compensation after the footer, and explicit hiding of collapsed transaction editor bodies.

Consequently, this retest does **not** establish whether the local changes resolve the physical-iPhone symptom. A copy of the deployed `.next` build was run on isolated port 3004 with synthetic API responses, and compared with local M4 on port 3003. No Production API was requested and no live service was restarted or changed. Native-viewport desktop WebKit still did not reproduce the owner's large area below pagination: the deployed unselected tail measured 40px on Review and 41px on Memberships. The old selected placeholder contributed its fixed height above pagination. Closed transaction editor bodies retained nonzero bounds but these did not demonstrably extend the root scroll height in that browser. These are measured observations, **not a confirmed root cause for the owner's physical-iPhone gap**.

The deployed build also overflowed horizontally with the deliberately long synthetic sync warnings. Chromium mobile emulation then expanded `innerWidth` to 1356px and `innerHeight` to 2935px despite a 390×844 visual viewport, reproducing a large *short-page* blank region. This was not reproduced in desktop WebKit and does not establish the cause of the reported long-list iPhone symptom. The existing local M4 warning containment already avoids that overflow. No further CSS or layout patch was made during this retest.

This pass changes only the shared `useTransactionPageSize` preference from 20 to **10** for narrow/coarse-pointer devices; desktop remains **50**. Pagination tests and browser expectations were updated. The bottom harness now supports `PFT_QA_NATIVE_VIEWPORT=1`, preserving the browser's actual `visualViewport` rather than replacing it with a keyboard test double. It records geometry at initial, selected, confirmation, cleared, last-page and selected-last-page states; uses a 103-row fixture to exercise genuinely partial last pages at both 10 and 50; and verifies the last-page row count. `scripts/pft_mobile_layout_probe.cjs` records page/list/footer/disclosure/toolbar/spacer bounds, ancestor sizing, computed height/min-height/flex/position/overflow styles, safe-area padding, native viewport geometry and frontend script identity. It records no transaction text, amounts or account names, and makes no API calls.

Files changed in this pass: `components/page-presentation.tsx`, `components/page-presentation.test.ts`, `app/review/review.test.ts`, `app/memberships/page.test.ts`, `scripts/pft_m4_browser_qa.cjs`, `scripts/pft_m4_bottom_qa.cjs`, `scripts/pft_mobile_layout_probe.cjs`, and this acceptance record. Existing local M4 changes are retained.

Verification and fresh screenshots are recorded in `/tmp/pft-m4-iphone-retest-20260930/`. The `native-chromium` and `native-webkit` directories contain 54 passing bottom-layout cases each at 320, 375, 390, 393, 430, 768, 1280, 1440 and touch landscape 844×390. Both selected and unselected states, empty/short/long lists, first/last pages, confirmation, and selection clearing passed. Chromium additionally verified nonzero 47px top / 34px bottom safe areas. Current unselected tails remain 40px/41px; selected compensation clears the measured toolbar and is removed on clearing selection. Native portrait-to-landscape and landscape-to-portrait geometry captures and selected/unselected screenshots are in `screenshots` and `screenshots-webkit`. The `keyboard-chromium` and `keyboard-webkit` matrices each passed another 54 cases, including simulated keyboard opening/closing on both pages, for 216 total spacing cases across native and modeled viewport runs. The complete flow matrix passed 27 cases. Frontend tests passed 54 tests across 11 suites, TypeScript typecheck passed, the production build passed, and `git diff --check` passed. Generated TypeScript build metadata was restored; no frontend source change followed verification.

The owner requested screenshots instead of a phone-accessible preview. A temporary loopback-only mock preview was prepared but was not published; no Tailscale route, ACL, Funnel setting or Production deployment was changed. **Physical-iPhone acceptance remains open, and the root cause of the reported native gap remains unconfirmed.** The next device check must use the current frontend (10 rows), rather than the deployed 50-row build. Screenshots are rendered WebKit/Chromium results, not captures from an actual iPhone.

## Final real-iPhone acceptance and preview cleanup

On September 30, the owner reported **real-iPhone M4 acceptance PASS**, including portrait and landscape, after testing the current isolated private preview rather than the older Production 50-row build. Accepted frontend build: `p0EpAkwaWKXRWo3aiFdKA`; phone/coarse-pointer pagination: 10, desktop: 50. This closes the current-build physical-device acceptance gate, including the reported bottom-whitespace issue. No new UI/CSS changes were made following acceptance. This owner report does not retroactively establish a confirmed causal diagnosis of the older build's native Safari symptom or supply per-case device telemetry.

The approved cleanup removed only `/m4-preview` from Tailscale Serve and stopped recorded temporary PIDs 92025/92589. Both PIDs are absent and neither port 3003 nor 3005 has a listener. Serve JSON exactly matches the saved original configuration: HTTPS 443, `/ → http://127.0.0.1:3000`. Production web/API/jobs/DB container identities, images, start times and restart counts remain unchanged. All 33 accepted frontend source fingerprints still match. Diagnostics remain in `/tmp/pft-m4-private-preview-20260930/`, including `cleanup-receipt.json`.

Prior verification remains applicable: 54 tests / 11 suites, typecheck, production build, 216 spacing cases, 27 complete flow cases, safe-area checks, and diff checks passed. This documentation/cleanup step changes no frontend source and does not require repeating the unchanged UI suite. M4 is ready for owner approval of the separately documented frontend-only Production deployment. No Production deployment, API/financial write, Plaid call, DB or jobs change occurred.

## Production release completed

Following explicit owner approval, only Production web was recreated from the verified M4 image. Deployed build `lto-AUcYrL5c59Tz8QL6W` contains the unchanged accepted frontend source with the existing Production API configuration. All candidate and deployed checks passed; all 33 financial fingerprints and API/jobs/DB identities were preserved. Serve is unchanged, preview ports are clear, and the prior web image is retained for rollback. Full release evidence: `PFT_PHASE_2_M4_WEB_DEPLOYMENT_2026-09-30.md`.
