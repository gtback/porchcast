"""Tests for tracking-number extraction and carrier detection.

All numbers here are synthetic: carrier sample numbers or numbers built to pass
a check digit.
"""

import pytest

from custom_components.porchcast.const import Carrier
from custom_components.porchcast.tracking import (
    TrackingNumber,
    classify,
    fedex12_check_digit_ok,
    find_tracking_number,
    gs1_check_digit_ok,
    s10_check_digit_ok,
    ups_check_digit_ok,
)

UPS = "1Z999AA10123456784"
FEDEX12 = "123456789012"
USPS_IMPB = "9400100000000000000006"
USPS_92 = "9200100000000000000121"
USPS_20 = "03070000000000000000"
S10 = "RA123456785US"

BOTH = (Carrier.USPS, Carrier.FEDEX)


@pytest.mark.parametrize(
    ("check", "good", "bad"),
    [
        (ups_check_digit_ok, UPS, "1Z999AA10123456785"),
        (fedex12_check_digit_ok, FEDEX12, "123456789013"),
        (fedex12_check_digit_ok, "987654321010", "987654321011"),
        (gs1_check_digit_ok, USPS_IMPB, "9400100000000000000007"),
        (gs1_check_digit_ok, USPS_20, "03070000000000000001"),
        (s10_check_digit_ok, S10, "RA123456784US"),
    ],
)
def test_check_digits(check: object, good: str, bad: str) -> None:
    """Each check-digit rule accepts a valid number and rejects a typo."""
    assert callable(check)
    assert check(good)
    assert not check(bad)


@pytest.mark.parametrize(
    ("number", "carriers"),
    [
        (UPS, (Carrier.UPS,)),
        (FEDEX12, (Carrier.FEDEX,)),
        ("123456789012345", (Carrier.FEDEX,)),
        ("9612345678901234567890", (Carrier.FEDEX,)),
        (USPS_IMPB, BOTH),
        (USPS_92, BOTH),
        (USPS_20, BOTH),
        ("12345678901234567891", (Carrier.FEDEX,)),  # fails GS1: FedEx only
        (S10, (Carrier.USPS,)),
        ("42012345" + USPS_IMPB, BOTH),
        ("420123456789" + USPS_IMPB, BOTH),
    ],
)
def test_classify(number: str, carriers: tuple[Carrier, ...]) -> None:
    """Formats map to the carriers to try, in order."""
    assert classify(number)[0] == carriers


@pytest.mark.parametrize(
    "number",
    [
        "1Z999AA10123456785",  # bad check digit
        "123456789013",
        "9400100000000000000007",
        "RA123456784US",
        "12345",
        "1234567890123",  # 13 digits: no format
        "HELLO",
    ],
)
def test_classify_rejects(number: str) -> None:
    """Typos and other numbers aren't tracking numbers."""
    assert classify(number)[0] == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            f"Bike rack, REI {UPS} https://rei.example/order/123456789012",
            TrackingNumber(UPS, (Carrier.UPS,)),
        ),
        (f"lowercase {UPS.lower()}", TrackingNumber(UPS, (Carrier.UPS,))),
        (f"({UPS}).", TrackingNumber(UPS, (Carrier.UPS,))),
        ("UPS: 1Z 999 AA1 01 2345 6784", TrackingNumber(UPS, (Carrier.UPS,))),
        (
            "Shoes 9400 1000 0000 0000 0000 06 arriving",
            TrackingNumber(USPS_IMPB, BOTH),
        ),
        ("1234-5678-9012 desk", TrackingNumber(FEDEX12, (Carrier.FEDEX,))),
        (
            f"International {S10} from a friend",
            TrackingNumber(S10, (Carrier.USPS,)),
        ),
        # A 420 + ZIP routing prefix is dropped.
        (
            f"Label scan 42012345{USPS_IMPB}",
            TrackingNumber(USPS_IMPB, BOTH),
        ),
        # The first number wins.
        (f"{FEDEX12} and {UPS}", TrackingNumber(FEDEX12, (Carrier.FEDEX,))),
    ],
)
def test_find_tracking_number(text: str, expected: TrackingNumber) -> None:
    """Numbers are found in free text, with or without spaces."""
    assert find_tracking_number(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            f"fedex:{USPS_IMPB} gift",
            TrackingNumber(USPS_IMPB, (Carrier.FEDEX,), forced=True),
        ),
        (
            "Parts USPS: abc12345xyz",
            TrackingNumber("ABC12345XYZ", (Carrier.USPS,), forced=True),
        ),
        # A prefix followed by a word isn't a forced number.
        (
            "Sent via USPS: tracking 9400 1000 0000 0000 0000 06",
            TrackingNumber(USPS_IMPB, BOTH),
        ),
        (
            f"(fedex: {FEDEX12})",
            TrackingNumber(FEDEX12, (Carrier.FEDEX,), forced=True),
        ),
    ],
)
def test_prefix_forces_carrier(text: str, expected: TrackingNumber) -> None:
    """A carrier prefix wins and skips format checks."""
    assert find_tracking_number(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Birthday present for the neighbors",
        "Order https://shop.example/track?n=1Z999AA10123456784",
        "Call 555 123 4567 about the couch",
        "Typo 1Z999AA10123456785",
        "Mixed 1Z 999 AA1 01 2345 6785",
        "\u00b2" * 12,  # superscript digits: isdigit() but not int()
        "\u0661" * 12,  # Arabic-Indic digits
    ],
)
def test_no_number(text: str | None) -> None:
    """No number: nothing found, including inside URLs."""
    assert find_tracking_number(text) is None


@pytest.mark.parametrize("text", ["Order 12345 67890 12345", "Order 12345-67890-12345"])
def test_groups_must_pass_check_digit(text: str) -> None:
    """Groups aren't glued into an unchecked format (15-digit FedEx)."""
    assert find_tracking_number(text) is None


def test_unchecked_format_as_one_token() -> None:
    """An unchecked format written without separators is accepted."""
    assert find_tracking_number("Order 123456789012345") == TrackingNumber(
        "123456789012345", (Carrier.FEDEX,)
    )


def test_standalone_number_is_not_extended() -> None:
    """Groups after a valid number aren't glued onto it."""
    assert find_tracking_number(f"{FEDEX12} 0000 0000") == TrackingNumber(
        FEDEX12, (Carrier.FEDEX,)
    )


def test_first_number_wins_over_later_prefix() -> None:
    """A forced number later in the text doesn't beat an earlier number."""
    assert find_tracking_number(f"{FEDEX12} then ups:{UPS}") == TrackingNumber(
        FEDEX12, (Carrier.FEDEX,)
    )


def test_prefix_inside_url_is_ignored() -> None:
    """A prefix inside a URL isn't a forced number."""
    text = f"Order https://shop.example/track/fedex:{FEDEX12} for {UPS}"
    assert find_tracking_number(text) == TrackingNumber(UPS, (Carrier.UPS,))
