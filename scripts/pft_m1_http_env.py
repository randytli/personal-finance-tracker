"""Apply or reverse only the M1 HTTP allowlists in a private runtime env file.

No credential values are printed. Production use requires a separate approval.
"""

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit


HOSTS = "PFT_ALLOWED_HOSTS=api:8000,127.0.0.1:8000"
LOCAL_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_TAILNET_NAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})+\.ts\.net\Z")


def validate_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (value != value.strip() or parsed.scheme != "https" or
            not parsed.hostname or not _TAILNET_NAME.fullmatch(parsed.hostname) or
            parsed.netloc != parsed.hostname or parsed.path or parsed.query or parsed.fragment):
        raise ValueError("Expected the assigned https://<device>.<tailnet>.ts.net origin")
    return value


def update(path: Path, origin: str, *, rollback: bool = False,
           previous_origin: str | None = None) -> None:
    validate_origin(origin)
    if previous_origin is not None:
        validate_origin(previous_origin)
        if rollback or previous_origin == origin:
            raise ValueError("Origin replacement must change one origin without rollback")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Runtime env file is not private")
    original = path.read_text()
    if not original.endswith("\n"):
        raise ValueError("Runtime env file must end with a newline")
    lines = original.splitlines()
    if (lines.count("PFT_STRICT_LOCAL_HTTP=true") != 1 or
            lines.count("PFT_ALLOWED_ORIGIN=http://127.0.0.1:3000") != 1):
        raise ValueError("Unexpected existing HTTP boundary configuration")
    origins = f"PFT_ALLOWED_ORIGINS={LOCAL_ORIGINS},{origin}"
    additions = [HOSTS, origins]
    if previous_origin is not None:
        previous_line = f"PFT_ALLOWED_ORIGINS={LOCAL_ORIGINS},{previous_origin}"
        if (lines.count(HOSTS) != 1 or lines.count(previous_line) != 1 or
                sum(line.startswith("PFT_ALLOWED_ORIGINS=") for line in lines) != 1 or
                sum(line.startswith("PFT_ALLOWED_HOSTS=") for line in lines) != 1):
            raise ValueError("M1 allowlists differ; refusing origin replacement")
        updated = [origins if line == previous_line else line for line in lines]
    elif rollback:
        if any(lines.count(line) != 1 for line in additions):
            raise ValueError("M1 allowlists differ; refusing rollback")
        updated = [line for line in lines if line not in additions]
    else:
        if any(line.startswith(("PFT_ALLOWED_HOSTS=", "PFT_ALLOWED_ORIGINS=")) for line in lines):
            raise ValueError("M1 allowlists already present; refusing overwrite")
        updated = lines + additions
    candidate = "\n".join(updated) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".pft-m1-env-", dir=path.parent)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if previous_origin is not None:
        print("M1 HTTPS origin replaced")
    else:
        print("M1 HTTP allowlists removed" if rollback else "M1 HTTP allowlists prepared")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, default=Path(".env.runtime.production.local"))
    parser.add_argument("--origin", required=True)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--previous-origin")
    arguments = parser.parse_args()
    update(arguments.file, arguments.origin, rollback=arguments.rollback,
           previous_origin=arguments.previous_origin)


if __name__ == "__main__":
    main()
