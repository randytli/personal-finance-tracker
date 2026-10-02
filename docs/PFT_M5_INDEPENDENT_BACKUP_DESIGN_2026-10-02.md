# M5 independent encrypted backup and restore — design and local drill (2026-10-02)

**Status: design plus a local synthetic prototype. This does not close SERVERLESS_GO criterion G7.** G7 also needs a real upload, readback and download from the chosen store, and a restore of the managed PostgreSQL 17 object set on a fresh environment. Both need owner approval. No cloud resource was created or contacted. Production, Supabase, Vercel and Plaid were not touched.

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

- **Primary:** a dedicated private GitHub repo used only for backups. Each backup is one release asset named `pft-backup-<UTC>-<random>.pftenc3`. It carries no database name, kind or financial identifier (implemented in the prototype `object_name`).
- **Why:** it is the only candidate with a documented hard stop at $0 (Actions) and no stated storage charge (releases). It needs no payment method. It is independent of both Supabase and Vercel.
- **Risks, stated plainly:**
  - The AUP gives GitHub discretion over undue strain, and backups are not an explicitly documented use [D].
  - A compromised workflow token can delete releases.
  - Both are mitigated by the secondary copy, not removed.

### 4.3 Secondary copy

- Weekly or monthly, the owner downloads the newest verified asset and keeps it in Google Drive or offline media. This is manual, so no unattended credential for Drive exists.
- It covers loss of the GitHub account.
- **Owner decision (P1-3):** cadence, or whether to skip it.

## 5. Encryption, keys, frequency and retention

- **Envelope `PFTENC3`** (prototype `scripts/pft_m5_backup_drill.py`):
  - **Key agreement:** X25519, ephemeral-static. HKDF-SHA256 over the ECDH secret, with salt = ephemeral ‖ recipient public keys.
  - **Cipher:** AES-256-GCM with a 96-bit random nonce, under a fresh key per bundle.
  - **Header:** magic, recipient key ID (SHA-256 of the raw public key), ephemeral public key, nonce and length. The whole header is authenticated as AAD.
  - **Payload:** the manifest, then the archive. The 16-byte tag is appended.
  - **Decryption** publishes plaintext only after both the tag and the manifest's archive SHA-256 verify.
  - **Crypto library:** `cryptography` 41.0.7, already pinned.
  - **Why public-key:** the backup runner needs only the **public** key, so a leaked runner cannot decrypt.
  - **Review needed:** this composes reviewed primitives, but it is a custom format. **Owner decision (P1-4):** keep PFTENC3 after an independent review, or switch to `age`, a standard format with an external binary in every recovery environment.
- **Key custody:**
  - The owner generates the X25519 key pair offline on a trusted machine, never in CI or chat.
  - The private key is stored as a passphrase-encrypted PKCS#8 PEM in two places: the owner's password manager and an offline copy (USB or paper). The passphrase is kept separately.
  - Only the public key goes to the runner.
  - The Fernet token key and Supabase credentials are **not** in the backup or the runner beyond the DB read role. Plaid tokens stay Fernet-encrypted inside the dump.
  - A lost private key means all backups are unrecoverable. The restore drill (§6) proves the owner can still open it.
- **Frequency:** daily, matching the current 24 h, plus on demand before any migration, cutover or schema change. Twice a day would halve the RPO at negligible cost [E]. **Owner decision (P1-5).**
- **Retention:** grandfather-father-son, **7 daily + 4 weekly + 3 monthly** (up to 14 points). This matches the tiers in `api/backup.py:RETENTION`. In practice local jobs only create `daily`, so the cloud policy covers at least as much as local. Prune only after the new point is verified (`prune` refuses otherwise).
- **Size:**
  - Drill [M]: 2,610 rows → 281 KB archive; 35,600 rows → 3.31 MB. Random payloads.
  - Production M6 dump (historical, from repo doc): 420,774 B at 2,517 rows, i.e. ~167 B/row compressed.
  - Projection at 35.6k rows: ~6 MB per point, ~84 MB for 14 points [E].

## 6. Restore drill and fingerprint verification

Prototype commands (local only):

```sh
.venv/bin/python -m scripts.pft_m5_backup_drill create --source-url ... --recipient pub.pem --store DIR --work-dir DIR
.venv/bin/python -m scripts.pft_m5_backup_drill restore --store DIR --object NAME --private-key key.pem --target-url ... --work-dir DIR
```

**Backup side:**
1. Open a `REPEATABLE READ READ ONLY` transaction with session time zone UTC, then `pg_export_snapshot()`.
2. Inside that snapshot, compute the fingerprint:
   - per-table count and SHA-256 of canonical sorted `to_jsonb` rows (same function as `scripts/pft_m6_fingerprint.py`);
   - sequence states;
   - a digest of constraint, index and column DDL.
3. Run `pg_dump -Fc --snapshot=<id> -n public …`. The archive and the fingerprint describe the **same** committed state (plan §16.1).
4. Fail closed on coverage problems:
   - an unselected non-provider schema exists;
   - the archive TOC lacks `TABLE DATA` for any fingerprinted table.
5. Seal, upload, read back and hash-check. Prune only after that.

**Restore side:**
1. Download and authenticate. Verify the archive hash against the manifest.
2. Refuse if the target equals the source.
3. `createdb` the new `pft_restore_m5_*` database. It fails if the target exists.
4. `pg_restore --exit-on-error --no-owner --no-privileges -L <list>`. The list skips only the dump's `SCHEMA public` create and comment, because every new database or managed project already has `public`. It never runs `DROP SCHEMA public` (plan §15.3).
5. Fingerprint the restored database under the same rules and compare to the manifest. Any table, sequence or catalog difference is listed by name.

**One DDL normalization:** PostgreSQL rewrites `(ARRAY['a'::varchar,…])::text[]` CHECK expressions to `ARRAY[('a'::varchar)::text,…]` on restore [M]. Only that equivalent form is normalized, as the earlier M5 recovery probe did. A test shows that a changed literal is still detected.

**Drill cadence for operation (proposal):** monthly, plus after any key, tool or major-version change. Restore into a fresh PostgreSQL **17** environment, matching Supabase 17.11 [M, compatibility pass]. A PG 16 client should not be assumed to read PG 17 archives (未核实, but plan §15.1 warns about it). After the fingerprints match, start the app read-only against the restore with jobs and Plaid disabled. Check monthly, category and Membership totals and token decryption, without calling Plaid (plan §16.2 item 5). Record the elapsed time.

### Local drill results [M]

Disposable PostgreSQL 16.15 on 127.0.0.1:55439, scratchpad, deleted afterwards. Synthetic fixture `scripts/pft_m5_backup_fixture.py` populates **all 15 tables**: overrides of every kind, statement batch, row and evidence, sync runs, Item runs, runtime state, Fernet-encrypted synthetic tokens and random payloads. Raw output: [backup-drill.json](evidence/m5-2026-10-02/backup-drill.json).

| Rows (raw) | Total rows | Archive | Sealed | Create (fingerprint + dump + seal + store + readback + prune) | Restore + verify | Equal |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2,611 | 5,255 | 281,419 B | 283,965 B | 0.197 s | 0.363 s | yes |
| 35,601 | 71,235 | 3,314,161 B | 3,316,710 B | 1.491 s | 1.752 s | yes |

Single runs on loopback. These exclude network, TLS, pooler and provider time.

`tests/test_m5_backup_drill.py`: **12 tests pass**, 3 of them on the database (opt-in `PFT_M5_BACKUP_SYNTHETIC_TEST=1`). They cover:
- envelope round trip;
- wrong key, ciphertext tamper, header tamper, truncation and manifest-hash mismatch all publish nothing;
- no overwrite;
- store readback rejection;
- retention covers 7/4/3, and prune refuses without a verified newest point;
- profile guards reject non-loopback hosts, ports 5432/5434, Production env and non-drill names;
- catalog normalization is narrow;
- full chain on a populated database:
  - a write made after the backup does not appear in the restore, which proves snapshot consistency;
  - a changed restored row is reported as `tables:public.accounts`, and a dropped index as `catalog`;
- an existing target and a wrong key are refused;
- an unselected application schema fails closed.

## 7. What remains for G7 (needs approval)

1. Owner decisions: P1-1 (GitHub private repo releases) and P1-2 (GitHub Actions runner) **decided 2026-10-02**. P1-3 (secondary copy), P1-4 (envelope format) and P1-5 (frequency) remain open.
2. Create the private backup repo, the read-only Supabase backup role, and the workflow with the public key only. The owner generates the real key pair offline.
3. Real run against the **synthetic** M5 project:
   - PG 17 dump through the session pooler with verified TLS;
   - verify that `pg_export_snapshot` + `--snapshot` works through Supavisor session mode (推测 that it does, because each client gets its own backend; 未核实);
   - upload, readback, download on a different machine, restore to a fresh PG 17, fingerprint match.
4. Confirm the Supabase-managed schema list in `PROVIDER_SCHEMAS` against the real project. It is 未核实; the drill fails closed on unknown schemas.
5. Status integration (backup outcome row, 25-hour warning) and failure tests from plan §16 "Tests":
   - temp-space exhaustion;
   - expired credentials;
   - quota denial;
   - paused DB;
   - pruning failure.

## 8. Files

- `scripts/pft_m5_backup_drill.py`: drill prototype (envelope, fingerprints, store, retention, create/restore).
- `scripts/pft_m5_backup_fixture.py`: populated synthetic fixture.
- `tests/test_m5_backup_drill.py`: tests.
- `docs/evidence/m5-2026-10-02/backup-drill.json`: measured results.

`api/backup.py`, `api/backup_crypto.py` and `api/jobs.py` are unchanged. The local guarded backup is untouched.
