# M4 frontend-only Production deployment plan — executed

Current status: owner approved deployment; frontend-only Production cutover and verification completed successfully. See `PFT_PHASE_2_M4_WEB_DEPLOYMENT_2026-09-30.md` for immutable release identity and results. The preparation-time plan below is retained as history; its pending/approval statements are superseded.

Owner real-iPhone portrait/landscape acceptance is PASS for private-preview build
`p0EpAkwaWKXRWo3aiFdKA`. Preview cleanup is complete. No deployment has occurred.
The accepted frontend source remains unchanged, including 10-row phone/coarse-pointer
pagination and 50-row desktop pagination.

## Release and rollback identities

Current Production web container: `pft-runtime-web-1`, ID
`c5daf985eb0ff9b5fd54b14edc74f381cde83bb0d57c07d8fa292142e36a7897`.

**Exact rollback image**, verified locally available:
`sha256:0ade6994b51f289a10f5d2c13ed0cfb140c37fda0b202eeed150e435d1932414`
(`pft-web:review-memberships-20260930`). This is the currently deployed accepted
Review/Memberships build, with 50-row pagination.

Prepared packet: `/tmp/pft-m4-web-release-20260930/`, containing the accepted
33-source-file fingerprint manifest, exact rollback override, and web-only execution
script. No candidate image has been built yet; `web-new.yml` must be created from
the verified candidate's immutable image ID before forward execution is possible.

## Execution after explicit deployment approval

1. Recheck all accepted source fingerprints, working-tree scope, retained rollback
   image, original Serve mapping, and Production web/API/jobs/DB container baseline.
   Capture read-only analytics preservation fingerprints using the prior release's
   snapshot approach. Do not trigger synchronization or mutations.
2. Build only the web image from the accepted repository frontend source:

   ```bash
   docker build -f Dockerfile.web -t pft-web:m4-responsive-20260930 .
   docker image inspect --format '{{.Id}}' pft-web:m4-responsive-20260930
   ```

   Pin that returned `sha256:…` in the packet's `web-new.yml` under `services.web.image`,
   with `pull_policy: never`. Recheck source fingerprints after building. The
   Dockerfile uses the existing Production API rewrite `http://api:8000`; do not
   deploy the preview `.next` artifact, whose deliberate API target is unreachable
   port 9. A different Next build ID is expected from this configuration rebuild.
   No synthetic adapter, preview route, fixture, or diagnostics script is deployed.
3. Verify the candidate in an isolated, synthetic-only browser setup with Production
   API access blocked. Check Overview/Review/Memberships at the required widths and
   selected/unselected, short/last-page and touch-landscape states. Confirm phone 10 /
   desktop 50, viewport/safe-area metadata, source identity, and successful build.
   Stop any isolated verification runtime afterward. Abort before cutover on failure.
4. Validate the resolved Compose configuration retains existing Production environment,
   loopback port binding and API/jobs/DB image pins. Execute only:

   ```bash
   bash /tmp/pft-m4-web-release-20260930/deploy-web.sh forward
   ```

   The script uses project `pft-runtime`, `compose.runtime.yml`,
   `docker-compose.production.yml`, the existing M3 image pins, and the new web-only
   override. Its operation is `up -d --no-deps --no-build --pull never
   --force-recreate --wait --wait-timeout 60 web`. Only web is recreated; a brief web
   interruption is possible. Do not run Compose down, build/recreate dependencies,
   restart API/jobs/DB, or change Tailscale Serve.
5. Verify web health and `/`, `/review`, `/memberships` via localhost and existing
   private HTTPS, plus read-only rendered 390/768/1440 checks. Confirm the new assets,
   mobile 10 / desktop 50 and accepted layout. Compare analytics fingerprints and
   API/jobs/DB container IDs, images, start times and restart counts to baseline.
   Preserve `/ → http://127.0.0.1:3000` and its HTTPS route exactly. Record immutable
   release image, build ID and verification receipt; retain both web overrides.

## Rollback

If cutover fails health, identity or acceptance checks, stop further rollout and
report the failure. Rollback uses the exact pre-M4 image above and recreates only
web, using the same Compose settings and isolation flags:

```bash
bash /tmp/pft-m4-web-release-20260930/deploy-web.sh rollback
```

Rollback requires authorization; the current request authorizes preparation only.
After rollback, verify health, original assets, unchanged Serve route and unchanged
API/jobs/DB baseline. The rollback intentionally restores the prior 50-row frontend.
No data rollback, schema action, jobs operation or financial/backend change is involved.

## Current verification

Preview PIDs 92025/92589 are absent, ports 3003/3005 have no listeners, Serve JSON
matches the original saved baseline, and Production containers remain unchanged.
All 33 accepted frontend fingerprints match. Existing accepted-source verification:
54 tests / 11 suites, typecheck, production build, 216 spacing cases, 27 complete
flow cases, nonzero safe-area checks, and owner real-iPhone portrait/landscape PASS.
Only acceptance/preview/deployment documentation changed during preparation.
Candidate-image verification and cutover are intentionally pending deployment approval.
