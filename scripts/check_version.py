#!/usr/bin/env python3
"""Fail if the integration changed but its version is not higher than the base's.

Usage: scripts/check_version.py <base-ref>   (for example origin/main)
"""

import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bump_version import parse

MANIFEST = "custom_components/porchcast/manifest.json"


def as_key(version: str) -> tuple[int, int, int, float]:
    """Sort key where a pre-release sorts before its final version."""
    major, minor, patch, beta = parse(version)
    return major, minor, patch, float("inf") if beta is None else beta


def main() -> int:
    """Compare manifest versions between HEAD and the base ref."""
    base = sys.argv[1]
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD", "--", "custom_components/"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if not changed:
        print("No changes under custom_components/; no version bump needed.")
        return 0
    shown = subprocess.run(
        ["git", "show", f"{base}:{MANIFEST}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        print(f"{base} has no manifest yet; any version is fine.")
        return 0
    old = json.loads(shown.stdout)["version"]
    new = json.loads(Path(MANIFEST).read_text())["version"]
    if as_key(new) <= as_key(old):
        print(
            f"::error::custom_components/ changed but version {new} is not higher than {old}. Run scripts/bump_version.py."
        )
        return 1
    print(f"Version {old} -> {new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
