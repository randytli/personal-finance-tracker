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
  R1)  # [READ] newest manifests: names, sizes, times only
    ls -l --time-style=+%FT%T "${PFT_BACKUP_SOURCE_DIR:?}"/*.json | tail -n 12 ;;
  R2)  # [READ] manifest fields, checksum and archive listing of the chosen backup
    file=$(backup_file)
    "$PY" -c 'import json,sys; m=json.load(open(sys.argv[1])); print(json.dumps({k: m[k] for k in ("created_at","kind","size","sha256","schema_sha256","application_commit","format")}, indent=1))' "${file%.dump}.json"
    sha256sum "$file" | cut -c1-64
    "$PG/pg_restore" -l "$file" | grep -c ' TABLE DATA ' ;;
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
