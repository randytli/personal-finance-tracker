# M4 temporary private iPhone preview — 2026-09-30

Owner approved this isolated preview in the conversation. Owner real-iPhone portrait/landscape acceptance is PASS. The temporary preview is now removed; the setup and URLs below are historical. No Production deployment or frontend UI/CSS change was made.

## Active setup

- Frozen current local build: `p0EpAkwaWKXRWo3aiFdKA`, copied to `/tmp/pft-m4-private-preview-20260930/frontend/.next`.
- Next.js snapshot server: `127.0.0.1:3003`, with API rewrite target `http://127.0.0.1:9`.
- Temporary preview adapter: `127.0.0.1:3005`. Assets, navigation and browser requests are scoped to `/m4-preview`. All API responses are synthetic; edits affect only in-memory synthetic rows. Unknown API routes fail closed instead of forwarding. CSP additionally blocks direct Production API paths, external connections, external scripts, forms and workers.
- Synthetic list choices: 103 rows or 3 rows, with 10 rows per phone/coarse-pointer page and 50 per desktop page. Fixtures reuse the existing responsive QA harness. Short-list state changes only on document navigation, not Next.js prefetches.
- Diagnostic script records computed layout, native visualViewport geometry, script identity and page/list/disclosure/toolbar/spacer bounds. It records no transaction text, amounts or account names. Captures are in `/tmp/pft-m4-private-preview-20260930/iphone-geometry.jsonl`.

Existing private Serve HTTPS 443 mapping remains `/ → http://127.0.0.1:3000`. The only additional handler is `/m4-preview → http://127.0.0.1:3005`. Serve text status reports **tailnet only**; no Funnel, ACL, firewall or Production environment change was made.

URLs:

- `https://pft-host.tailc4d964.ts.net/m4-preview/`
- `https://pft-host.tailc4d964.ts.net/m4-preview/review`
- `https://pft-host.tailc4d964.ts.net/m4-preview/memberships`
- Short lists: append `?list=short` to either transaction page, or use the landing-page links.
- Overview: `https://pft-host.tailc4d964.ts.net/m4-preview/overview`.

## Verification

Local Chromium and WebKit each passed eight Review/Membership cases at 390, 768, 844×390 touch landscape and 1440. Checks covered 10/50 pagination, short and partial last pages, natural bottom spacing, selected toolbar clearance, page navigation remaining in the preview, unknown API failures, and CSP blocking both unprefixed same-origin API requests and direct port-3000 API requests. Overview also rendered in each browser. Windows loopback access returned HTTP 200.

The actual private HTTPS route returned 200 and passed the same eight Chromium browser cases. The Linux WebKit test runtime could not open HTTPS because its TLS backend is unavailable; WebKit's local HTTP checks passed. Actual iPhone Safari HTTPS/layout acceptance remains for the owner.

Saved Serve JSON matches the original snapshot plus exactly the approved preview handler. All Docker container IDs, images and published port bindings match the pre-action baseline. Fingerprints for all 33 frontend source files match. Production web/API/DB/jobs were not rebuilt, restarted or modified. No Production API request, financial write or Plaid call occurred. `git diff --check` passed.

Artifacts, process IDs, adapter source, frozen fixtures, before/after routing and container baselines, browser results/screenshots and execution receipt are under `/tmp/pft-m4-private-preview-20260930/`. Processes run temporarily in the background, without installing a startup service.

## Real-iPhone checks

With Tailscale connected, open the preview landing page and confirm its build ID. On both transaction pages, confirm `1–10 of 103` before starting. Test bottom spacing without selection, with a selection and visible bulk toolbar, after confirmation/cancel/clearing selection, and after expanding/collapsing the final transaction's editor. Go to the last page (`101–103 of 103`) and repeat with and without selection. Test the landing page's 3-row variants. Repeat in portrait and touch landscape, and after opening/closing an editor or date picker. Pagination must remain reachable above the toolbar; clearing selection must remove toolbar compensation. Legitimate page and safe-area padding remain.

Pause approximately two seconds at each bottom state so geometry is captured. If excess space persists, record page, orientation, selected/unselected state and whether it follows picker/disclosure use; a screenshot is useful. Do not change app UI/CSS until an owner-reported current-preview problem can be reproduced and diagnosed.

## Cleanup when acceptance is finished

Prepared guarded cleanup:

```bash
python3 /tmp/pft-m4-private-preview-20260930/cleanup.py
```

The script verifies Serve is either the saved baseline or that baseline plus the exact preview handler, removes only `/m4-preview`, requires the remaining configuration to match the original Production route, then stops only the recorded temporary processes after checking their working directories. It retains diagnostic artifacts and never runs Serve reset or stops a Production container.

The targeted Serve removal is:

```powershell
& 'C:\Program Files\Tailscale\tailscale.exe' serve --bg --https=443 --set-path=/m4-preview off
```

The [official Serve reference](https://tailscale.com/docs/reference/tailscale-cli/serve#disable-tailscale-serve) documents retaining the path flags when turning off a particular handler. Do not use the generic `serve --https=443 off` printed during activation: this preview cleanup must preserve the existing Production handler.

## Cleanup completed

Owner reported real-iPhone M4 acceptance PASS. The guarded cleanup ran successfully, removing only `/m4-preview` and terminating only temporary PIDs 92025/92589. Both processes are absent; ports 3003/3005 have no listeners. Remaining Serve JSON exactly matches `before-serve.json`, retaining `/ → http://127.0.0.1:3000`. Production web/API/jobs/DB container IDs, images, start times and restart counts remain unchanged. All 33 frontend source fingerprints match the accepted preview. No UI/CSS change or Production deployment occurred. Diagnostics and `cleanup-receipt.json` are retained in the temporary packet. Preview URLs above are no longer active.
