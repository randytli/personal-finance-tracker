# Review and Memberships visual redesign — web deployment

Deployed the owner-accepted local frontend on September 30, 2026. Only
`pft-runtime-web-1` was recreated with an exact image override and
`--no-deps --no-build --pull never --force-recreate --wait`.

Release image: `sha256:0ade6994b51f289a10f5d2c13ed0cfb140c37fda0b202eeed150e435d1932414`
Tag: `pft-web:review-memberships-20260930`.

Retained rollback image: `sha256:5f269ec4ff7d83d5809625e6c84c1c05d5ffe902ee79e85dffff892dad7462ca`.

Frontend verification: 10 suites / 44 tests, TypeScript, Docker Next.js build,
and diff checks passed. Existing Next.js viewport/themeColor metadata warnings
remain. The owner accepted fresh synthetic screenshots before authorizing deployment.

All three routes return HTTP 200 through localhost and existing private HTTPS;
page HTML, 10 Overview JavaScript assets, and the monthly API response match
between those endpoints. All 33 analytics fingerprints match the predeployment
baseline, covering 25 monthly outputs, six account/institution summaries, and
YTD / trailing-12-month Membership summaries. API, jobs, and database container
IDs, images, start times, and restart counts are unchanged. Web is healthy and
retains the loopback-only port binding. No financial writes, Plaid calls, schema
changes, jobs operations, or Tailscale changes were performed.

Read-only rendered checks passed for Overview, Review, and Memberships at
390 / 768 / 1440px through both localhost and private HTTPS: 18 page checks,
no horizontal overflow, runtime/API errors, or attempted browser mutations.

Owner-only evidence and exact forward/rollback overrides:
`/tmp/pft-review-memberships-release-20260930`.

Rollback command (requires rollback authorization):

```bash
bash /tmp/pft-review-memberships-release-20260930/deploy-web.sh rollback
```

Keep the release override when recreating web; the older Dining packet contains
an earlier web pin.
