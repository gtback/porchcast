"""The normalized tracking model every carrier client returns, and its errors.

This module and the clients don't import Home Assistant, so
``scripts/live_check.py`` can use them with a plain aiohttp session.
"""

from dataclasses import dataclass
import datetime as dt
from enum import StrEnum
from typing import Protocol


class Carrier(StrEnum):
    """Carriers Porchcast can track."""

    UPS = "ups"
    FEDEX = "fedex"
    USPS = "usps"


class Status(StrEnum):
    """Normalized package status."""

    PRE_TRANSIT = "pre_transit"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Eta:
    """The expected delivery: one day, a range of days, or a window on one day.

    ``start`` and ``end`` are each a date, or an aware datetime when the
    carrier gives a time. A single day has ``start == end``. A "by 10:30 am"
    commitment has a date ``start`` and a datetime ``end`` on the same day.
    """

    start: dt.date | dt.datetime
    end: dt.date | dt.datetime


@dataclass(frozen=True, slots=True)
class Event:
    """One scan or status update."""

    text: str
    location: str | None = None
    time: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class TrackingResult:
    """What a carrier says about one package."""

    carrier: Carrier
    status: Status
    # The carrier's own words for the current status, e.g. "Out For Delivery".
    description: str | None = None
    eta: Eta | None = None
    last_event: Event | None = None
    delivered_at: dt.datetime | None = None
    # Where it was left, e.g. "Front Door".
    delivered_location: str | None = None


class CarrierError(Exception):
    """The carrier couldn't be reached or returned something unusable."""


class AuthError(CarrierError):
    """The credentials were rejected. Retrying won't help; reauthenticate."""


class RateLimitedError(CarrierError):
    """The carrier asked us to slow down (HTTP 429)."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        """Record how long the carrier asked us to wait, if it said."""
        super().__init__(message)
        self.retry_after = retry_after


class NotFoundError(CarrierError):
    """The carrier has no data for this number (not yet, or not theirs)."""


class CarrierClient(Protocol):
    """What the coordinator and config flow need from a carrier client."""

    @property
    def carrier(self) -> Carrier:
        """The carrier this client talks to."""

    async def async_validate(self) -> None:
        """Check the credentials; raise ``AuthError`` or ``CarrierError``."""

    async def async_track(self, number: str) -> TrackingResult:
        """Return the current result for ``number``, or raise."""
