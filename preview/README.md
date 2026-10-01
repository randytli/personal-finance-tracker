# Design preview (preview-only)

An isolated build of the frontend under `/design-preview`, backed only by synthetic data. Nothing in this directory is used by Production builds: `next.config.js` loads `preview/next-config.cjs` only when `PFT_PREVIEW_BASE_PATH` is set.

| Process | Bind | Purpose |
| --- | --- | --- |
| `node preview/mock-api.cjs` | `127.0.0.1:3107` | Synthetic API. Reuses the fixture/responder from `scripts/pft_m4_browser_qa.cjs`; edits stay in memory; Plaid writes return 403; unknown paths return 404. |
| `next start` (preview build) | `127.0.0.1:3106` | `basePath=/design-preview`, `distDir=.next-design-preview`, rewrites baked to the mock only. |

```bash
preview/run.sh build   # refuses to build without a loopback, non-Production PFT_API_URL; verifies routes-manifest
preview/run.sh start   # refuses if .env/.env.local/.env.production* exist or ports are busy
preview/run.sh status
preview/run.sh stop    # stops only the recorded PIDs whose cwd is this worktree
```

Isolation:

- Client API calls go through `lib/api.ts` (`apiFetch`), which prefixes `PFT_CLIENT_BASE_PATH` (defined only by the preview build), so the browser requests `/design-preview/api/pft/...`, never `/api/...`.
- The preview CSP limits `connect-src` to `<origin>/design-preview[/]`; `react-plaid-link` is aliased to a stub so `cdn.plaid.com` is never loaded.
- If the mock is down, the Next rewrite fails and pages show their error states. There is no fallback to `127.0.0.1:8000`.
- `preview/capture.cjs` takes screenshots at 390/768/1440 and fails if any request leaves the prefix or the CSP reports a violation.

Tailscale Serve strips a handler's mount path before proxying (`http.StripPrefix(mountPoint)` in `ipn/ipnlocal/serve.go`) and then joins the target URL's path. The handler target therefore carries the prefix back: `/design-preview → http://127.0.0.1:3106/design-preview`.

Removal: `preview/run.sh stop`, remove only the `/design-preview` Serve handler, then delete `preview/`, `.next-design-preview/` and the three-line hook at the end of `next.config.js`. `lib/api.ts` is a no-op without the preview build and can stay.
