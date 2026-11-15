"""Set the advisor sign-in passcode (and a session signing key) in backend/.env without ever showing either.

    python scripts/set_advisor_password.py            # prompts twice, input is hidden
    python scripts/set_advisor_password.py --env-file /path/to/.env

Writes LOANKART_ADVISOR_PASSWORD, and generates LOANKART_SECRET_KEY if the file has none. Nothing is printed except
which setting names were written. The file is created owner-read/write only (0600). Restart the backend afterwards.
"""

import argparse
import getpass
import os
import secrets
import sys
import tempfile
from pathlib import Path

MIN_LENGTH = 12
DEFAULT_ENV = Path(__file__).resolve().parent.parent / ".env"


def write_settings(path: Path, updates: dict[str, str]) -> None:
    """Replace or append KEY=VALUE lines for the given keys only; every other line is kept as it is, in order."""
    lines = path.read_text().splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if key in updates and not line.lstrip().startswith("#"):
            lines[i], _ = f"{key}={updates[key]}", seen.add(key)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.tmp-")      # mkstemp files are owner-only (0600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)                                             # atomic: a crash never leaves a half-written .env
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def has_setting(path: Path, name: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name and value.strip().strip("\"'") and not line.lstrip().startswith("#"):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    path = parser.parse_args(argv).env_file
    password = getpass.getpass(f"New advisor passcode ({MIN_LENGTH}+ characters, not shown): ")
    if len(password) < MIN_LENGTH:
        print(f"Too short: use at least {MIN_LENGTH} characters. Nothing was changed.", file=sys.stderr)
        return 1
    if password != password.strip() or password[0] in "\"'" or password[-1] in "\"'":
        print("Do not start or end the passcode with a space or quote mark. Nothing was changed.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Repeat it: "):
        print("The two entries do not match. Nothing was changed.", file=sys.stderr)
        return 1
    updates = {"LOANKART_ADVISOR_PASSWORD": password}
    if not has_setting(path, "LOANKART_SECRET_KEY"):
        updates["LOANKART_SECRET_KEY"] = secrets.token_urlsafe(48)
    write_settings(path, updates)
    print(f"Wrote {', '.join(updates)} to {path} (mode 600). Restart the backend to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
