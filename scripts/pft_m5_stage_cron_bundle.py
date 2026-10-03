"""Stage the M5 cron acceptance bundle in a fresh private directory; no cloud calls.

main.py is experiments/m5_cloud/cron_jobs_app.py; the synthetic fixture client
sits next to it. Only Python source of the listed packages is copied, never
env files or data. Run as: python -m scripts.pft_m5_stage_cron_bundle --destination DIR
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

from scripts.pft_m5_prepare_cloud_bundle import check_entrypoints

ROOT = Path(__file__).resolve().parents[1]
RENAMED = {"experiments/m5_cloud/cron_jobs_app.py": "main.py",
           "experiments/m5_cloud/cron_fixture_client.py": "m5_cron_fixture.py"}
EXCLUDED = {"api/main.py", "api/migrate_once.py", "api/sync_once.py"}


def sources():
    files = [ROOT / path for path in RENAMED]
    for relative in ("api", "api/routes", "api/services", "statement_imports"):
        files.extend(sorted((ROOT / relative).glob("*.py")))
    files = [path for path in files if path.relative_to(ROOT).as_posix() not in EXCLUDED]
    if any(path.is_symlink() for path in files):
        raise RuntimeError("Symlink source rejected")
    return files


def bundled(path):
    relative = path.relative_to(ROOT).as_posix()
    return RENAMED.get(relative, relative)


def stage(destination):
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(ROOT):
        raise RuntimeError("Requires a fresh destination outside the repository")
    files = sources()
    check_entrypoints([bundled(path) for path in files], {bundled(path): path.read_text() for path in files})
    destination.mkdir(mode=0o700, parents=True)
    generated = {"requirements.txt": (ROOT / "api/requirements.txt").read_bytes(),
                 ".python-version": b"3.12\n",
                 "vercel.json": (json.dumps({"functions": {"main.py": {"maxDuration": 300}}}, indent=2) + "\n").encode()}
    manifest = []
    for source in files:
        target = destination / bundled(source)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
    for name, data in generated.items():
        (destination / name).write_bytes(data)
    for target in sorted(path for path in destination.rglob("*") if path.is_file()):
        manifest.append({"path": target.relative_to(destination).as_posix(), "bytes": target.stat().st_size,
                         "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    result = {"kind": "m5_cron_acceptance_bundle", "files": manifest,
              "source_bytes": sum(entry["bytes"] for entry in manifest)}
    (destination / "source-manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    result = stage(parser.parse_args().destination)
    print(json.dumps({"files": len(result["files"]), "source_bytes": result["source_bytes"]}))
