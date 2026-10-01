"""Create fresh separate deployment candidates; no provider calls or DB access.

Does not modify the M5 benchmark, prior bundles or evidence. Reader/jobs include
only their AST import closures; original application source is copied unchanged.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path

from scripts.pft_m5_prepare_cloud_bundle import ROOT, check_entrypoints

SHARED = ("api.models", "api.statement_semantics", "api.services.derivation",
          "statement_imports", "statement_imports.persistence")
ROLE_ROOTS = {"reader": ("api.routes.analytics", "api.routes.review"),
              "jobs": ("api.services.sync_all", "api.jobs", "api.backup", "api.backup_crypto")}
FORBIDDEN = {"api/main.py", "api/migrate_once.py", "api/sync_once.py", "statement_imports/__main__.py"}


def module_path(module):
    if not (module == "api" or module.startswith("api.") or module == "statement_imports"
            or module.startswith("statement_imports.")):
        return None
    stem = ROOT.joinpath(*module.split("."))
    for path in (stem.with_suffix(".py"), stem / "__init__.py"):
        if path.is_file():
            if path.is_symlink() or path.relative_to(ROOT).as_posix() in FORBIDDEN:
                raise RuntimeError("Forbidden source in import closure")
            return path
    return None


def closure(role):
    queue = list(SHARED + ROLE_ROOTS[role])
    visited, paths = set(), set()
    while queue:
        module = queue.pop()
        if module in visited:
            continue
        visited.add(module)
        path = module_path(module)
        if path is None:
            continue
        paths.add(path)
        parts = module.split(".")
        for length in range(1, len(parts)):
            queue.append(".".join(parts[:length]))
        package = parts if path.name == "__init__.py" else parts[:-1]
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                queue.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    prefix = package[:len(package)-node.level+1]
                    base = ".".join(prefix + ([base] if base else []))
                queue.append(base)
                queue.extend(base + "." + alias.name for alias in node.names)
    if role == "reader" and any(path.relative_to(ROOT).as_posix() in
            {"api/jobs.py", "api/services/sync_all.py", "api/backup.py", "api/backup_crypto.py", "api/routes/plaid.py"}
            for path in paths):
        raise RuntimeError("Reader now depends on a jobs/Plaid module; review separation")
    return sorted(paths)


def write(directory, relative, data):
    path = directory / relative
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    os.chmod(path, 0o600)


def stage_packet(destination):
    if destination.exists() or not destination.resolve().is_relative_to(Path("/tmp")):
        raise RuntimeError("Requires fresh private /tmp destination")
    destination.mkdir(mode=0o700, parents=True)
    summaries = {}
    for role in ("reader", "jobs"):
        directory = destination / role
        source = (ROOT / "experiments/m5_cloud/runtime_probe.py").read_text()
        # Keep the shared source unchanged. Add an immutable bundle-role check
        # after the original capability check and before every handler.
        suffix = f'''

# Generated disposable bundle role boundary.
async def _bundle_capability(request: Request):
    config = await capability(request)
    if config.role != {role!r}:
        raise HTTPException(503, "Bundle role rejected")
    return config

app.dependency_overrides[capability] = _bundle_capability
from pool_probe_support import register as _register_pool
_register_pool(app, _bundle_capability, identity, new_engine)
'''
        sources = {"main.py": source + suffix,
            "pool_probe_support.py": (ROOT / "experiments/m5_cloud/pool_probe_support.py").read_text()}
        if role == "jobs":
            sources["sync_benchmark_support.py"] = (ROOT / "experiments/m5_cloud/sync_benchmark_support.py").read_text()
            sources["main.py"] += ("\nfrom sync_benchmark_support import register as _register_benchmark\n"
                "_register_benchmark(app, _bundle_capability, identity, tls_context, APP_INSTANCE)\n")
        for path in closure(role):
            sources[path.relative_to(ROOT).as_posix()] = path.read_text()
        check_entrypoints(list(sources), sources)
        for relative, data in sources.items():
            write(directory, relative, data)
        write(directory, "requirements.txt", (ROOT / "api/requirements.txt").read_bytes())
        write(directory, ".python-version", "3.12\n")
        write(directory, "vercel.json", json.dumps({"framework": "fastapi", "functions": {
            "main.py": {"maxDuration": 300}}, "headers": [{"source": "/(.*)", "headers": [
                {"key": "Cache-Control", "value": "private, no-store"}]}]}, indent=2)+"\n")
        manifest = [{"path": path.relative_to(directory).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(directory.rglob("*")) if path.is_file()]
        result = {"kind": "source_candidate_not_vercel_build", "role": role,
                  "files": manifest, "source_bytes": sum(row["bytes"] for row in manifest)}
        write(directory, "source-manifest.json", json.dumps(result, indent=2)+"\n")
        summaries[role] = {"files": len(manifest), "source_bytes": result["source_bytes"]}
        # Templates stay outside upload trees. Replace only with the newly
        # created project's ref and fresh experiment secrets through provider API.
        write(destination, f"{role}.env.template", "\n".join([
            "PLAID_ENV=sandbox", f"M5_PROBE_ROLE={role}",
            f"M5_VERCEL_PROJECT_NAME=pft-m5-{role}-20261001",
            "M5_SUPABASE_PROJECT_REF=<NEW_SYNTHETIC_PROJECT_REF>",
            f"DATABASE_URL=postgresql+asyncpg://pft_m5_{role}.<NEW_SYNTHETIC_PROJECT_REF>:<URL_ENCODED_NEW_PASSWORD>@<SESSION_HOST_FROM_CONNECT_DIALOG>:5432/postgres",
            "M5_DATASET_ID=m5-<32_HEX_SYNTHETIC_DATASET_ID>",
            "M5_DEPLOYMENT_ID=m5-<32_HEX_SHARED_EXPERIMENT_ID>",
            "M5_PROBE_TOKEN=<FRESH_ROLE_SPECIFIC_TOKEN_AT_LEAST_32_CHARACTERS>", ""]))
    web = destination / "web-probe"
    write(web, "app/api/probe/route.js", "import { handleProbe } from '../../probe-handler.mjs';\n"
          "export const runtime = 'nodejs';\nexport const dynamic = 'force-dynamic';\n"
          "export async function GET(request) { return handleProbe(request); }\n")
    write(web, "app/probe-handler.mjs", (ROOT / "experiments/m5_cloud/web_probe_handler.mjs").read_bytes())
    # Existing repo lock and npm runner. No install or root build here.
    write(web, "package.json", (ROOT / "package.json").read_bytes())
    write(web, "package-lock.json", (ROOT / "package-lock.json").read_bytes())
    write(web, "vercel.json", json.dumps({"framework": "nextjs", "functions": {
        "app/api/probe/route.js": {"maxDuration": 90}}}, indent=2)+"\n")
    write(destination, "web-probe.env.template", "\n".join([
        "M5_VERCEL_PROJECT_NAME=pft-m5-web-probe-20261001",
        "M5_WEB_PROBE_TOKEN=<FRESH_WEB_SERVICE_TOKEN_AT_LEAST_32_CHARACTERS>",
        "M5_READER_HOST=<EXACT_NEW_READER_DEPLOYMENT_HOST>",
        "M5_READER_URL=https://<EXACT_NEW_READER_DEPLOYMENT_HOST>/",
        "M5_READER_PROBE_TOKEN=<FRESH_READER_SERVICE_TOKEN>",
        "M5_READER_PROTECTION_BYPASS=<VERCEL_SERVER_ONLY_AUTOMATION_SECRET>", ""]))
    summaries["web-probe"] = {"files": sum(path.is_file() for path in web.rglob("*"))}
    write(destination, "synthetic-identity.sql.template",
          (ROOT / "experiments/m5_cloud/synthetic-identity.sql.template").read_bytes())
    write(destination, "packet-summary.json", json.dumps({"kind": "local_preparation_only",
        "bundles": summaries, "environment_templates_uploaded": False}, indent=2)+"\n")
    return summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage_packet(args.destination), indent=2))
