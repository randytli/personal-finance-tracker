"""Stage the files for the private backup repository (randytli/pft-backups).

Copies the reviewed runner, workflow template and restore runbook into a
target directory, normally a fresh local clone of the backup repository:

    .github/workflows/pft-backup.yml
    runner/{pft_backup_runner.py, release_store.py, snapshot_dump.sql, fingerprint.sql, SHA256SUMS}
    RESTORE.md
    config/recipients.txt.example

It then verifies ``runner/SHA256SUMS`` and writes ``STAGED_FROM.txt`` naming
the PFT commit. It never creates ``config/recipients.txt`` (the owner adds the
two real public keys) or ``config/supabase-ca.crt``, and never runs git:
committing and pushing stay manual and approved. Standard library only.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNNER_FILES = ("pft_backup_runner.py", "release_store.py", "snapshot_dump.sql", "fingerprint.sql",
                "SHA256SUMS")
EXAMPLE_RECIPIENTS = """\
# age X25519 public keys, one per line. At least two are required.
# Generate offline (backup design §5.2) and paste ONLY the public keys here:
#   age-keygen | age -p -o daily.key.age        (prints "Public key: age1...")
#   age-keygen | age -p -o emergency.key.age
# Then save this file as config/recipients.txt.
# daily
age1REPLACE_WITH_DAILY_PUBLIC_KEY
# emergency
age1REPLACE_WITH_EMERGENCY_PUBLIC_KEY
"""


class StageError(RuntimeError):
    pass


def stage(target, *, commit):
    target = Path(target)
    if not target.is_dir():
        raise StageError("target directory must exist (a clone of the backup repository)")
    plan = {target / ".github" / "workflows" / "pft-backup.yml": HERE / "pft-backup.yml",
            target / "RESTORE.md": ROOT / "docs" / "PFT_BACKUP_RESTORE_RUNBOOK.md"}
    plan.update({target / "runner" / name: HERE / name for name in RUNNER_FILES})
    existing = [str(path.relative_to(target)) for path in plan if path.exists()]
    if existing:
        raise StageError("refusing to overwrite: " + ", ".join(sorted(existing)))
    for destination, source in plan.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    example = target / "config" / "recipients.txt.example"
    example.parent.mkdir(exist_ok=True)
    if not example.exists():
        example.write_text(EXAMPLE_RECIPIENTS)
    for line in (target / "runner" / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        if hashlib.sha256((target / name).read_bytes()).hexdigest() != digest:
            raise StageError(f"staged file does not match SHA256SUMS: {name}")
    (target / "STAGED_FROM.txt").write_text(
        f"Staged from personal-finance-tracker commit {commit} by deploy/backup_runner/stage_backup_repo.py.\n"
        "Update only by re-staging from a reviewed commit.\n")
    missing = [name for name in ("config/recipients.txt", "config/supabase-ca.crt")
               if not (target / name).exists()]
    return {"staged": sorted(str(p.relative_to(target)) for p in plan) + ["config/recipients.txt.example",
                                                                         "STAGED_FROM.txt"],
            "still_required_before_first_run": missing}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                            check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", "deploy/backup_runner",
                            "docs/PFT_BACKUP_RESTORE_RUNBOOK.md"], capture_output=True, text=True,
                           check=True).stdout.strip()
    if dirty:
        raise SystemExit("stage only committed runner files (deploy/backup_runner has local changes)")
    result = stage(args.target, commit=commit)
    for name in result["staged"]:
        print("staged", name)
    for name in result["still_required_before_first_run"]:
        print("REQUIRED before the first run:", name)


if __name__ == "__main__":
    main()
