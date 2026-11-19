"""Tests for the version scripts."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from bump_version import bump
from check_version import as_key


@pytest.mark.parametrize(
    ("version", "part", "expected"),
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.3", "minor", "0.2.0"),
        ("0.2.3", "major", "1.0.0"),
        ("0.1.0", "beta", "0.1.1b0"),
        ("0.1.1b0", "beta", "0.1.1b1"),
        ("0.1.1b2", "patch", "0.1.1"),
    ],
)
def test_bump(version: str, part: str, expected: str) -> None:
    """Each part bumps as documented."""
    assert bump(version, part) == expected


def test_prerelease_sorts_before_final() -> None:
    """0.1.1b0 < 0.1.1 < 0.1.2."""
    assert as_key("0.1.1b0") < as_key("0.1.1") < as_key("0.1.2")


def test_rejects_unknown_format() -> None:
    """Only X.Y.Z and X.Y.ZbN are allowed."""
    with pytest.raises(ValueError, match="Not a version"):
        bump("1.0", "patch")
