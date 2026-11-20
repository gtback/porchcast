"""Tests for description rendering and stored-data decoding."""

import datetime as dt
from typing import Any

import pytest

from custom_components.porchcast.carriers.base import Eta, Event, Status
from custom_components.porchcast.const import Carrier
from custom_components.porchcast.store import (
    NO_NUMBER_LINE,
    SEPARATOR,
    Package,
    PollState,
    _decode_package,
    _encode_package,
    notes_from_description,
)
from custom_components.porchcast.tracking import TrackingNumber

UPS = "1Z999AA10123456784"
PT = dt.timezone(dt.timedelta(hours=-8))  # US/Pacific in November


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


def test_unknown_tracking_data_survives_until_number_changes() -> None:
    """Nested keys and unknown carriers are kept while the number is unchanged."""
    tracking = {
        "number": UPS,
        "carriers": ["ups", "dhl"],
        "forced": False,
        "poll": {"future_key": 2},
    }
    package = _decode_package({"uid": "a", "summary": "Rack", "tracking": tracking})
    assert package is not None
    assert _encode_package(package)["tracking"] == tracking

    package.set_tracking(TrackingNumber("123456789012", (Carrier.FEDEX,)))
    assert _encode_package(package)["tracking"] == {
        "number": "123456789012",
        "carriers": ["fedex"],
        "forced": False,
    }


def test_unknown_only_carriers_survive_until_edited() -> None:
    """Data for a carrier this version doesn't know is kept until the item changes."""
    tracking = {"number": UPS, "carriers": ["dhl"], "poll": {"failures": 1}}
    package = _decode_package({"uid": "a", "summary": UPS, "tracking": tracking})
    assert package is not None
    assert package.tracking is None
    assert _encode_package(package)["tracking"] == tracking

    package.set_tracking(TrackingNumber(UPS, (Carrier.UPS,)))
    assert _encode_package(package)["tracking"] == {
        "number": UPS,
        "carriers": ["ups"],
        "forced": False,
    }


def test_changed_tracking_never_restores_old_data() -> None:
    """A -> B -> A writes fresh data; a changed override is saved."""
    tracking = {"number": UPS, "carriers": ["ups"], "forced": True, "poll": {}}
    package = _decode_package({"uid": "a", "summary": UPS, "tracking": tracking})
    assert package is not None
    ups = TrackingNumber(UPS, (Carrier.UPS,), forced=True)
    package.set_tracking(ups)  # unchanged: kept
    assert _encode_package(package)["tracking"] == tracking

    package.set_tracking(TrackingNumber("123456789012", (Carrier.FEDEX,)))
    package.set_tracking(ups)
    assert "poll" not in _encode_package(package)["tracking"]

    package.set_tracking(TrackingNumber(UPS, (Carrier.FEDEX,), forced=True))
    assert _encode_package(package)["tracking"]["carriers"] == ["fedex"]


def test_notes_keep_indentation() -> None:
    """Leading indentation in the notes is kept; trailing space isn't."""
    text = f"  indented note\n  - item  \n\n{SEPARATOR}\nUPS {UPS}"
    assert notes_from_description(text, None) == "  indented note\n  - item"
    package = _package("  indented note")
    assert notes_from_description(package.description(), package) == ("  indented note")


def _polled() -> Package:
    package = _package()
    package.poll = PollState(
        carrier=Carrier.UPS,
        status=Status.OUT_FOR_DELIVERY,
        description="Out For Delivery Today",
        eta=Eta(
            dt.datetime(2026, 11, 24, 14, tzinfo=PT),
            dt.datetime(2026, 11, 24, 18, tzinfo=PT),
        ),
        last_event=Event(
            "Out For Delivery Today",
            "Anytown, ST",
            dt.datetime(2026, 11, 24, 8, 2, tzinfo=PT),
        ),
        checked=dt.datetime(2026, 11, 24, 8, 15, tzinfo=PT),
        next_poll=dt.datetime(2026, 11, 24, 8, 35, tzinfo=PT),
        failures=1,
    )
    return package


def test_poll_state_round_trip() -> None:
    """Poll state is stored under tracking.poll and read back intact."""
    package = _polled()
    encoded = _encode_package(package)
    assert encoded["tracking"]["poll"]["status"] == "out_for_delivery"
    decoded = _decode_package(encoded)
    assert decoded is not None
    assert decoded.poll == package.poll

    package.poll = PollState(
        status=Status.DELIVERED,
        eta=Eta(dt.date(2026, 11, 24), dt.date(2026, 11, 26)),
        delivered_at=dt.datetime(2026, 11, 24, 15, 10, tzinfo=PT),
        delivered_location="Front Door",
        problem="Something",
    )
    decoded = _decode_package(_encode_package(package))
    assert decoded is not None
    assert decoded.poll == package.poll


def test_poll_state_keeps_unknown_keys_and_tolerates_junk() -> None:
    """Unknown poll keys survive; junk values fall back to defaults."""
    raw_poll = {
        "carrier": "dhl",
        "status": "lost_in_space",
        "eta": {"start": "2026-11-24"},
        "last_event": {"text": ""},
        "failures": "many",
        "checked": "2026-11-24",
        "future_key": [1, 2],
    }
    tracking = {"number": UPS, "carriers": ["ups"], "poll": raw_poll}
    package = _decode_package({"uid": "a", "summary": UPS, "tracking": tracking})
    assert package is not None
    assert package.poll == PollState()

    package.poll.failures = 1
    assert _encode_package(package)["tracking"]["poll"]["future_key"] == [1, 2]


def test_status_block_after_polls(hass: Any) -> None:
    """The status block shows status, window, last scan and check time.

    The ``hass`` fixture sets HA's time zone to US/Pacific.
    """
    assert _polled().status_lines() == [
        f"UPS {UPS}",
        "Status: Out for delivery",
        "Expected Nov 24, 2-6 pm",
        "Last scan: Out For Delivery Today, Anytown, ST, Nov 24, 8:02 am",
        "Checked Nov 24, 8:15 am",
    ]

    package = _polled()
    package.poll.status = Status.DELIVERED
    package.poll.delivered_at = dt.datetime(2026, 11, 24, 15, 10, tzinfo=PT)
    package.poll.delivered_location = "Front Door"
    package.poll.problem = "A problem line"
    assert package.status_lines()[1:4] == [
        "Status: Delivered",
        "Delivered Nov 24, 3:10 pm, Front Door",
        "Last scan: Out For Delivery Today, Anytown, ST, Nov 24, 8:02 am",
    ]
    assert package.status_lines()[4] == "A problem line"

    # A problem before any answer replaces "not checked yet".
    package = _package()
    package.poll.problem = "UPS isn't set up in Porchcast."
    assert package.status_lines() == [f"UPS {UPS}", "UPS isn't set up in Porchcast."]


def test_answering_carrier_replaces_candidates() -> None:
    """Once a carrier answers for an ambiguous number, only it is named."""
    package = Package(
        uid="x",
        summary="Shoes",
        tracking=TrackingNumber(
            "9400100000000000000006", (Carrier.USPS, Carrier.FEDEX)
        ),
    )
    package.poll.carrier = Carrier.USPS
    assert package.carriers == (Carrier.USPS,)
    assert package.status_lines()[0] == "USPS 9400100000000000000006"
