# M4 frontend-only Production deployment — 2026-09-30

Deployed after explicit owner approval following real-iPhone portrait/landscape
acceptance. Only `pft-runtime-web-1` was recreated, using the verified immutable
web image and `--no-deps --no-build --pull never --force-recreate --wait`.

Release image: `sha256:6ad6b7bc0f9962854c1c61467ea049baa61266ab281ed3b369774ba3be0f2180`.
Tag: `pft-web:m4-responsive-20260930`.
Production build ID: `lto-AUcYrL5c59Tz8QL6W`.
Web container: `69f85ba97d6ac08723dc08e976a98c8ca2c679246e50e06b81630634de111fa2`,
started `2026-09-30T22:42:06.256917876Z`, healthy, zero restarts.

All 33 accepted frontend source fingerprints still match the private preview.
The Production rebuild uses the existing `http://api:8000` rewrite; it does not
include the synthetic preview adapter or fixtures. Review/Memberships use 10 rows
on phones/coarse-pointer devices, including touch landscape, and 50 on desktop.

## Verification

- 54 tests across 11 suites, standalone TypeScript check, Docker production build
  including lint/type validation, and `git diff --check` passed.
- Candidate synthetic browser checks: 27 complete flows and 54 spacing cases each
  in Chromium and WebKit, at 320/375/390/393/430/768/1280/1440 plus 844×390 touch
  landscape. Selected/unselected, empty/short/long lists, partial last pages,
  toolbar clearance and pagination passed; Chromium checked nonzero safe-area insets.
- Deployed static frontend: 18 synthetic-only rendered checks across all three
  pages at 390/768/1440, through localhost and private HTTPS. No page errors,
  horizontal overflow, Production API requests or mutations during visual QA.
  Mobile 10 / desktop 50 and explicitly hidden collapsed bodies were verified.
- All three routes return 200. Page HTML and 10 Overview assets match between
  localhost and private HTTPS, as does the read-only monthly API response.
- All 33 read-only analytics preservation fingerprints match: 25 monthly outputs,
  six account/institution summaries and two Membership period summaries.
- API/jobs/DB container IDs, images, start times and restart counts are unchanged.
  Web retains its loopback-only port. Serve remains exactly
  `/ → http://127.0.0.1:3000` on private HTTPS 443.
- Temporary candidate server stopped; ports 3003/3005 have no listeners. The
  `/m4-preview` handler remains removed. No UI/CSS changes followed owner acceptance.

No financial writes, schema changes, Plaid calls, API/jobs/DB operations or Tailscale
configuration changes occurred during deployment. Browser edits before cutover were
intercepted synthetic mutations only. Real-iPhone acceptance was on the matching
frontend source in the isolated preview, before Production cutover.

## Retained rollback

Image: `sha256:0ade6994b51f289a10f5d2c13ed0cfb140c37fda0b202eeed150e435d1932414`
(`pft-web:review-memberships-20260930`). Rollback restores the prior 50-row frontend.
Only web would be recreated; data/backend rollback is unnecessary.

Rollback command, subject to rollback authorization:

```bash
bash /tmp/pft-m4-web-release-20260930/deploy-web.sh rollback
```

Owner-only packet `/tmp/pft-m4-web-release-20260930/` retains exact forward/rollback
overrides, candidate build, source fingerprints, Compose verification, before/after
analytics/container fingerprints, browser results/screenshots and release receipt.
Use this latest web override for future web recreation; earlier release packets
pin older frontend images.
