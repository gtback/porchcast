"""Bump the integration version in manifest.json.

Usage: scripts/bump_version.py [patch|minor|major|beta]

`beta` turns X.Y.Z into X.Y.ZbN (the next pre-release of the current version,
or the first pre-release of the next patch when the current version is final).
"""

import json
from pathlib import Path
import re
import sys

MANIFEST = (
    Path(__file__).resolve().parent.parent / "custom_components/porchcast/manifest.json"
)
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:b(\d+))?$")


def parse(version: str) -> tuple[int, int, int, int | None]:
    """Split a version into (major, minor, patch, beta)."""
    match = VERSION_RE.match(version)
    if not match:
        raise ValueError(f"Not a version this project uses: {version!r}")
    major, minor, patch, beta = match.groups()
    return int(major), int(minor), int(patch), None if beta is None else int(beta)


def bump(version: str, part: str) -> str:
    """Return the next version."""
    major, minor, patch, beta = parse(version)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        # A pre-release of X.Y.Z bumps to the final X.Y.Z.
        return (
            f"{major}.{minor}.{patch}"
            if beta is not None
            else f"{major}.{minor}.{patch + 1}"
        )
    if part == "beta":
        if beta is None:
            return f"{major}.{minor}.{patch + 1}b0"
        return f"{major}.{minor}.{patch}b{beta + 1}"
    raise ValueError(f"Unknown part {part!r}")


def read_version() -> str:
    """Return the manifest version."""
    return str(json.loads(MANIFEST.read_text())["version"])


def write_version(version: str) -> None:
    """Set the manifest version, keeping the file's layout."""
    parse(version)
    manifest = json.loads(MANIFEST.read_text())
    manifest["version"] = version
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    """Bump the manifest version in place and print it."""
    part = sys.argv[1] if len(sys.argv) > 1 else "patch"
    version = bump(read_version(), part)
    write_version(version)
    print(version)


if __name__ == "__main__":
    main()
