# PFT backup restore runbook: no PFT code needed

Scenario: years from now, on a brand-new machine, you have none of the PFT repository, the old PC, Supabase or Vercel. You have only a backup point and one of the two private keys. This page is enough.

It needs **only** `age`, the PostgreSQL client tools (`pg_restore`, `createdb`, `psql`), a PostgreSQL server to restore into, and `sha256sum`. Each step was exercised end to end by `tests/test_m5_backup_age.py::test_runbook_commands_without_pft_code`, on synthetic data, with the commands below.

Keep a copy of this page next to each private key, and as `RESTORE.md` in the backup repository.

## 0. What you need

| Item | Where it is |
| --- | --- |
| A backup point: `backup.dump.age`, `manifest.json.age`, `fingerprint.txt.age` | Backup repository → **Releases** → newest release named `pft-backup-YYYYMMDDTHHMMSSZ-…` (never a *Draft*), or the owner's secondary copy (Google Drive / offline media) |
| **One** private key file (daily *or* emergency) and its passphrase | The two separate offline locations (backup design §5). Either key alone decrypts every point |
| `fingerprint.sql` | Backup repository `runner/fingerprint.sql`, or the copy stored with the keys |
| `age` | Any implementation of the age v1 format: the [official age](https://github.com/FiloSottile/age) (backups were made with v1.3.2) or [rage](https://github.com/str4d/rage) |
| PostgreSQL | Major version **≥** `server_version` in the manifest (17 at the time of writing). Older `pg_restore` versions cannot read newer archives |

## 1. Install the tools

- **age:** download the release archive for your platform from the official releases page. Compare its SHA-256 with the digest shown on that page (`sha256sum <file>`), then unpack it. If the page is gone, use the age archive stored with the keys, or any maintained age-v1 implementation.
- **PostgreSQL:** install the server and client packages from postgresql.org (or your OS) with a major version ≥ the manifest's.

## 2. Get the backup point

- **Web:** open the backup repository's **Releases**, pick the newest non-draft `pft-backup-…` release, and download its three `.age` assets into an empty private directory.
- **CLI alternative:** `gh release download <tag> -R <owner>/<backup-repo> -D restore-work`.

```sh
mkdir -m 700 restore-work && cd restore-work      # all plaintext stays in here
```

## 3. Decrypt

```sh
age -d -i /path/to/daily.key.age -o backup.dump     backup.dump.age
age -d -i /path/to/daily.key.age -o manifest.json   manifest.json.age
age -d -i /path/to/daily.key.age -o fingerprint.txt fingerprint.txt.age
```

- age asks for the key file's passphrase.
- If the daily key is lost, use the emergency key file instead. Nothing else changes.
- age authenticates the data. Any error means a wrong key or a damaged file. Stop and try an older point; never use partial output.
- `no identity matched any of the recipients` means this key was not a recipient of this point. Try the other key.

## 4. Check the manifest

Open `manifest.json`. It is plain JSON. Note `created_at`, `server_version` and `schemas`, then:

```sh
sha256sum backup.dump fingerprint.txt
```

The two hashes must equal `archive.sha256` and `fingerprint.sha256` in the manifest. If not, stop.

## 5. Start an empty PostgreSQL server (local only)

Use any empty server that you control and that listens only on localhost. For example:

```sh
initdb -D ./pgdata -U postgres --auth=trust
pg_ctl -D ./pgdata -o "-c listen_addresses=localhost -p 55432" -l pg.log start
export PGHOST=localhost PGPORT=55432 PGUSER=postgres
```

Never restore into a database that already holds data.

## 6. Restore

```sh
pg_restore -l backup.dump > toc.txt
# A new database already has schema "public": drop only its CREATE and COMMENT lines.
grep -v -e ' SCHEMA - public ' -e ' COMMENT - SCHEMA public ' toc.txt > restore.list
createdb pft_restore
pg_restore --exit-on-error --no-owner --no-privileges -L restore.list -d pft_restore backup.dump
```

- `unsupported version … in file header` means your `pg_restore` is too old. Install a newer major.
- Ownership and grants are not restored by design. The data, schema, constraints, indexes and sequences are.

## 7. Verify with the fingerprint

```sh
psql -X -q -v ON_ERROR_STOP=1 -v schemas='{public}' -d pft_restore -f fingerprint.sql > restored.txt
diff fingerprint.txt restored.txt && echo IDENTICAL
```

- Use the `schemas` list from the manifest, e.g. `'{public,pft_ops}'`.
- **No output from `diff` means the restore equals the backup snapshot**: every table's row count and full-row hash, sequences, constraints, indexes and columns.
- The fingerprint was taken inside the same database snapshot that `pg_dump` exported.
- On a much newer PostgreSQL major, only `column|`/`constraint|`/`index|` lines might differ in how definitions are printed. The data check is then:

  ```sh
  diff <(grep '^table|' fingerprint.txt) <(grep '^table|' restored.txt) && echo DATA-IDENTICAL
  ```

  Must print `DATA-IDENTICAL`.

## 8. Use the data safely

- `pft_restore` is now an ordinary PostgreSQL database: transactions, overrides, statement evidence, Items and accounts. Query it with `psql` or export it with `\copy`.
- `items.access_token` values are **Fernet-encrypted Plaid tokens**. They are useless without the separately held `PLAID_TOKEN_ENCRYPTION_KEY` and a live Plaid relationship. Do not try to call Plaid from a restore. Re-linking institutions is a separate decision.
- **Never connect an old PFT scheduler or app to this database while another copy is still the active one.** Promoting a restore to the live database is a separate, reviewed procedure (cutover packet). It is not part of this runbook.

## 9. Clean up

The decrypted files contain financial data. When finished:
- delete `backup.dump`, `manifest.json`, `fingerprint.txt`, `toc.txt`, `restore.list` and `restored.txt`;
- delete the scratch server (`pg_ctl -D ./pgdata stop`, then remove `pgdata`) unless you are keeping the restore.

## Older Windows-era formats (transition period)

Until cloud backups take over (plan stage M8c), the Windows runtime keeps making its own backups, unchanged:

| Format | Recognise it by | Restore without PFT code? |
| --- | --- | --- |
| Plain dump + manifest: `pft-daily-<UTC>.dump` with `pft-daily-<UTC>.json` | File starts with `PGDMP` | **Yes.** Check `sha256sum` against the `.json` `sha256`, then steps 5–6. There is no embedded fingerprint. |
| External encrypted copy (`PFTENC2`) from `api/backup_crypto.py` | File starts with the bytes `PFTENC2` | **No.** It needs the PFT repository's `api/backup_crypto.py` and its password. Use `scripts/pft_backup_restore.py <file> --target-url …` from a PFT checkout. |

`scripts/pft_backup_restore.py` restores **all three** formats (age points, PFTENC2, plain local dumps) into a new local `pft_restore_*` database and runs this fingerprint. For the Windows formats it compares against a source fingerprint passed with `--expected-fingerprint`.
