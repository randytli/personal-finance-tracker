"""Stage allowlisted source in a fresh private /tmp directory; no cloud calls.

This is a packaging candidate, not a deploy artifact or a full M5 implementation.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
# Vercel's documented Python entrypoint locations and handler names (checked 2026-10-01).
ENTRYPOINT_NAMES = {"app.py", "index.py", "server.py", "main.py", "wsgi.py", "asgi.py"}
HANDLER_NAMES = {"app", "application", "handler"}


def handler_names(source):
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(target.id for target in targets if isinstance(target, ast.Name))
    return names & HANDLER_NAMES


def check_entrypoints(relative_paths, sources):
    """The FastAPI preset must resolve only main.py. If preset detection ever falls
    back to file-based /api functions, no other module may be servable."""
    candidates = sorted(path for path in relative_paths if Path(path).name in ENTRYPOINT_NAMES
                        and Path(path).parent.as_posix() in {".", "src", "app"})
    if candidates != ["main.py"]:
        raise RuntimeError(f"Ambiguous Vercel entrypoints: {candidates}")
    servable = sorted(path for path in relative_paths if path != "main.py"
                      and handler_names(sources[path]))
    if servable:
        raise RuntimeError(f"Bundled modules define Vercel handler names: {servable}")


def stage(destination):
    if destination.exists() or not destination.resolve().is_relative_to(Path("/tmp")):
        raise RuntimeError("Requires a fresh destination under /tmp")
    files = [ROOT / "experiments/m5_cloud/runtime_probe.py"]
    # Only Python source in these exact directories; never copy runtime env/data.
    for relative in ("api", "api/routes", "api/services", "statement_imports"):
        files.extend(sorted((ROOT / relative).glob("*.py")))
    files = [path for path in files if path.relative_to(ROOT).as_posix() not in
             {"api/main.py", "api/migrate_once.py", "api/sync_once.py"}]
    if any(path.is_symlink() for path in files):
        raise RuntimeError("Symlink source rejected")
    def bundled(source):
        relative = source.relative_to(ROOT)
        return Path("main.py") if relative.as_posix() == "experiments/m5_cloud/runtime_probe.py" else relative
    check_entrypoints([bundled(path).as_posix() for path in files],
                      {bundled(path).as_posix(): path.read_text() for path in files})
    destination.mkdir(mode=0o700, parents=True)
    manifest = []
    for source in files:
        relative = bundled(source)
        target = destination / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        manifest.append({"path": relative.as_posix(), "bytes": target.stat().st_size,
                         "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    requirements = (ROOT / "api/requirements.txt").read_bytes()
    (destination / "requirements.txt").write_bytes(requirements)
    (destination / ".python-version").write_text("3.12\n")
    (destination / "vercel.json").write_text(json.dumps({"functions": {"main.py": {"maxDuration": 300}}}, indent=2)+"\n")
    for name in ("requirements.txt", ".python-version", "vercel.json"):
        path = destination / name
        manifest.append({"path": name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    result = {"kind": "local_source_staging_not_vercel_build", "files": manifest,
              "source_bytes": sum(entry["bytes"] for entry in manifest)}
    (destination / "source-manifest.json").write_text(json.dumps(result, indent=2)+"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.destination)
    print(json.dumps({"files": len(result["files"]), "source_bytes": result["source_bytes"]}))
