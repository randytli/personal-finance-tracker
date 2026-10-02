# PFT backup runner (GitHub Actions + age)

Source of truth for the independent cloud backup (owner decisions P1-1, P1-2 and P1-4, 2026-10-02). Design: [docs/PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md](../../docs/PFT_M5_INDEPENDENT_BACKUP_DESIGN_2026-10-02.md). Recovery without any PFT code: [docs/PFT_BACKUP_RESTORE_RUNBOOK.md](../../docs/PFT_BACKUP_RESTORE_RUNBOOK.md).

**Nothing here is deployed.** Creating the backup repository, roles, keys and secrets needs the owner's separate approval.

| File | Purpose |
| --- | --- |
| `pft_backup_runner.py` | One backup run. Standard library only. |
| `release_store.py` | GitHub release store (draft → upload → readback → publish) and the local store. Standard library only. |
| `snapshot_dump.sql` | psql script: identity check, exported snapshot, `pg_dump --snapshot`, fingerprint of the same snapshot. |
| `fingerprint.sql` | Deterministic fingerprint; also used by restores, standalone. |
| `pft-backup.yml` | Workflow template. Not active in this repository. |
| `SHA256SUMS` | Hashes of the four runner files as `runner/<file>`. Checked by the workflow; `tests/test_m5_backup_age.py` fails if it is stale. |

## Layout of the dedicated private backup repository

```
.github/workflows/pft-backup.yml   ← copy of pft-backup.yml
runner/                            ← the four runner files + SHA256SUMS, copied from a reviewed PFT commit
config/recipients.txt              ← two age X25519 public keys: daily, emergency (public, not secret)
config/supabase-ca.crt             ← Supabase public root CA (verify-full)
RESTORE.md                         ← copy of docs/PFT_BACKUP_RESTORE_RUNBOOK.md
```

Record the PFT commit the runner was copied from in the backup repo's commit message. Update only by copying the files again together with `SHA256SUMS`.

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
