# DRAFT — Production → Supabase cutover and rollback (M8a) — 2026-10-02

**Status: DRAFT ONLY. NOT EXECUTABLE. Nothing in this document was run.** M5 has not issued SERVERLESS_GO, and M6/M7 have not happened. Plan §12 states that M5 "cannot authorize a Production migration". This draft exists so the M8a packet can be reviewed early. Every prerequisite in §1 must be closed, and the packet regenerated from the then-current runtime, before any step is considered.

Format follows the [diff-writes packet](PFT_SYNC_DIFF_WRITES_PRODUCTION_ACTION_PACKET_2026-10-01.md) and the [M6 cutover record](PFT_M6_CUTOVER_STAGE1_2026-09-23.md). Labels:
- **[READ-ONLY]** no state change.
- **[LOCAL]** changes only local Git or local files outside Production.
- **[STATE]** changes Production containers, images, backups or data, *or* cloud state (Supabase / Vercel / GitHub), with the effect named.
- **[M]** measured; **[E]** estimate.

Every **[STATE]** step needs the owner's explicit approval at execution time, one command at a time.

Scope: plan §15.1–15.3 (M8a): **database authority only**. M8b (authenticated reader), M8c (cloud scheduler) and M8d (writes) are separate packets with their own gates. They are summarised in §6 only to show the boundaries.

## 1. Prerequisites (all open)

| # | Prerequisite | Source |
| --- | --- | --- |
| C1 | SERVERLESS_GO accepted; M6 code and M7 rehearsal passed on synthetic data, including this exact procedure end to end | plan §12–§14 |
| C2 | Identity sentinel (`dataset_id`, `deployment_id`) added to Production by an approved additive migration, and checked by every writer and tool | plan §15.1 |
| C3 | `scripts/pft_m6_fingerprint.py` gains a verified-TLS remote profile (CA + hostname) with identity checks; today it connects without TLS settings. `deploy/backup_runner/fingerprint.sql` already runs over any psql connection (`PGSSLMODE=verify-full`) | plan §15.2 |
| C4 | Target Supabase project: Data API off, RLS backstop, roles from the [Auth design §7](PFT_M5_AUTH_DESIGN_2026-10-02.md#7-rls-and-database-roles), TLS enforcement on, known issue R16 closed (`REVOKE TEMP ON DATABASE … FROM PUBLIC`, explicit TEMP only where a role needs it, Supabase-internal role needs 未核实); `anon`/`authenticated` revoked including default privileges | plan §15.1 |
| C5 | PostgreSQL **17** client and a PG 17 recovery environment. Source is PG 16.15 [M, M6 record]; target 17.11 [M, compatibility pass]. A newer pg_restore reads older archives; the reverse is not assumed | plan §15.1 |
| C6 | Independent backup path working against the target ([backup design](PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md)), with a successful real restore drill | plan §15.2 |
| C7 | Remote-DB Compose definition with no local `db` dependency and a single authoritative `DATABASE_URL` (jobs currently loads two env files that both contain it) | plan §15.2 |
| C8 | Window chosen: no sync or backup running, next scheduled sync ≥ 2 h away (owner rule). Today's daily sync runs around 19:35 UTC [M, diff-writes packet] | memory: approval gates |

Reference size: about 2,615 consumer rows read per sync, average Plaid payload 1,565 B [M, diff-writes packet]. The M6 pre-cutover dump was 420,774 B [M]. A dump, restore and import of this size takes seconds; the window is dominated by verification [E].

## 2. Fixed values

Same shell setup as the diff-writes packet. Private evidence goes to `$P` (mode 0700, never committed). The Production stack uses its pinned `running-images.yml` with `--no-build --pull never`, and `.env*` files are never printed. New values:

```bash
export TARGET_REF=<new production project ref>       # pinned; never the M5 synthetic project
export TARGET_HOST=<session pooler host>              # from the project's Connect dialog
export SUPABASE_CA=<path to provider root CA>          # verify-full; fingerprint recorded in packet
export P=/tmp/pft-m8a-cutover-$STAMP                   # private evidence directory
```

## 3. Procedure

### Step 0 — Preflight [READ-ONLY]

1. Re-check the M0-style Production identity:
   - database `pft_production_backfill`, PostgreSQL 16.15;
   - Compose project `pft-runtime`;
   - running image IDs equal the pin file;
   - five active Items and their account scope.
2. Fingerprint **F0** with `pft_m6_fingerprint.py` (repeatable read, UTC). This is only the baseline for planning.
3. Target project:
   - identity: project ref, server 17.x, sentinel table empty or absent as planned;
   - Data API disabled; RLS and grant inventory as expected;
   - no application tables yet;
   - no cron jobs; no Vercel deployment pointing at it.
4. Stop if anything differs.

### Step 1 — Freeze writers [STATE: no automatic sync/backup; app unavailable for the window]

1. Confirm no sync or backup is running (`/sync/status`, `sync_runs` with `status='running'`).
2. Stop **jobs** [STATE].
3. Stop **api** and **web** [STATE]. The current code has no read-only mode, so stopping them is the only enforced mutation freeze. Leave the DB running.
4. Confirm no application sessions remain in `pg_stat_activity` and no advisory locks are held [READ-ONLY].
5. Record `requested/handled/running_sequence`, last run IDs and every Item's cursor-presence flag [READ-ONLY]. Do not reset them.

### Step 2 — Frozen-source fingerprint and dump

1. **F1** = full fingerprint, repeatable read, UTC [READ-ONLY].
2. Fresh custom-format dump through the existing guarded adapter: `api/backup.py create --kind extra` inside the jobs image, as in M6 [STATE: new file in the protected Windows backup directory]. Record size, SHA-256 and `pg_restore -l` [READ-ONLY].
3. **F2** = fingerprint again [READ-ONLY]. **F2 must equal F1**, which proves no writer ran during the dump. Otherwise stop and return to Step 1.

### Step 3 — Isolated restore proof [LOCAL]

1. Restore that exact archive into a new disposable **PG 17** cluster on loopback, using `scripts/pft_backup_restore.py` (local-dump format) or the [restore runbook](PFT_BACKUP_RESTORE_RUNBOOK.md) steps:
   - `createdb` a new database;
   - `pg_restore --exit-on-error --no-owner --no-privileges -L <list without SCHEMA public>`.
2. **F_iso** = fingerprint of the restore. Require F_iso == F1 for every table count and hash, institution/source breakdown and integrity count.
3. Also compare `deploy/backup_runner/fingerprint.sql` output of source and restore. It must be identical: it lists CHECK constraints by name only, because PostgreSQL rewrites some CHECK expressions on restore. Any difference stops the cutover.
4. Never use a stale preflight dump (plan §15.3 step 4).

### Step 4 — Import into Supabase [STATE: target receives the application object set]

1. As `pft_migrator`, over verified TLS: `pg_restore` (PG 17) of the **same archive**:
   - `--exit-on-error --single-transaction --no-owner --no-privileges -L <same filtered list>`;
   - restore only the `public` application objects;
   - never restore over `auth`, `storage`, `extensions` or other provider schemas;
   - never run `DROP SCHEMA public CASCADE` (plan §15.3 step 5).
2. Apply the reviewed grants, RLS and identity script for the target [STATE]. Set the target's distinct `deployment_id`; `dataset_id` follows the data (plan §15.1).
3. **F3** = target fingerprint via the TLS profile [READ-ONLY]. Require F3 == F1 for:
   - table counts and full-row hashes;
   - Items/status/scope, accounts;
   - token-ciphertext digest, cursor digest;
   - every override and audit table, statement batches/rows/evidence;
   - classifications, publication state and runtime request sequences.

   Only the identity sentinel rows may differ, compared separately with the stated reason (plan §15.3 step 6). Never omit a whole table to hide a difference.

### Step 5 — Read-only verification on the target

1. Start **only** the local API in read-only mode against Supabase, using the remote Compose file (C7) [STATE: local api container against the target; no jobs, no web writes].
2. Verify:
   - startup identity and schema checks;
   - monthly, canonical-category, institution/account and Membership totals equal the pre-freeze values;
   - token decryption through a controlled tool that prints only counts. No Plaid call.
3. **F4** = target fingerprint [READ-ONLY]. Require F4 == F3, which proves the read-only phase wrote nothing.

### Step 6 — Target backup and restore [STATE: first independent backup object of the target]

1. Run the independent backup against the target with the real profile.
2. Restore it into a fresh PG 17 environment that has no access to the old PC files.
3. Require its fingerprint == F3 (plan §15.3 step 8).
4. Verify session-lock behaviour only with synthetic isolated data, never with a Production sync.

### Step 7 — Authority handoff [STATE: Supabase becomes the sole authoritative DB]

1. Record in the handoff note:
   - source/target identities, F1/F3/F4 digests, archive SHA-256, backup object ID;
   - the fact that **no financial writer is running anywhere**.
2. Old local DB:
   - set restart policy to `no`, then stop the `pft-runtime` `db` [STATE];
   - keep the volume **recovery-only**: no `down -v`, no deletion.
3. Remove or rename old local env paths so no tool can write to the old DB by accident [LOCAL / STATE: local config only].
4. **Writers stay paused** until M8c (cloud scheduler) or an explicitly approved transitional Windows jobs worker against Supabase (plan §15.3 step 10). There are never two writers and never an ambiguous scheduler.

## 4. Fingerprint comparison summary

| Point | Database | Must equal | Proves |
| --- | --- | --- | --- |
| F0 | Source | — | Planning baseline only |
| F1 | Source, frozen | — | Frozen reference |
| F2 | Source after dump | F1 | No writer during dump |
| F_iso | Isolated PG 17 restore | F1 | Archive is complete and restorable |
| F3 | Supabase after import | F1 (sentinel separate) | Import complete |
| F4 | Supabase after read-only checks | F3 | Read-only phase wrote nothing |
| F_bk | Restore of first target backup | F3 | Independent recovery of the new authority |

Rules for all comparisons:
- Session time zone is UTC.
- Columns are compared in full, including `created_at`/`updated_at`. No sync runs between points, so timestamps must match too.
- Catalog differences are allowed only for the documented equivalent rewrite.
- After the first post-handoff sync, only expected sync/run/cursor and new-row changes may appear. Explain them in writing, as in the diff-writes packet.

## 5. Rollback

**Before Step 7 (no target writes accepted):**
1. Stop any target client (local API in read-only mode) [STATE].
2. Confirm the target is unchanged: fingerprint == F3 [READ-ONLY]. Keep it for forensics; delete it only with separate approval.
3. Confirm the local source is intact: start the local `db` if stopped, then fingerprint == F1 [READ-ONLY].
4. Restart **api, web, then jobs** from the pinned `running-images.yml` with `--no-build --pull never` [STATE].
5. Check `/sync/status` and heartbeat. The next due sync runs on its normal schedule; do not force one.
6. The source never accepted writes during the freeze, so nothing needs merging.

**After Step 7 (Supabase is authoritative and may have new writes):**
1. **Freeze all writers first**, then take a new target backup [STATE].
2. Prefer fixing forward, or rolling back application code against the same Supabase DB (plan §15.3 "Rollback after target writes").
3. Returning authority to the PC is a **separately approved reverse migration** of the latest cloud state into a **PG 17**-compatible local runtime (C5). The current local PG 16 runtime is not assumed able to restore a PG 17 dump.
4. **Never restart the stale pre-cutover local DB as a writer, and never rewind cursors.**

**Stop conditions (any step):**
- unexplained hash or analytics mismatch;
- unverifiable target identity or TLS;
- unsupported version;
- backup or restore failure;
- any lock or connection workaround that weakens a control;
- an unexpected writer.

## 6. Later stages (separate packets, outline only)

- **M8b, authenticated reader:**
  - deploy the reviewed commit to Vercel with the reader role, Supabase Auth (signup closed, `aal2`) and Data API off;
  - run the direct-API negative tests;
  - check analytics against F3-era totals.

  Rollback: withdraw the deployment; Supabase authority stays.
- **M8c, cloud scheduler:**
  - fresh backup;
  - stop and **disable** Windows jobs and its restart paths;
  - enable the single signed Supabase Cron ([cron design](PFT_M5_CRON_TRIGGER_DESIGN_2026-10-02.md));
  - observe a legitimate due cycle.

  Rollback: unschedule cron, drain, verify no lock owner, then optionally one Windows jobs worker against the **same** Supabase DB under approval.
- **M8d, writes:**
  - switch the API role and capability to the writer;
  - make scoped reversible override edits and restore them.

  Rollback: back to reader mode.
