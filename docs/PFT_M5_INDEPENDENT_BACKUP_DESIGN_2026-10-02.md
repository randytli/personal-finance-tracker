# M5 independent encrypted backup and restore — design and local drill (2026-10-02)

**Status: design plus a local runner, store adapter, restore tool and workflow template (owner decisions P1-1…P1-5 recorded 2026-10-02). This does not close SERVERLESS_GO criterion G7.** G7 also needs a real upload, readback and download from the chosen store, and a restore of the managed PostgreSQL 17 object set on a fresh environment. Both need owner approval. No cloud resource was created or contacted. Production, Supabase, Vercel and Plaid were not touched.

Legend: **[M]** measured tonight; **[D]** quoted from official documentation (link + lookup date); **[E]** estimate or inference; **未核实** not verified.

## 1. Answers to the three questions

### 1.1 What Supabase Free provides

- **Backups: none.** Pricing lists Free "Backups: Not included" [D, [pricing](https://supabase.com/pricing), 2026-10-02]. The backups guide says "We automatically back up all Pro, Team, and Enterprise Plan projects on a daily basis" and "We recommend that free tier plan projects regularly export their data using the Supabase CLI `db dump` command and maintain off-site backups" [D, [backups](https://supabase.com/docs/guides/platform/backups), 2026-10-02].
- **PITR:** "Pro, Team and Enterprise Plan projects can enable PITR as an add-on" [D, same page]. Not available on Free, and it is paid.
- **Pause-specific recovery:** a paused project can be restored "for up to 1 year after it was paused"; after that window "you can download your project's backup file, and Storage objects from the project dashboard" [D, [project pausing](https://supabase.com/docs/guides/platform/free-project-pausing) and [upgrading](https://supabase.com/docs/guides/platform/upgrading), 2026-10-02]. This only covers pausing. It is not a routine or point-in-time backup.

### 1.2 Why an independent backup is still required

1. Free has no routine backup [D], and the provider's own advice is to keep off-site copies [D].
2. **Deletion removes the backups too:** "When you delete a project, we permanently remove all associated data, including any backups stored in S3" [D, backups page]. An owner mistake, account compromise or provider action therefore leaves nothing to restore from at Supabase, even on a paid plan.
3. The plan requires recovery that survives loss of the PC **and** loss of Supabase access, with keys outside both (plan §16.1 item 2; §2 "Independent backup storage outside Supabase remains required").
4. Supabase Storage is not independent. Its objects are not in database backups [D], and it fails together with the project.

### 1.3 Worst case: what point can be recovered

| Scenario | Supabase-side outcome | Recovery point with this design |
| --- | --- | --- |
| Free project **paused** (inactivity) | Data kept; restorable for 1 year [D] | No loss once the owner restores it. Backups fail while it is paused, and this must be visible. |
| Project **deleted** / account lost / provider removal | Data and backups removed [D] | **Last verified independent backup.** Nominal RPO ≤ 24 h. Bound = time since the last run that passed readback. Runs can be delayed or dropped (see §3), so the 25-hour overdue warning is the real control. |
| Same, plus the primary backup store lost | — | Last secondary copy (§4.3). Without one, nothing. |
| Corruption or bad write discovered late | — | Oldest point still retained: up to ~3 months (GFS retention, §5). |

What is lost after the recovery point [E]:
- **Manual edits** (overrides, labels, review decisions) made after the last backup are lost.
- **Plaid-origin rows are probably re-fetchable.** The restored Item cursors are older, so the next sync should replay changes since then. This assumes Plaid still accepts the older cursors. 未核实. Test it only in sandbox, never by calling Production Plaid.

## 2. Requirements

From plan §12.6, §16.1 and §16.2, plus tonight's owner requirement:

- Consistent logical export of **all application objects**: schema, data, constraints, indexes and sequences. Coverage must be **no less than the local backup**. Locally, `api/backup.py` runs `pg_dump -Fc -d <db>` of a database whose only application schema is `public` (15 tables in the drill fixture).
- Authenticated encryption of dump and manifest. Unique nonces. The **unattended side holds no decryption secret**.
- Upload under an object name with no financial identifiers. Success is recorded **only after readback hash verification**.
- Multiple recent points. Prune only after a newer point is verified.
- Restore to a **new** isolated database. Never overwrite. Compare fingerprints against the manifest and record elapsed time.
- Hard $0 with no paid prerequisite. A budget alert is not a cap.
- Failures are visible and keep the 25-hour overdue warning truthful. A backup failure never blocks a due sync.

## 3. Where the backup runs

| | A. Vercel jobs function, dispatched by the single Supabase cron as a separate job kind | B. GitHub Actions scheduled workflow in a dedicated private repo |
| --- | --- | --- |
| Time limit | 300 s function [D, [Vercel limits](https://vercel.com/docs/functions/limitations), checked 2026-10-01 in the feasibility pass]. The measured 35.6k dump took 1.5 s locally [M]. Network time 未核实. | "Each job in a workflow can run for up to 6 hours of execution time" [D, [Actions limits](https://docs.github.com/en/actions/reference/limits), 2026-10-02]. |
| PG 17 client | 17.11 package executes on Hobby [M, compatibility pass]. `api/backup.py` is not yet wired to it. | Pinned `postgres:17.11-alpine` image by digest (`sha256:b0f9…2b24`, recorded in the compatibility pass) as a job container. |
| Scheduler model | Fits "one scheduler": the jobs dispatcher owns both kinds. | **A second schedule.** It is read-only on the DB and holds no advisory lock, but it is still a second cron system. **Owner decision (P1-2).** |
| Coupling to sync | Must be separated from `tick` (R3: backup runs before sync in a thread that can outlive cancellation). | Fully decoupled from sync and Vercel. |
| $0 enforcement | Vercel Hobby usage. Billing APIs gave no data in M5 (UNKNOWN). | "If your account does not have a valid payment method on file, usage is blocked once you use up your quota" [D, [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions), 2026-10-02]. Free private: 2,000 min/month, 500 MB artifact storage [D, same]. Daily runs use far less [E]. |
| Schedule reliability | Supabase Cron + pg_net (Task 2) | "can be delayed during periods of high loads"; "some queued jobs may be dropped"; minimum interval 5 minutes. Scheduled workflows auto-disable after 60 days without activity **in public repositories** only [D, [events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), 2026-10-02]. |
| DB route | Session pooler, verified TLS [M] | Session pooler over IPv4. Runner IPv6 support 未核实, so direct IPv6 should not be assumed. |
| Status reporting | Writes `last_backup_*` in the same DB | Needs a narrow write path, e.g. a `backup_runs` table that only the backup role can `INSERT`. Otherwise status cannot see the result. |

**Owner decision, 2026-10-02: B adopted (P1-2).** The owner accepted a read-only second schedule. This is an explicit, scoped exception to plan §12.4's "Do not implement two competing cron systems". It holds only under these limits:
- the backup schedule runs a read-only export;
- it takes no advisory lock;
- it makes no financial writes, no Plaid call and holds no Fernet key;
- its only write is one `backup_runs` outcome row.

Any extension beyond that needs a new decision. Consequences:
- **R3 is resolved by design.** The cloud one-shot tick runs with `backup_fn=None` (as `run_scheduler_once` already allows), and Supabase Cron dispatches only `tick`.
- The Windows `tick` keeps its local daily backup unchanged until M8c.

Original recommendation text: **Recommendation: B**, if the owner accepts a read-only second schedule. It removes the backup-before-sync blocker (R3) without changing `tick`. It runs outside both Vercel and Supabase. It is the only option tonight with a documented hard-stop at the free quota. If the owner rejects a second schedule, use A with a separate job kind and its own claim, as plan §12.4 allows.

## 4. Storage destination

### 4.1 Candidates (all checked 2026-10-02 unless noted)

| Candidate | Permanent-free allowance [D] | Payment method / hard $0 | Reliability and credentials | Verdict |
| --- | --- | --- | --- | --- |
| **Backblaze B2** | "First 10GB storage is always free"; Class A/B/C free; Class D "first 2,500 calls per day are free"; "Free 3x monthly egress" ([pricing](https://www.backblaze.com/cloud-storage/pricing)) | Caps exist, but Class D cannot be capped; terms may let usage accrue (experiment doc, 2026-10-01) | Object store with prefix-scoped app keys; good fit technically | **Gate closed by owner.** Keep as alternative if the gate is reopened. |
| **Cloudflare R2** | "10 GB-month / month", 1M Class A, 10M Class B, egress "Free"; Standard only ([pricing](https://developers.cloudflare.com/r2/pricing/)) | Requires "Complete the checkout flow to add an R2 subscription" ([get started](https://developers.cloudflare.com/r2/get-started/)). Whether a card is required: 未核实. No documented hard cap. | S3 API with scoped tokens | Not selected: no proven $0 stop. |
| **GCS** | "5 GB-months of regional storage (US regions only)", 5,000 Class A, 50,000 Class B, 100 GB egress; only us-east1/us-west1/us-central1 ([free features](https://docs.cloud.google.com/free/docs/free-cloud-features)) | "A Google Cloud billing account is required" [D]. Budgets are alerts. | Service-account keys; mature | Not selected: billing account, no hard cap. |
| **GitHub private repo, release assets** | "There is no limit on the total size of a release, nor bandwidth usage"; each file "under 2 GiB"; up to 1,000 assets per release ([releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)). Availability on Free private repos 未核实 by doc quote. | No payment method needed. Storage has no stated charge [D]. AUP reserves the right to throttle "significantly excessive" bandwidth and to delete repos placing "undue strain" after notice ([AUP](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)). | Workflow `GITHUB_TOKEN` scoped to one repo (`contents: write`). The same permission can delete. | **Recommended primary** (with B in §3). A few MB per day is far from "excessive" [E]. |
| GitHub Actions artifacts | 500 MB total on Free, not reset monthly [D]; default retention 90 days ([artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/remove-workflow-artifacts)) | Blocked at quota without payment method [D] | Auto-expiry | Not selected: 90-day default retention cannot hold 3 monthly points. |
| Google Drive (personal) | "up to 15 GB of storage, which is shared across Gmail, Google Drive, and Google Photos" ([Google One](https://support.google.com/googleone/answer/9312312)) | No billing. Over quota blocks uploads [D]. | Unattended upload needs an OAuth refresh token for the owner's personal account, which is a broad credential. Service-account quota 未核实. | **Recommended secondary** copy, pulled manually (§4.3), not written by automation. |
| Supabase Storage | 1 GB on Free [D, pricing] | — | Same failure domain as the DB | Excluded (not independent). |
| Owner's PC | — | — | Same failure domain as current Production | Allowed only as an extra copy. Must not be required for recovery (plan §16.2 item 6). |

### 4.2 Recommendation — **adopted by the owner 2026-10-02 (P1-1)**

- **Primary:** a dedicated private GitHub repository used only for backups.
  - Each backup point is one **release** named `pft-backup-<UTC>-<16 hex>`, with three age-encrypted assets: `backup.dump.age`, `manifest.json.age` and `fingerprint.txt.age`.
  - Names carry no database name, kind or financial identifier.
- **Why:** it is the only candidate with a documented hard stop at $0 (Actions) and no stated storage charge (releases). It needs no payment method. It is independent of both Supabase and Vercel.
- **Store contract** (`deploy/backup_runner/release_store.py`):
  - create the release as a **draft**;
  - upload each asset;
  - download each asset again and compare SHA-256 with the local ciphertext (and with GitHub's reported `digest` when present);
  - only then publish.

  Drafts are never listed, so a crash mid-upload cannot be mistaken for a backup. Stale drafts older than one day are removed by the next run. The token is sent only to the API/upload hosts. Asset downloads follow the storage redirect **without** `Authorization`.
- **Risks, stated plainly:**
  - The AUP gives GitHub discretion over undue strain, and backups are not an explicitly documented use [D].
  - The workflow token that can publish can also delete releases.
  - Both are mitigated by the secondary copy (§4.3), not removed.

### 4.3 Secondary copy — **decided 2026-10-02 (P1-3)**

- **Monthly**, and in addition before any planned migration or cutover, the owner manually downloads the newest published point's three `.age` files.
- They go unchanged (still encrypted) to Google Drive **or** offline media.
- This is manual on purpose: no Drive credential exists in any automation.
- It covers loss or compromise of the GitHub account.
- Keep at least the last three monthly copies; older ones can be deleted.

## 5. Encryption, keys, frequency and retention

### 5.1 Encryption: age — **decided 2026-10-02 (P1-4)**

- **Tool and format:** the age CLI, **v1.3.2**, format age-encryption.org/v1, with X25519 recipients. The custom PFTENC3 prototype has been **removed** from the branch.
  - Why age: a standard, specified, widely implemented format. The official Go age and the independent Rust rage both read it, so a restore needs no PFT code (runbook).
  - Integrity: age authenticates every chunk. A wrong key, truncation or tampering fails decryption (tested [M]).
- **Pinning in the workflow:**
  - download `age-v1.3.2-linux-amd64.tar.gz` from the official release;
  - check it against the **SHA-256 digest published on the release page**: `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10`. It was looked up through the GitHub API on 2026-10-02 and re-computed after download [M].
  - The release has no separate checksums file. It also publishes Sigsum `.proof` files ("you can check their Sigsum proofs" [D, age README]). Verifying those would be optional extra hardening; it is not done.
- **Recipients:**
  - `config/recipients.txt` lists **at least two** X25519 public keys: a **daily** key and an **emergency** key. Comments are allowed.
  - The runner refuses fewer than two, duplicates, and anything that is not a plain `age1…` X25519 key (SSH keys, post-quantum `age1pq1…`, secret keys).
  - Every asset is encrypted to all recipients, so either private key alone decrypts every point (tested [M]).
  - Post-quantum hybrid keys (`age-keygen -pq`, age ≥ 1.3) are a possible future change. Not adopted.
- **Runner secrets:** none for encryption. The runner holds only public keys and the read-only database password.

### 5.2 Key custody

| | Daily key | Emergency key |
| --- | --- | --- |
| Generated | Offline, by the owner, on a trusted machine: `age-keygen \| age -p -o daily.key.age` | Same, separately: `emergency.key.age` |
| Protection | Passphrase-encrypted identity file (age's native format; age prompts for the passphrase on use) | Same, **different** passphrase |
| Stored at | Offline location **A** (e.g. encrypted USB at home), plus a printed copy of the file in the same place | Offline location **B**, physically separate (e.g. a safe-deposit box or a trusted person's safe) |
| Passphrase stored | Owner's password manager | Password manager **and** sealed paper away from location B |
| Used for | Monthly restore drills (§6) | Only when the daily key is unavailable; also one annual check |
| Public key | Line 1 of `config/recipients.txt` | Line 2 |

Also at each location: a copy of this runbook, `fingerprint.sql` and the age release archive.

Rules:
- Never put a private key or its passphrase in GitHub, Supabase, Vercel, the PFT repository, chat or a cloud drive.
- `age -d -i <file>.key.age` on a fresh machine is the only operation that needs one.

### 5.3 If a key is lost or exposed

1. **One key lost** (destroyed, or passphrase forgotten), not exposed:
   - All existing points remain decryptable with the other key. No data is at risk.
   - Generate a replacement key offline and put the replacement public key in place of the lost one in `recipients.txt`.
   - Run the workflow manually. Restore-drill the new point with the **replacement** key and with the surviving key.
   - Old points stay single-key until retention ages them out (≤ about 3 months). Re-encrypting them is optional and not recommended: it needs plaintext on a machine.
2. **One key possibly exposed** (lost device, leaked file **and** passphrase):
   - Assume every existing point is readable by whoever holds it **and** can download from the backup repository or the secondary copy.
   - Rotate as in 1 immediately.
   - Once three new verified points exist, delete the older points from releases and from the secondary copy.
   - Review backup-repository access and rotate the backup role password.
   - Plaid tokens in the dump remain Fernet-encrypted. The Fernet key is never in a backup, but treat its exposure separately if it may also be affected.
3. **Both keys lost:** every existing point is permanently unrecoverable.
   - Generate two new keys and take a new backup immediately.
   - The live database is then the only copy until it succeeds.
   - Separate locations and the annual check exist to make this unlikely.
4. **Annual check:** decrypt the newest `manifest.json.age` with **each** key and record the date. A forgotten passphrase is found while the other key still works.

### 5.4 Frequency and retention — **frequency decided 2026-10-02 (P1-5)**

- **Daily** scheduled run at 08:23 UTC. This is off the top of the hour, where GitHub documents high load and possible dropped scheduled runs.
- Plus a **manual** run (`workflow_dispatch`) before every migration, cutover or schema change.
- Twice a day would halve the RPO at negligible cost; not chosen for now.
- **Retention:** grandfather-father-son, **7 daily + 4 weekly + 3 monthly** (up to 14 points). This matches the tiers in `api/backup.py:RETENTION`. Prune only after the new point is published (readback complete); `prune` refuses otherwise.
- **Size:**
  - Drill [M]: 2,610 rows → 281,862 B stored dump; 35,600 rows → 3,314,822 B, plus about 23 KB of manifest and fingerprint.
  - Production M6 dump (historical): 420,774 B at 2,517 rows.
  - Projection: about 6 MB per point and about 84 MB for 14 points at 35.6k rows [E].

### 5.5 Transition: Windows formats stay unchanged until M8c

| Period | Windows runtime | Cloud |
| --- | --- | --- |
| Now → M8a | Unchanged: `api/backup.py` daily plain `pg_dump -Fc` + JSON manifest in the protected Windows directory (7/4/3 tiers). Optional external copies with `api/backup_crypto.py` (**PFTENC2**, password + scrypt) | None for Production. Drills on synthetic data only |
| M8a → M8c | Windows jobs, if resumed under an approved transition, keeps the same local backups of the then-authoritative DB | GitHub Actions age backups of Supabase start once approved (prerequisite C6 of the cutover draft) |
| After M8c | Windows jobs disabled; no new Windows backups | age backups are the only scheduled backups |
| Afterwards | Keep existing Windows dumps and PFTENC2 copies, recovery-only, for at least one year after M8c | — |

- `scripts/pft_backup_restore.py` restores **age points, PFTENC2 copies and plain local dumps** into a new local `pft_restore_*` database, and fingerprints the result with the same `fingerprint.sql`.
- Removing PFTENC2 support needs a separate decision, once no PFTENC2 copy is retained.
- Note: **PFTENC3 was never a Production format.** It existed only as last night's prototype and was replaced by age before any use.

### 5.6 Third-party actions and images: pinned by commit SHA or digest (owner rule, 2026-10-02)

- **Rule:** every `uses:` in the backup workflow must reference a **full 40-character commit SHA**, with the human-readable version as a trailing comment. A tag (`@v7`), branch (`@main`) or short SHA is never allowed.
  - GitHub: "Pinning an action to a full-length commit SHA is currently the only way to use an action as an immutable release" [D, [secure use](https://docs.github.com/en/actions/reference/security/secure-use), 2026-10-02].
- **Same rule for other inputs the workflow executes:**
  - container images by `@sha256:` digest;
  - downloaded binaries (age) by a pinned SHA-256 that is checked before use;
  - the runner's own files by `runner/SHA256SUMS`.
- **Current state:**
  - the only action is `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1`. The SHA was resolved from the tag through the GitHub API on 2026-10-02;
  - no other third-party action is used. Adding one requires the same pinning plus a review of what it executes.
- **Enforced:** `tests/test_m5_backup_age.py::test_workflow_pins_and_never_lives_in_github_workflows` fails if any `uses:` is not a 40-hex SHA, or if any image reference lacks a digest.
- **Updating a pin:**
  1. Resolve the new tag to its commit SHA through the API.
  2. Read the action's diff between the old and new SHA.
  3. Update the SHA and the comment together in one reviewed commit.
  4. Restage the backup repository.

  Dependabot-style automatic bumps are not used.

### 5.7 The backup database role (`pft_backup`, BYPASSRLS in Production): threat model and controls

**Why it is the most sensitive credential in the design.** In Production the role will have **BYPASSRLS** plus SELECT on every application table (§7 item 4).
- Whoever holds its password can read the complete financial history, overrides, statement evidence and Plaid token **ciphertext** directly from the live database. There is no age encryption in that path, no Auth/MFA and no application-level owner check.
- age protects stored backups. It does nothing for someone holding this password.

**Assets behind it:**
- every application table;
- Fernet-encrypted Plaid tokens. They stay useless without `PLAID_TOKEN_ENCRYPTION_KEY`, which is never stored with this role.

**Threats and controls:**

| Threat | Control |
| --- | --- |
| **Secret read by anyone who can change the workflow** (push access to `randytli/pft-backups`). GitHub **environments** (environment-scoped secrets, required reviewers) are not available for private repositories on GitHub Free: "Users with GitHub Free plans can only configure environments for public repositories" [D, [environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments), 2026-10-02]. Protected-branch availability for private repositories on Free is 未核实. | Only the owner has write access: no collaborators, deploy keys or third-party GitHub Apps with repository write. GitHub account MFA. Every change to `.github/workflows` and `runner/` is reviewed, and only reviewed PFT commits are staged (`STAGED_FROM.txt`, `SHA256SUMS`). |
| **Compromised third-party action or image** exfiltrating the job environment | §5.6 pinning; only one third-party action (`actions/checkout`, run with `persist-credentials: false` before the secret is in scope). The secret is set only in the env of the single step that needs it. |
| **Secret leaked into logs** | The runner never prints its environment or connection strings, and keeps only the first line of tool stderr. GitHub redaction is a backstop only: "automatic redaction is not guaranteed" and fails on transformed or structured values [D, secure use]. The password is never placed in JSON, URLs or command lines; it travels only in `PGPASSWORD`, passed by name to the container. |
| **Password reused or guessed** | At least 32 random characters, generated by the owner. Used for this role only and stored only in the GitHub secret. Never typed into chat, files or the PFT repository. |
| **Use from anywhere** (Supavisor is internet-reachable) | `verify-full` TLS. Optional Supabase network restrictions apply to pooled and direct routes [D], but Free availability is 未核实 and GitHub runner egress IPs vary, so this is not relied on. |
| **Role does more than read** | NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT, NOREPLICATION; no role memberships; `default_transaction_read_only=on`; SELECT grants only; connection limit 2; `statement_timeout=15min`. Already true of the synthetic role [M]. **BYPASSRLS** is added in Production only, and only because `pg_dump` requires it under the RLS backstop. **TEMP via PUBLIC** is a known gap, removed at Production configuration time (inventory R16; owner decision 2026-10-02: closed together during Production configuration, cutover prerequisite C4). |
| **Undetected misuse** | Supabase Free log retention is 1 day [D, pricing], so there is no long audit trail. Compensating control: the workflow records each run's start/end. A periodic owner check of `pg_stat_activity` and `pg_roles` for `pft_backup` sessions outside the 08:23 UTC window is a manual step. Automated alerting is not available at $0 (推测). |
| **Compromise suspected** | 1. `ALTER ROLE pft_backup NOLOGIN` immediately (stops new sessions).<br>2. Terminate its sessions.<br>3. Rotate the password and the GitHub secret.<br>4. Review repository access and the audit log.<br>5. Treat the database contents as disclosed, but Plaid tokens as still protected unless the Fernet key is also exposed.<br>6. `LOGIN` again only after review. |

**Scope today:**
- the synthetic M5 project only;
- the role has **no password and no BYPASSRLS** (§7);
- Production role creation is part of the cutover (C4/C6), under its own approval.

## 6. Restore drill and fingerprint verification

**Backup side** (`deploy/backup_runner/pft_backup_runner.py` with `snapshot_dump.sql`):
1. **Connection policy:** a remote source needs `PGSSLMODE=verify-full` plus `PGSSLROOTCERT`. Plaintext is accepted only for loopback test clusters on port ≥ 55000.
2. **Schema coverage:** fail closed if any non-system, non-provider schema is not selected (`PROVIDER_SCHEMAS` is still 未核实 against a real project).
3. **One psql session:**
   - `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`;
   - database identity check (a wrong database aborts before any dump);
   - `pg_export_snapshot()`;
   - `pg_dump --snapshot=…`;
   - `fingerprint.sql`, in the same snapshot.
4. **Archive check:** the TOC must contain `TABLE DATA` for every fingerprinted table.
5. Write the manifest, encrypt all three files with age to all recipients, delete the plaintext, then store and prune.

**`fingerprint.sql`** is plain psql, so it works with no PFT code. It prints one sorted line per object and no database name:
- per-table row count and SHA-256 over per-row SHA-256 of canonical `to_jsonb` text (memory-bounded);
- sequences;
- PK/FK/unique constraint definitions;
- CHECK constraint **names** (PostgreSQL rewrites some CHECK expressions on restore [M]);
- index definitions;
- column type/nullability/default.

Rendering settings are pinned: UTC, `search_path`, `bytea_output`, `extra_float_digits`, `IntervalStyle`.

**Restore side:**
- **With PFT code:** `scripts/pft_backup_restore.py` does download → decrypt (daily or emergency key) → manifest hash checks → `createdb` of a new database (fails if it exists) → `pg_restore --exit-on-error --no-owner --no-privileges -L <list>`. The list skips only `SCHEMA public` create/comment, so `DROP SCHEMA public` is never needed. It then fingerprints and compares.
- **Without PFT code:** [restore runbook](PFT_BACKUP_RESTORE_RUNBOOK.md), using `age`, `pg_restore`, `createdb`, `psql`, `diff`.

**Drill cadence (operation):**
- Monthly, with the daily key; annually with the emergency key; after any key, tool or major-version change.
- Restore into a fresh PostgreSQL **17** environment, matching Supabase 17.x.
- After fingerprints match, start the app read-only against the restore with jobs and Plaid disabled. Check totals and token decryption without calling Plaid (plan §16.2 item 5). Record the elapsed time.

### Local results [M]

Disposable PostgreSQL 16.15 on 127.0.0.1:55439 in the scratchpad, deleted afterwards. age v1.3.2, release digest verified. Fixture `scripts/pft_m5_backup_fixture.py` populates **all 15 tables** with random payloads, overrides, statement evidence, sync state and Fernet-encrypted synthetic tokens. Raw output: [backup-age-drill.json](evidence/m5-2026-10-02/backup-age-drill.json).

| Rows (raw) | Archive | Stored assets | Create: dump + fingerprint + encrypt ×3 + store + readback + prune | Restore with **emergency key only** + verify | Equal |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2,611 | 281,500 B | 305,111 B | 0.208 s | 0.333 s | yes |
| 35,601 | 3,313,724 B | 3,338,074 B | 1.090 s | 1.377 s | yes |

Single loopback runs; no network, TLS, pooler or GitHub time.

`tests/test_m5_backup_age.py`: **20 pass**. 6 need the database opt-in (`PFT_M5_BACKUP_SYNTHETIC_TEST=1`) plus `PFT_AGE_BIN`; 3 more need only `PFT_AGE_BIN`.

- **Recipients and policy:**
  - fewer than two keys, duplicates, SSH, post-quantum and secret keys are rejected;
  - the loopback/verify-full connection policy is enforced.
- **Runner bundle:**
  - `SHA256SUMS` must match the runner files;
  - workflow pins: age version + checksum, checkout SHA, image digest;
  - the template must not be under `.github/workflows`.
- **Retention and local store:** 7/4/3 coverage; atomic put; readback failure leaves nothing behind; prune refuses without a verified newest point.
- **GitHub store against a local fake API with a separate fake storage host:**
  - a point publishes only after readback;
  - storage never receives `Authorization`;
  - a corrupted upload leaves no release;
  - a crashed run leaves only an invisible draft, which is later removed;
  - pagination beyond 100 releases works;
  - a wrong token and untrusted hosts are rejected.
- **age:**
  - each of the two keys alone decrypts;
  - a stranger key, tampering and truncation fail;
  - a passphrase-protected identity file works.
- **Full chain:**
  - emergency-key restore equals the source fingerprint;
  - a committed write injected **between snapshot export and pg_dump** is in neither the dump nor the fingerprint. A mutation check removing `--snapshot` makes this test fail [M];
  - a changed row and a dropped index are reported by name;
  - container-style wrapper mode works;
  - the runbook commands work with no PFT code;
  - wrong database, unselected schema, wrong key and an existing target all fail closed;
  - Windows plain dump and PFTENC2 restore to the source fingerprint.

**Not tested locally:**
- the real `docker run` of the pinned PG 17 image (`env` stands in for the wrapper);
- the real GitHub API;
- verify-full TLS to Supabase;
- `--snapshot` through Supavisor session mode (推测 to work; 未核实).

These are the approved real run (§7).

## 7. What remains for G7 (needs approval)

1. Owner decisions P1-1…P1-5 are recorded (2026-10-02). Nothing is pending there.
2. **Approvals still needed:**
   1. ~~create the dedicated private backup repository~~ **done by the owner 2026-10-02: `randytli/pft-backups`** (private, initial README; anonymous API 404 [M]). Installing the template (stage → review → commit → push) still needs approval; install order in `deploy/backup_runner/README.md`;
   2. the owner generates the two key pairs offline and commits only the public keys;
   3. ~~create the read-only `pft_backup` role on the synthetic M5 project~~ **done 2026-10-02** (migration `m5_backup_role`) [M]:
      - LOGIN with **no password yet**; no superuser/createdb/createrole/replication/bypass-RLS; no role membership;
      - connection limit 2; `default_transaction_read_only=on`, `statement_timeout=15min`;
      - SELECT on exactly the 31 tables of `pft_m5_bench_2610`, `pft_m5_bench_35600`, `pft_m5_probe`, with no other table privileges;
      - no `auth` usage, no CREATE; TEMP through PUBLIC (known gap R16);
      - security advisor: no lints.

      Setting its password and the single repository secret waits for the keys.
   4. run the workflow manually against the synthetic project, then download on a different machine, restore to PostgreSQL 17 using the runbook, and compare fingerprints.
3. During that run, verify:
   - ~~`PROVIDER_SCHEMAS`~~: checked 2026-10-02 against the synthetic project's real schema list [M];
   - `--snapshot` through the session pooler;
   - GitHub's asset `digest` field;
   - whether scheduled-run failures notify the owner (GitHub's notification behaviour for scheduled workflows is 未核实).
4. **Production role and RLS (found 2026-10-02).** With the RLS backstop of the Auth design, `pg_dump` (default `row_security=off`) errors for a role without BYPASSRLS. That is fail-closed, not silently partial. So the Production `pft_backup` role needs **BYPASSRLS**.
   - Do **not** use `--enable-row-security`: dump and fingerprint would both see only policy-visible rows and agree on an incomplete backup.
   - On the synthetic project, `postgres` has CREATEROLE and BYPASSRLS [M]. Under PostgreSQL 16+ rules it should therefore be able to create a BYPASSRLS role [E]. Test this in M7.
5. M6:
   - a `backup_runs` outcome row written by the backup role, for honest status and the 25-hour overdue warning;
   - failure tests from plan §16 "Tests": temp space, expired credentials, quota denial, paused DB, pruning failure.

## 8. Files

- `deploy/backup_runner/pft_backup_runner.py`, `release_store.py`, `snapshot_dump.sql`, `fingerprint.sql`, `SHA256SUMS`, `pft-backup.yml`, `README.md`, `stage_backup_repo.py`: runner, stores, workflow template and the staging helper for `randytli/pft-backups`. Standard library only.
- `scripts/pft_backup_restore.py`: multi-format restore tool (age, PFTENC2, plain local dump).
- `scripts/pft_m5_backup_fixture.py`: populated synthetic fixture.
- `tests/test_m5_backup_age.py`: tests.
- `docs/PFT_BACKUP_RESTORE_RUNBOOK.md`: restore without PFT code.
- `docs/evidence/m5-2026-10-02/backup-age-drill.json`: measured results.

`api/backup.py`, `api/backup_crypto.py` and `api/jobs.py` are unchanged; the Windows backup is untouched.
