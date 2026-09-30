# M3 Dining Production execution — 2026-09-29

**Status: atomic migration committed; exact pinned services staged and verified. Owner acceptance pending.**

The owner authorized the reviewed forward packet, then explicitly selected
**keep application access closed and jobs paused until acceptance**. Consequently,
packet steps 1–4 are complete; step 5 (reopen/resume) has not run. No M4 work began.
Normal localhost port 3000 is absent and Tailscale Serve configuration is empty.
The verified web is available only on loopback verification port 3004. No Production
Plaid API calls, sync requests, classification runs, or backup ticks were made.

## Exact migration and preservation

Database `pft_production_backfill`, role `pftbackfill`, PostgreSQL 16.15,
server `172.20.0.4`, unchanged database container and authority volume
`personal-finance-tracker_pgdata_production_backfill`.

The old web/API/jobs stopped before DB changes. No other DB clients or running syncs
remained. The maintenance refresh admitted only the reviewed pre-stop heartbeat
difference; all financial fingerprints, manual audit rows, target IDs, constraint,
and public table inventory matched the seal. The manual table had no triggers.

Commit receipt time: **2026-09-29T21:58:32.361755+00:00** (UTC filesystem receipt time).
Both `.committed` and independent `.verified` receipts exist. The transaction
changed only the reviewed category constraint and the category cells of the exact
80 active sealed overrides; it passed lock, timeout, row, audit, and fingerprint guards.

| State | Before active | Before cleared | After active | After cleared |
| --- | ---: | ---: | ---: | ---: |
| Manual FOOD_AND_DRINK | 80 | 0 | 0 | 0 |
| Manual DINING | 0 | 0 | 80 | 0 |

Manual row count remains **180**. The 80 targets retain their original transaction
IDs, created/updated/cleared actors, and timestamps; only `category` differs.
All other 100 manual rows are identical. All 14 other public-table fingerprints
match the quiescent before-state exactly. Raw and normalized financial rows,
classifications, benefits, labels, cursors, Items, accounts, statement evidence,
sync runs, Membership meaning, and paused runtime state are preserved. All **573**
normalized Plaid/source FOOD_AND_DRINK values remain; raw-table fingerprints are
also unchanged. The constraint now permits DINING and excludes FOOD_AND_DRINK.

| Sealed evidence | SHA-256 |
| --- | --- |
| Reviewed 80-row manifest | `3fa7fc7ba493893b660e73d5d3458a4035753ddbe9c90eef81754bf870a75147` |
| Heartbeat-only maintenance manifest | `3151bd4abbfac3e79719cb2128ef7545477f75a7becc39ea247f3bdfcb9a4940` |
| Forward before/after evidence | `2bb1571fbcf15b14aa8eec6fedb9421d31fdcbf29695a547032abe1440345cdf` |
| Manual table before, count 180 | `2fb6031cad383df3ba2100f441e0b3d84d492c2a663019d817300ae00d5ffea3` |
| Manual table after, count 180 | `1a680f7c3b59b2073a648632fa54c405583793409ba417fbcfcfeab69f8399ff` |

## Staged financial and UI verification

The unchanged sealed GET verifier passed **1,540 requests** over
all **25 months**, September 2024–September 2026. It checked exact monthly responses,
canonical category summaries, every paginated gross/refund/reimbursement/benefit/net
contributor ID and signed sum, source-category preservation, all account/institution
modes, and Membership periods. All expected amounts and component reconciliations
match the reviewed preview. Monthly/account/institution/Membership money is unchanged;
legacy monthly category codes receive only the approved Dining rename/order change.

September remains Gross **6,483.52** − Refunds **1,601.47** − Reimbursements **37.50**
− Card Benefits **210.26** = Net Spending **4,634.29**. Representative full category
and benefit redistribution tables remain in the protected `preview-review.md`.
DINING_CREDIT now attributes to DINING; Groceries remains separate.

The API/manual category options expose `DINING` with label **Dining**, retain
GROCERIES, and exclude the old manual code. Rendered staged UI checks passed at
**390, 768, and 1440 px**: Dining and separate Groceries, canonical net drilldown,
no horizontal overflow, no page errors. Browser requests were restricted to local
GETs; the existing Plaid Link CDN download was blocked before network access.

## Exact services and readiness

| Service | Verified new image ID | Retained rollback image ID |
| --- | --- | --- |
| API | `sha256:8f82bdaea18a838f2ec3df512c4e3d9a1dbddb91bc24ea85a825d5e24929b961` | `sha256:5b11a147048f888fe9ee6e05ff5f9984a31749e95bdcd6db6dfdcb1b0ff66dcf` |
| Web | `sha256:27ebccc049961a588f5fc8ced6c56bdcbe596920cdef41d2a1d4740550fb63f3` | `sha256:aaa353283344398d2d58908e911704071a3c4f7623bbfc886f93e7747f7fa586` |
| Jobs | `sha256:b1ae3322ba3ab7683d46b4026dda5f57ecd43463e8bbc1a6e4d51272ce59de6c` | `sha256:f3e3536c901ad23a4d3f1e2f007f11a4933dbc9cfa1c8b635565a8a2fbed60d2` |

API and web Docker health/readiness passed; DB remains healthy. Jobs has no Docker
healthcheck: its exact pinned container is running `sleep infinity`, and a read-only
imports/schema check passed for DINING without executing the scheduler. All new
containers have zero restarts. The jobs scheduler/heartbeat is deliberately paused,
so normal active scheduler health and reopened localhost/Tailscale reachability are
**deferred**, not claimed as passed. Access has not been reopened even temporarily.
No mixed-version serving window occurred.

## Rollback and protected evidence

Final read-only proof at **2026-09-29T22:11:04.527792+00:00** confirms exact committed
after-state and **guarded reverse eligibility**. All old images remain available.
Use only the packet's manifest-specific reverse while access/writers stay closed;
any subsequent state change must make the guard refuse. Never use a global Dining
rewrite or whole-database restore to undo this migration.

Evidence is mirrored to owner-only Windows storage:
`C:\Users\tianr\PFTBackups\Production\M3-Dining-20260929`.
Original 27 artifact hashes and the execution inventory were compared after copy.
ACL grants only the owner, Administrators, and SYSTEM. C: encryption is the owner's
previously confirmed protection state; a fresh tool query still required Windows
administrator rights and was denied. Private financial manifests are not committed.

Execution evidence includes `execution-summary.json`, `forward-result.json` and
its receipts, maintenance manifest/refresh evidence, HTTP/UI/runtime checks,
independent DB proof, `final-rollback-eligibility.json`, and `execution-integrity.json`.
The original reviewed packet and original integrity inventory are unchanged.

Two verification invocation/representation issues were resolved without changing
images or DB state: the sealed external refresh helper required `/app` on the
one-off Python import path; the independent proof normalized PostgreSQL's equivalent
INET `/32` text representation. The UI guard recorded the blocked SDK download.
No financial, schema, runtime identity, reconciliation, or readiness precondition
failed, and no rollback was needed.

**Next authorization boundary:** owner post-deployment acceptance, then the packet's
reopen/resume sequence. Scheduler resumption writes runtime state and can perform
due Plaid work, so it remains paused under the current no-Plaid instruction.
