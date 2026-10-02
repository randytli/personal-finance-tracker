# PFT backup runner (GitHub Actions + age)

Source of truth for the independent cloud backup (owner decisions P1-1, P1-2 and P1-4, 2026-10-02). Design: [docs/PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md](../../docs/PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md). Recovery without any PFT code: [docs/PFT_BACKUP_RESTORE_RUNBOOK.md](../../docs/PFT_BACKUP_RESTORE_RUNBOOK.md).

**Backup repository: `randytli/pft-backups`.** The owner created it on 2026-10-02: private, with an initial README commit. Anonymous API access returns 404 while the user exists, consistent with private visibility [M].

**Nothing is installed there yet.** Pushing files, creating keys, roles and secrets, and running the workflow each need the owner's separate approval.

| File | Purpose |
| --- | --- |
| `pft_backup_runner.py` | One backup run. Standard library only. |
| `release_store.py` | GitHub release store (draft → upload → readback → publish) and the local store. Standard library only. |
| `snapshot_dump.sql` | psql script: identity check, exported snapshot, `pg_dump --snapshot`, fingerprint of the same snapshot. |
| `fingerprint.sql` | Deterministic fingerprint; also used by restores, standalone. |
| `pft-backup.yml` | Workflow template. Not active in this repository. |
| `SHA256SUMS` | Hashes of the four runner files as `runner/<file>`. Checked by the workflow; `tests/test_m5_backup_age.py` fails if it is stale. |
| `stage_backup_repo.py` | Copies exactly the files above (plus `RESTORE.md` and an example recipients file) into a local clone of the backup repository and verifies `SHA256SUMS`. Never runs git. |

## Layout of the dedicated private backup repository

```
.github/workflows/pft-backup.yml   ← copy of pft-backup.yml
runner/                            ← the four runner files + SHA256SUMS, copied from a reviewed PFT commit
config/recipients.txt              ← two age X25519 public keys: daily, emergency (public, not secret)
config/supabase-ca.crt             ← Supabase public root CA (verify-full)
RESTORE.md                         ← copy of docs/PFT_BACKUP_RESTORE_RUNBOOK.md
```

Stage with `python3 deploy/backup_runner/stage_backup_repo.py <clone of randytli/pft-backups>`. It records the PFT commit in `STAGED_FROM.txt` and refuses uncommitted runner files or overwriting existing ones.

## Install order (each step separately approved)

Schedule last, so the daily schedule never runs against an incomplete setup. Every failure would send a notification, although the runner fails closed.

1. **Keys (owner, offline).** Create `daily.key.age` and `emergency.key.age` (backup design §5.2). Write the two **public** keys into `config/recipients.txt` in the clone.
2. **Database role.** Create the read-only `pft_backup` role on the **synthetic** M5 project. In the backup repository, set the variables `PFT_BACKUP_PGHOST` / `PGPORT` / `PGUSER` / `PGDATABASE` and the secret `PFT_BACKUP_PGPASSWORD`.
3. **CA certificate.** Put the Supabase public root CA in `config/supabase-ca.crt`. The certificate used in M5 has SHA-256 fingerprint `807025AD50D4ED219D2C9C7D299C004F824EB00CF7F65AFEF607D07B72E6CAFA` (`openssl x509 -noout -fingerprint -sha256 -in config/supabase-ca.crt`).
4. **Stage, review, commit, push** (`stage_backup_repo.py`, then `git diff`). Then trigger **Run workflow** manually once. Check that the release is published, then restore it on another machine with `RESTORE.md`.
5. Only after a successful restore, leave the daily schedule enabled.

Point the variables at Production only in the cutover stage (cutover draft, prerequisite C6). Until then everything targets the synthetic project.

Not yet verified: whether Actions is enabled for this private repository by default, and that `permissions: contents: write` takes effect. GitHub documents that only organization or enterprise policy can restrict it, and this is a personal repository. Both are checked on the first manual run.

## Configuration (backup repository settings)

- **Variables:** `PFT_BACKUP_PGHOST`, `PFT_BACKUP_PGPORT`, `PFT_BACKUP_PGUSER`, `PFT_BACKUP_PGDATABASE`.
- **Secret:** `PFT_BACKUP_PGPASSWORD`, for the read-only `pft_backup` role.
- **No other secret.** The workflow uses its own `GITHUB_TOKEN` with `contents: write` on the backup repository only.
- **Pinned:** age v1.3.2 (release-page SHA-256 checked before use), `actions/checkout` by commit SHA, the PostgreSQL 17.11 client image by digest.

## Local drill

```sh
PFT_AGE_BIN=/path/to/verified/age PFT_PG_BIN_DIR=/usr/lib/postgresql/16/bin \
PGHOST=127.0.0.1 PGPORT=55439 PGUSER=... PGDATABASE=... \
python3 deploy/backup_runner/pft_backup_runner.py --store local:/path/to/store \
  --recipients recipients.txt --expected-database "$PGDATABASE" --work-dir /path/to/tmp
```

Plaintext connections are accepted only for loopback clusters on ports ≥ 55000. Every other host needs `PGSSLMODE=verify-full` and `PGSSLROOTCERT`.
