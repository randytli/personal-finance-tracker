#!/usr/bin/env bash
# Design preview launcher: synthetic mock API (127.0.0.1:3107) + basePath Next.js server (127.0.0.1:3106).
# Usage: preview/run.sh build|start|stop|status
# Never touches Docker, Tailscale, Production ports (3000/8000) or Production env files.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="$ROOT/preview/.run"
WEB_PORT=3106
MOCK_PORT=3107
export PFT_PREVIEW_BASE_PATH=/design-preview
export PFT_API_URL="http://127.0.0.1:$MOCK_PORT"
export PFT_PREVIEW_MOCK_PORT=$MOCK_PORT
export NEXT_TELEMETRY_DISABLED=1
cd "$ROOT"

preflight() {
  # Next.js loads these automatically; the preview must run with no Production secrets present.
  for file in .env .env.local .env.production .env.production.local .env.development .env.development.local; do
    [[ ! -e "$file" ]] || { echo "Refusing to run: $file exists in this worktree" >&2; exit 1; }
  done
}

port_free() { ! ss -ltn "sport = :$1" | grep -q LISTEN; }

build() {
  preflight
  # next build rewrites next-env.d.ts to reference its distDir; keep the shared file unchanged.
  cp next-env.d.ts "$ROOT/preview/.next-env.d.ts.keep"
  trap 'mv "$ROOT/preview/.next-env.d.ts.keep" next-env.d.ts' RETURN
  node node_modules/next/dist/bin/next build
  # Rewrites are baked into the build; every API destination must be the loopback mock.
  node -e '
    const m = require("./.next-design-preview/routes-manifest.json")
    const rewrites = [].concat(m.rewrites.beforeFiles || [], m.rewrites.afterFiles || [], m.rewrites.fallback || [], Array.isArray(m.rewrites) ? m.rewrites : [])
    const bad = rewrites.filter(r => !r.destination.startsWith(process.env.PFT_API_URL + "/"))
    if (m.basePath !== "/design-preview" || !rewrites.length || bad.length) { console.error("Unsafe preview build", m.basePath, bad); process.exit(1) }
    console.log(`Preview build OK: basePath ${m.basePath}, ${rewrites.length} rewrites -> ${process.env.PFT_API_URL}`)'
}

start() {
  preflight
  [[ -f .next-design-preview/BUILD_ID ]] || { echo "Run preview/run.sh build first" >&2; exit 1; }
  port_free $MOCK_PORT && port_free $WEB_PORT || { echo "Port $MOCK_PORT or $WEB_PORT is busy" >&2; exit 1; }
  mkdir -p "$RUN_DIR"
  nohup node preview/mock-api.cjs >"$RUN_DIR/mock.log" 2>&1 &
  echo $! >"$RUN_DIR/mock.pid"
  nohup node node_modules/next/dist/bin/next start -H 127.0.0.1 -p $WEB_PORT >"$RUN_DIR/web.log" 2>&1 &
  echo $! >"$RUN_DIR/web.pid"
  for _ in $(seq 1 50); do
    curl -fsS -o /dev/null "http://127.0.0.1:$WEB_PORT/design-preview/review" 2>/dev/null && break; sleep 0.2
  done
  status
}

stop() {
  for name in web mock; do
    pid_file="$RUN_DIR/$name.pid"
    [[ -f "$pid_file" ]] || continue
    pid="$(cat "$pid_file")"
    # Only stop a process that still belongs to this worktree.
    if [[ -d "/proc/$pid" && "$(readlink "/proc/$pid/cwd")" == "$ROOT" ]]; then kill "$pid"; echo "Stopped $name ($pid)"; fi
    rm -f "$pid_file"
  done
}

status() {
  for name in mock web; do
    pid_file="$RUN_DIR/$name.pid"
    if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then echo "$name: running (pid $(cat "$pid_file"))"; else echo "$name: stopped"; fi
  done
  ss -ltn "( sport = :$MOCK_PORT or sport = :$WEB_PORT )" | tail -n +2
  echo "Preview: http://127.0.0.1:$WEB_PORT/design-preview/"
}

case "${1:-}" in
  build) build ;;
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "Usage: $0 build|start|stop|status" >&2; exit 2 ;;
esac
