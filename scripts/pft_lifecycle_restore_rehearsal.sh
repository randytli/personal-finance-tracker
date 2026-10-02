#!/usr/bin/env bash
# Lifecycle restore rehearsal (D15) and timing (D12), one approved step at a time.
#
# Usage: scripts/pft_lifecycle_restore_rehearsal.sh STEP
# Required environment:
#   PFT_REHEARSAL_DIR      private working directory (mode 0700) for the disposable cluster
#   PFT_BACKUP_SOURCE_DIR  backup directory, read only (R1, R2, S3)
#   PFT_REHEARSAL_BACKUP   absolute path of the chosen .dump inside PFT_BACKUP_SOURCE_DIR
#   PFT_REHEARSAL_OLD_COMMIT  application_commit from that backup's manifest (S4)
# The cluster listens on a Unix socket only, uses peer authentication, never TCP.
# Nothing here connects to Production, runs docker, or constructs a Plaid client.
set -euo pipefail
umask 077  # Result files are private from creation, not only after S9.

STEP=${1:?step}
WORKTREE=$(cd "$(dirname "$0")/.." && pwd)
PG=${PFT_PG_BIN_DIR:-/usr/lib/postgresql/16/bin}
PY=${PFT_PYTHON:-/home/randyli/code/personal-finance-tracker/.venv/bin/python}
DIR=${PFT_REHEARSAL_DIR:?set PFT_REHEARSAL_DIR}
PORT=55441
DB=pft_restore_lifecycle_20261002
SOCK="$DIR/sock"
OUT="$DIR/results"
export DATABASE_URL="postgresql+asyncpg://$(id -un)@:$PORT/$DB?host=$SOCK"
unset PLAID_ENV EXPECTED_DATABASE_NAME PLAID_CLIENT_ID PLAID_SECRET PLAID_TOKEN_ENCRYPTION_KEY

private() { [ -d "$1" ] && [ "$(stat -c %a "$1")" = 700 ] || { echo "refusing: $1 must exist with mode 0700" >&2; exit 1; }; }
psql_copy() { "$PG/psql" -h "$SOCK" -p "$PORT" -X -v ON_ERROR_STOP=1 "$@"; }
rehearse() { (cd "$OUT" && PYTHONPATH="$1" "$PY" "$WORKTREE/scripts/pft_lifecycle_restore_rehearsal.py" "${@:2}"); }
backup_file() {
  local source; source=$(realpath "${PFT_BACKUP_SOURCE_DIR:?}")
  [ "$(dirname "$(realpath "${PFT_REHEARSAL_BACKUP:?}")")" = "$source" ] || { echo "refusing: backup outside source dir" >&2; exit 1; }
  echo "$PFT_REHEARSAL_BACKUP"
}

case "$STEP" in
  S0)  # [STATE: local only] create exactly the configured private directory
    "$PY" - "$DIR" <<'EOF'
import os, stat, sys
from pathlib import Path
directory = Path(sys.argv[1])
if not directory.is_absolute() or directory == Path('/') or directory.resolve() != directory:
    raise SystemExit('refusing: rehearsal path must be absolute, canonical and not symlinked')
if not directory.parent.is_dir():
    raise SystemExit('refusing: rehearsal parent must already exist as a directory')
if directory.exists() and (not directory.is_dir() or directory.stat().st_uid != os.getuid()):
    raise SystemExit('refusing: rehearsal directory must be owned by the current user')
if not directory.exists():
    directory.mkdir(mode=0o700)  # parents=False: never create an ancestor.
directory.chmod(0o700)
info = directory.stat()
if directory.resolve() != directory or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise SystemExit('refusing: rehearsal directory identity, ownership or permissions differ')
print(f'private rehearsal directory ready: {directory} (mode 0700)')
EOF
    ;;
  R1)  # [READ] newest manifests: names, sizes, times only
    "$PY" - "${PFT_BACKUP_SOURCE_DIR:?}" <<'EOF'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
source = Path(sys.argv[1]).resolve(strict=True)
if not source.is_dir():
    raise SystemExit('refusing: backup source must be a directory')
candidates = []
for manifest in source.glob('*.json'):
    if manifest.is_symlink() or not manifest.is_file():
        raise SystemExit('refusing: manifest candidates must be regular, non-symlink files')
    info = manifest.stat()
    candidates.append((info.st_mtime_ns, manifest.name, info.st_size))
for timestamp, filename, size in sorted(candidates, key=lambda row: (-row[0], row[1]))[:12]:
    print(json.dumps({'filename': filename, 'size': size,
                      'modified_at': datetime.fromtimestamp(timestamp / 1e9, timezone.utc).isoformat()}))
EOF
    ;;
  R2)  # [READ] manifest fields, checksum and archive listing of the chosen backup
    "$PY" - "${PFT_BACKUP_SOURCE_DIR:?}" "${PFT_REHEARSAL_BACKUP:?}" "$PG/pg_restore" "$WORKTREE" <<'EOF'
import hashlib, json, re, subprocess, sys
from datetime import datetime, timedelta
from pathlib import Path

def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate manifest field')
        result[key] = value
    return result

try:
    source = Path(sys.argv[1]).resolve(strict=True)
    archive = Path(sys.argv[2])
    if (not source.is_dir() or not archive.is_absolute() or archive.suffix != '.dump'
            or archive.is_symlink() or archive.resolve(strict=True) != archive
            or archive.parent != source
            or not archive.is_file()):
        raise ValueError('selected dump must be a regular .dump inside the backup source')
    manifest = archive.with_suffix('.json')
    if manifest.is_symlink() or not manifest.is_file() or manifest.resolve(strict=True).parent != source:
        raise ValueError('matching same-stem manifest is missing or outside the backup source')
    metadata = json.loads(manifest.read_text(), object_pairs_hook=unique_fields)
    fields = ('created_at', 'kind', 'sha256', 'schema_sha256', 'application_commit', 'format')
    if not isinstance(metadata, dict) or any(not isinstance(metadata.get(key), str)
                                            or not metadata[key] for key in fields):
        raise ValueError('required manifest fields are missing or malformed')
    try:
        created_at = datetime.fromisoformat(metadata['created_at'])
    except ValueError:
        raise ValueError('manifest created_at is malformed') from None
    if created_at.isoformat() != metadata['created_at'] or created_at.utcoffset() != timedelta(0):
        raise ValueError('manifest created_at must be a UTC isoformat timestamp')
    if metadata['kind'] not in ('daily', 'weekly', 'monthly', 'extra'):
        raise ValueError('manifest kind is malformed')
    # One exact overlay label has a recorded 34/34 source comparison in the
    # sync-diff-writes release packet. Never infer a revision from arbitrary labels.
    revision = metadata['application_commit']
    verified_label = 'sdw-p2-b646fb9-derivation-over-1d17e2b59fa4be74af41f60125f41084698049424e0b4d77376db1fe41cc74c7'
    if revision == verified_label:
        revision = '6ac9612f97479ed96eb69be55864437652f33a00'
        base = 'a047b0f4b32c2db23203fbab9b25cd5fe7678400'
        overlay = 'b646fb9e9d52e795f177cf9c4d2f202f5d71f99a'
        changed = subprocess.run(['git', '-C', sys.argv[4], 'diff', '--name-only', base, revision,
                                  '--', 'api', 'statement_imports'], capture_output=True, text=True, check=True)
        blobs = [subprocess.run(['git', '-C', sys.argv[4], 'rev-parse', '--verify',
                                 commit + ':api/services/derivation.py'],
                                capture_output=True, text=True, check=True).stdout.strip()
                 for commit in (overlay, revision)]
        if changed.stdout.splitlines() != ['api/services/derivation.py'] or blobs[0] != blobs[1]:
            raise ValueError('recorded overlay provenance differs from local Git history')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('manifest application_commit must be a full Git commit hash or the exact verified release label')
    commit = subprocess.run(['git', '-C', sys.argv[4], 'rev-parse', '--verify',
                             revision + '^{commit}'],
                            capture_output=True, text=True)
    if commit.returncode != 0 or commit.stdout.strip() != revision:
        raise ValueError('manifest application_commit must identify an existing commit in this repo')
    if (metadata['format'] != 'pg_dump-custom'
            or any(not re.fullmatch(r'[0-9a-f]{64}', metadata[key]) for key in ('sha256', 'schema_sha256'))):
        raise ValueError('manifest format or hashes are malformed')
    if 'size' in metadata and (type(metadata['size']) is not int or metadata['size'] < 0):
        raise ValueError('manifest size is malformed')
    actual_size = archive.stat().st_size
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != metadata['sha256']:
        raise ValueError('backup checksum mismatch')
    if 'size' in metadata and actual_size != metadata['size']:
        raise ValueError('backup size mismatch')
    listing = subprocess.run([sys.argv[3], '-l', str(archive)], capture_output=True, check=True, text=True)
    report = {key: metadata[key] for key in fields}
    report.update(resolved_application_commit=revision, size=metadata.get('size'), actual_size=actual_size, actual_sha256=actual_sha256,
                  table_data_count=sum(' TABLE DATA ' in line for line in listing.stdout.splitlines()))
    print(json.dumps(report, indent=1))
except (OSError, ValueError, subprocess.SubprocessError) as error:
    # Never print archive listing, manifest contents or pg_restore stderr on failure.
    message = str(error) if type(error) is ValueError else 'manifest/dump unreadable, malformed or archive inspection failed'
    raise SystemExit(f'refusing: {message}')
EOF
    ;;
  S1)  # [STATE: local disposable] create the socket-only cluster
    private "$DIR"; [ ! -e "$DIR/data" ] || { echo "refusing: $DIR/data exists" >&2; exit 1; }
    install -d -m 0700 "$SOCK" "$OUT"
    "$PG/initdb" -D "$DIR/data" -U "$(id -un)" --auth-local=peer --auth-host=reject -E UTF8 >/dev/null
    echo "initialized $DIR/data" ;;
  S2)  # [STATE: local disposable] start it without any TCP listener
    "$PG/pg_ctl" -D "$DIR/data" -l "$DIR/pg.log" -w start \
      -o "-c listen_addresses='' -c unix_socket_directories='$SOCK' -p $PORT" ;;
  R3)  # [READ] prove the cluster is the disposable, socket-only one
    psql_copy -d postgres -Atc "select current_setting('listen_addresses') = '', current_setting('data_directory'), version()" ;;
  S3)  # [STATE: local disposable] restore the backup into a new database (reads the backup only)
    file=$(backup_file)
    "$PG/createdb" -h "$SOCK" -p "$PORT" "$DB"
    "$PG/pg_restore" -h "$SOCK" -p "$PORT" --exit-on-error --no-owner --no-privileges -d "$DB" "$file"
    psql_copy -d "$DB" -Atc "select status, count(*) from items group by 1 order by 1" ;;
  S4)  # [STATE: local disposable] extract the code that wrote the backup
    install -d -m 0700 "$DIR/old_src"
    git -C "$WORKTREE" archive "${PFT_REHEARSAL_OLD_COMMIT:?}" api statement_imports | tar -x -C "$DIR/old_src"
    echo "old code: $(git -C "$WORKTREE" rev-parse --short "$PFT_REHEARSAL_OLD_COMMIT")" ;;
  R4)  # [READ on copy] old-code fingerprint, read-only transaction
    rehearse "$DIR/old_src" fingerprint > "$OUT/before.json"; cat "$OUT/before.json" ;;
  S5)  # [STATE on copy] old-code reclassification, then fingerprint
    rehearse "$DIR/old_src" fingerprint --reclassify > "$OUT/before_reclassified.json"; cat "$OUT/before_reclassified.json" ;;
  R5)  # [READ on copy] strict Production preflight, new code
    (cd "$OUT" && PYTHONPATH="$WORKTREE" "$PY" -m api.lifecycle_preflight) | tee "$OUT/preflight.json" ;;
  S6)  # [STATE on copy] migrate with the strict gate; exit 2 means stop and report
    rehearse "$WORKTREE" migrate | tee "$OUT/migrate.json" ;;
  S6b) # [STATE on copy, separate approval] only if S6 stopped: migrate this copy with the
       # non-Production gate so D15/D12 can still run. It does not change the Production verdict.
    rehearse "$WORKTREE" migrate --copy-only-gate | tee "$OUT/migrate_copy_only.json" ;;
  R6)  # [READ on copy] new-code fingerprint after migration
    rehearse "$WORKTREE" fingerprint > "$OUT/after.json"; cat "$OUT/after.json" ;;
  S7)  # [STATE on copy] new-code reclassification, then fingerprint
    rehearse "$WORKTREE" fingerprint --reclassify > "$OUT/after_reclassified.json"; cat "$OUT/after_reclassified.json" ;;
  R7)  # [READ] compare every digest; timings are ignored
    "$PY" - "$OUT" <<'EOF' | tee "$OUT/compare.json"
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
keys = ("status_counts", "items_digest", "table_digests", "classification_digest",
        "analytics_rows", "analytics_months", "analytics_digest")
runs = {name: json.loads((out / f"{name}.json").read_text())
        for name in ("before", "before_reclassified", "after", "after_reclassified")}
base = {key: runs["before"][key] for key in keys}
result = {name: {key: run[key] == base[key] for key in keys} for name, run in runs.items()}
result["all_identical"] = all(all(values.values()) for values in result.values())
print(json.dumps(result, indent=1))
EOF
    ;;
  S8)  # [STATE on copy] lifecycle timings; changes only the disposable copy
    rehearse "$WORKTREE" timing | tee "$OUT/timing.json" ;;
  S9)  # [STATE: local disposable] stop and delete the cluster and code copy; keep results only
    "$PG/pg_ctl" -D "$DIR/data" -m fast -w stop || true
    rm -rf -- "$DIR/data" "$DIR/sock" "$DIR/old_src" "$DIR/pg.log"
    chmod 0600 "$OUT"/*.json
    ls -l "$DIR" "$OUT" ;;
  *) echo "unknown step $STEP" >&2; exit 2 ;;
esac
