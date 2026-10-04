# CI maintenance

`CI` runs on pull requests targeting `main`, pushes to `main`, and manual
`workflow_dispatch`. Its stable required check names are **frontend** and
**backend**. Both run on standard GitHub-hosted `ubuntu-24.04` runners with
read-only repository permissions and 15-minute timeouts. New runs cancel stale
runs for the same PR/ref. There are no deployments, image publishing, cloud
operations, Production secrets, or real Plaid requests in this workflow.

## Local reproduction

Use a clean checkout with Node 22 and Python 3.12, matching `Dockerfile.web` and
`Dockerfile.api`. Do not source an application or Production env file.

```sh
npm ci
npm test -- --ci --runInBand --json --outputFile=/tmp/pft-jest.json
node scripts/ci_frontend_summary.cjs /tmp/pft-jest.json
npx --no-install tsc --noEmit
NEXT_TELEMETRY_DISABLED=1 PFT_API_URL=http://127.0.0.1:8000 npm run build
```

The backend requires a **new disposable** PostgreSQL 16 cluster on loopback
port **55439**, user `pft_ci`, password `synthetic`, database `pft_ci_synthetic`.
Do not reuse an existing application database. The role needs database creation
privileges for migration and recovery tests. Install PostgreSQL 16 client tools
at `/usr/lib/postgresql/16/bin` (`postgresql-client-16` on Ubuntu).
For example, after ensuring port 55439 is unused:

```sh
docker run --name pft-ci-postgres --rm -d \
  --tmpfs /var/lib/postgresql/data \
  -p 127.0.0.1:55439:5432 \
  -e POSTGRES_USER=pft_ci -e POSTGRES_PASSWORD=synthetic \
  -e POSTGRES_DB=pft_ci_synthetic postgres:16
# Wait for pg_isready to succeed before running tests.
docker exec pft-ci-postgres pg_isready -U pft_ci -d pft_ci_synthetic
python3.12 -m venv /tmp/pft-ci-venv
/tmp/pft-ci-venv/bin/python -m pip install -r api/requirements.txt
/tmp/pft-ci-venv/bin/python scripts/ci_backend_tests.py
docker stop pft-ci-postgres
```

The backend entry point fixes synthetic database/Plaid/owner settings and enables
all seven `PFT_*_SYNTHETIC_TEST` switches. It discovers every `tests/test_*.py`,
including existing mocked cloud experiment tests; it never runs a cloud probe
or a scheduler. Plaid SDK HTTP requests fail if a test misses its mock. Python
socket connections are restricted to the disposable database. Recovery tests
generate synthetic archives in temporary directories and use matching PG16 tools.

Both entry points print executed, failure/error, and skipped counts, also written
to the Actions job summary. Any skip/todo fails CI. Backend discovery also fails
if an opt-in is added without updating the inventory, a required integration
class/critical test disappears, or a discovered test does not run. Keep the
inventory and required test names current when deliberately renaming tests;
never remove assertions or disable tests to make CI green.

## Main merge protection

Configure protection only after the PR's latest **frontend** and **backend** jobs
actually succeed. Inspect existing branch protection and rulesets first and
preserve all existing protections. If API access is unavailable, use repository
Settings → Branches → the `main` protection rule (or add one if absent):

- Enable **Require a pull request before merging**. For a new rule, leave
  **Require approvals** disabled; preserve any existing approval requirement.
- Enable **Require status checks to pass before merging**, select `frontend`
  and `backend` from **GitHub Actions**, and enable **Require branches to be
  up to date before merging**. Retain any already-required checks.
- Keep **Allow force pushes** and **Allow deletions** disabled.
- Do not introduce signed-commit or linear-history requirements. Retain them
  if already required. Leave bypass allowances empty for a new rule and enable
  **Do not allow bypassing the above settings** so administrators also use PRs.

Save the rule, then verify it and any matching rulesets. Do not merge this CI PR
automatically. If `main` advances, update the PR branch and wait for both checks
on the updated commit before merging.
