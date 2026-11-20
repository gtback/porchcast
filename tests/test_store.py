"""Tests for description rendering and stored-data decoding."""

import datetime as dt
from typing import Any

import pytest

from custom_components.porchcast.const import Carrier
from custom_components.porchcast.store import (
    NO_NUMBER_LINE,
    SEPARATOR,
    Package,
    _decode_package,
    _encode_package,
    notes_from_description,
)
from custom_components.porchcast.tracking import TrackingNumber

UPS = "1Z999AA10123456784"


def _package(notes: str | None = "Bike rack from REI") -> Package:
    return Package(
        uid="abc",
        summary=f"Bike rack {UPS}",
        notes=notes,
        tracking=TrackingNumber(UPS, (Carrier.UPS,)),
    )


def test_description_layout() -> None:
    """Notes, a blank line, the separator, then the status block."""
    assert _package().description() == (
        f"Bike rack from REI\n\n{SEPARATOR}\nUPS {UPS}\nStatus: not checked yet"
    )
    assert _package(None).description() == (
        f"{SEPARATOR}\nUPS {UPS}\nStatus: not checked yet"
    )
    assert Package(uid="x", summary="Gift").description() == (
        f"{SEPARATOR}\n{NO_NUMBER_LINE}"
    )


def test_ambiguous_number_lists_both_carriers() -> None:
    """The status block names every carrier still in the running."""
    package = Package(
        uid="x",
        summary="Shoes",
        tracking=TrackingNumber(
            "9400100000000000000006", (Carrier.USPS, Carrier.FEDEX)
        ),
    )
    assert "USPS or FedEx 9400100000000000000006" in package.description()


def test_round_trip_keeps_notes() -> None:
    """Reading back a rendered description yields the notes unchanged."""
    package = _package("Line one\n\nLine two")
    assert notes_from_description(package.description(), package) == (
        "Line one\n\nLine two"
    )


@pytest.mark.parametrize(
    "separator",
    [
        SEPARATOR,
        "--- Tracking ---",
        "  ---tracking---  ",
        "\u2014 tracking \u2014",  # em dashes: iOS smart punctuation
        "\u2013\u2013 tracking \u2013\u2013",  # en dashes
        "- TRACKING -",
    ],
)
def test_separator_variants(separator: str) -> None:
    """Edited or auto-corrected separators still split notes from status."""
    text = f"My notes\r\n\r\n{separator}\r\nUPS {UPS}\r\nStatus: stale"
    assert notes_from_description(text, None) == "My notes"


def test_status_block_without_separator_is_dropped() -> None:
    """If only the separator line was deleted, the old block isn't kept as notes."""
    package = _package()
    text = package.description().replace(f"{SEPARATOR}\n", "")
    assert notes_from_description(text, package) == "Bike rack from REI"


def test_no_separator_means_all_notes() -> None:
    """Text with no separator and no old block is all notes."""
    assert notes_from_description("Just notes\nmore", _package()) == "Just notes\nmore"


@pytest.mark.parametrize("text", [None, "", "  \n", f"\n{SEPARATOR}\nUPS ..."])
def test_empty_notes(text: str | None) -> None:
    """Nothing above the separator means no notes."""
    assert notes_from_description(text, None) is None


def test_encode_decode_round_trip() -> None:
    """A package survives storage, including date vs datetime due values."""
    package = _package()
    package.due = dt.date(2026, 11, 24)
    assert _decode_package(_encode_package(package)) == package

    package.due = dt.datetime(2026, 11, 24, 9, 0, tzinfo=dt.UTC)
    assert _decode_package(_encode_package(package)) == package


def test_decode_keeps_unknown_keys_and_tolerates_junk() -> None:
    """Newer keys survive a round trip; bad values fall back to defaults."""
    raw: dict[str, Any] = {
        "uid": "abc",
        "summary": "Gift",
        "status": "weird",
        "due": 12,
        "completed": "2026-11-24",  # a date, not a datetime
        "tracking": {"number": UPS, "carriers": ["ups", "dhl"]},
        "poll": {"next": "2026-11-24T10:00:00+00:00"},
    }
    package = _decode_package(raw)
    assert package is not None
    assert package.due is None
    assert package.completed is None
    assert package.tracking == TrackingNumber(UPS, (Carrier.UPS,))
    assert _encode_package(package)["poll"] == raw["poll"]

    assert _decode_package({"summary": "no uid"}) is None
    assert _decode_package({"uid": "x", "summary": "t", "tracking": {}}) is not None
