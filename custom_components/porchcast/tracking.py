"""Find tracking numbers in item text and work out which carrier they belong to.

Rules (recorded in docs/carriers.md on the plan branch):

- UPS: ``1Z`` plus 16 letters/digits, with the UPS mod-10 check digit.
- FedEx: 12 digits with the mod-11 check digit (weights 1, 3, 7 from the
  right); 15 digits; 20 digits; 22 digits starting with ``96``. Only the
  12-digit form is checked, because the other check-digit rules aren't
  published reliably enough to risk rejecting real numbers.
- USPS: IMpb, 22 digits starting with ``91``-``95`` (optionally after a
  ``420`` + ZIP routing prefix), or 20 digits, with the GS1 mod-10 check digit;
  and S10 international numbers (``AB123456785US``) with the UPU mod-11 check
  digit.
- A valid IMpb number is also tried with FedEx (FedEx ground economy hands
  packages to USPS with IMpb numbers); a 20-digit number may be either.
- A ``ups:``, ``fedex:`` or ``usps:`` prefix forces the carrier and skips the
  format checks.

Numbers may be written in groups separated by spaces (``9400 1000 ...``) or
hyphens. A number joined from several groups must pass a check digit, so that
unrelated numbers next to each other aren't glued together. URLs are skipped.
"""

from dataclasses import dataclass
import re

from .const import Carrier

# The forced number must contain a digit, so "USPS: tracking ..." isn't one.
_FORCED_RE = re.compile(
    r"\b(ups|fedex|usps):[ \t]?((?=[A-Za-z]*\d)[A-Za-z0-9]{6,40})\b", re.I
)
_PUNCTUATION = "()[]{}<>,.;:!?\"'*#"
_MAX_GROUPS = 8
_MAX_GROUP_LEN = 6


@dataclass(frozen=True, slots=True)
class TrackingNumber:
    """A tracking number and the carriers to try, in order."""

    number: str
    carriers: tuple[Carrier, ...]
    forced: bool = False


def _digits(value: str) -> list[int]:
    return [int(ch) for ch in value]


def ups_check_digit_ok(number: str) -> bool:
    """Validate a ``1Z`` number: letters map to digits, then mod 10."""
    body = number[2:]
    values = [int(ch) if ch.isdigit() else (ord(ch) - ord("A") + 2) % 10 for ch in body]
    *payload, check = values
    total = sum(v if i % 2 == 0 else 2 * v for i, v in enumerate(payload))
    return (10 - total % 10) % 10 == check


def fedex12_check_digit_ok(number: str) -> bool:
    """Validate a 12-digit FedEx Express number (mod 11, weights 1, 3, 7)."""
    *payload, check = _digits(number)
    weights = (1, 3, 7)
    total = sum(d * weights[i % 3] for i, d in enumerate(reversed(payload)))
    return total % 11 % 10 == check


def gs1_check_digit_ok(number: str) -> bool:
    """Validate a GS1 mod-10 check digit (weights 3, 1 from the right)."""
    *payload, check = _digits(number)
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    return (10 - total % 10) % 10 == check


def s10_check_digit_ok(number: str) -> bool:
    """Validate a UPU S10 number such as ``AB123456785US``."""
    *payload, check = _digits(number[2:11])
    total = sum(d * w for d, w in zip(payload, (8, 6, 4, 2, 3, 5, 9, 7), strict=True))
    expected = 11 - total % 11
    expected = {10: 0, 11: 5}.get(expected, expected)
    return expected == check


def _strip_usps_routing(number: str) -> str:
    """Drop a ``420`` + 5- or 9-digit ZIP prefix in front of an IMpb number."""
    if number.startswith("420") and len(number) in (30, 34):
        return number[-22:]
    return number


def classify(number: str) -> tuple[tuple[Carrier, ...], bool]:
    """Return (carriers to try, whether a check digit was verified).

    ``number`` must already be upper case with no separators. An empty tuple
    means it isn't a tracking number we recognize.
    """
    if re.fullmatch(r"1Z[0-9A-Z]{16}", number):
        return ((Carrier.UPS,), True) if ups_check_digit_ok(number) else ((), False)
    if re.fullmatch(r"[A-Z]{2}\d{9}[A-Z]{2}", number):
        ok = s10_check_digit_ok(number)
        return ((Carrier.USPS,), True) if ok else ((), False)
    if not number.isdigit():
        return (), False

    number = _strip_usps_routing(number)
    length = len(number)
    if length == 12:
        ok = fedex12_check_digit_ok(number)
        return ((Carrier.FEDEX,), True) if ok else ((), False)
    if length == 15:
        return (Carrier.FEDEX,), False
    if length == 22 and number.startswith("96"):
        return (Carrier.FEDEX,), False
    if length == 22 and number[:2] in {"91", "92", "93", "94", "95"}:
        if gs1_check_digit_ok(number):
            return (Carrier.USPS, Carrier.FEDEX), True
        return (), False
    if length == 20:
        if gs1_check_digit_ok(number):
            return (Carrier.USPS, Carrier.FEDEX), True
        return (Carrier.FEDEX,), False
    return (), False


def _clean(token: str) -> str | None:
    """Normalize one whitespace-separated token, or None to break a run."""
    token = token.strip(_PUNCTUATION)
    if not token or "/" in token or "@" in token or "=" in token:
        return None
    if token.lower().startswith("www."):
        return None
    token = token.replace("-", "").upper()
    return token if token.isalnum() else None


def _routing_free(number: str) -> str:
    """Return the number as stored: the IMpb part of a ``420`` ZIP barcode."""
    return _strip_usps_routing(number) if number.isdigit() else number


def find_tracking_number(text: str | None) -> TrackingNumber | None:
    """Return the first tracking number in ``text``, or None."""
    if not text:
        return None

    if forced := _FORCED_RE.search(text):
        return TrackingNumber(
            number=forced.group(2).upper(),
            carriers=(Carrier(forced.group(1).lower()),),
            forced=True,
        )

    tokens = [_clean(token) for token in text.split()]
    for start, first in enumerate(tokens):
        if first is None:
            continue
        # Prefer the longest run of short groups that passes a check digit.
        joined = first
        best: TrackingNumber | None = None
        for token in tokens[start + 1 : start + _MAX_GROUPS]:
            if token is None or len(token) > _MAX_GROUP_LEN:
                break
            joined += token
            carriers, checked = classify(joined)
            if carriers and checked:
                best = TrackingNumber(_routing_free(joined), carriers)
        if best is not None:
            return best
        carriers, _ = classify(first)
        if carriers:
            return TrackingNumber(_routing_free(first), carriers)
    return None
