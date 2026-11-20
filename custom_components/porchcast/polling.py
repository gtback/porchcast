"""When to poll: per-status intervals, error handling and carrier backoff.

Kept apart from the coordinator so the timing rules are easy to read and test.
"""

from dataclasses import dataclass
import datetime as dt
from typing import Final

from .carriers.base import Status

TICK: Final = dt.timedelta(minutes=15)

# How often to ask about a package, by its last status. Delivered packages
# aren't polled.
INTERVALS: Final[dict[Status | None, dt.timedelta]] = {
    Status.OUT_FOR_DELIVERY: dt.timedelta(minutes=20),
    Status.IN_TRANSIT: dt.timedelta(hours=2),
    Status.EXCEPTION: dt.timedelta(hours=2),
    Status.PRE_TRANSIT: dt.timedelta(hours=6),
    Status.UNKNOWN: dt.timedelta(hours=6),
    None: dt.timedelta(hours=6),
}
SLOW: Final = dt.timedelta(hours=6)

# After a failed poll, try again sooner than the status interval, until this
# many failures in a row; then say so in the status block and poll at SLOW.
MAX_FAILURES: Final = 5
RETRY: Final = dt.timedelta(minutes=30)

# Carrier-wide backoff after a rate limit or an outage: 15 min, doubling, up
# to 2 h, unless the carrier says how long to wait. A carrier's Retry-After is
# honored in full, up to a day (a sanity limit against a garbled header).
BACKOFF_START: Final = dt.timedelta(minutes=15)
BACKOFF_MAX: Final = dt.timedelta(hours=2)
RETRY_AFTER_MAX: Final = dt.timedelta(days=1)
# 15 min * 2**3 already exceeds 2 h; capping the exponent avoids overflow.
_MAX_DOUBLINGS: Final = 8


def next_poll_after_success(status: Status, now: dt.datetime) -> dt.datetime | None:
    """When to ask again after an answer; None for delivered (never)."""
    if status is Status.DELIVERED:
        return None
    return now + INTERVALS[status]


def next_poll_after_failure(
    status: Status | None, failures: int, now: dt.datetime
) -> dt.datetime:
    """When to ask again after ``failures`` failures in a row."""
    if failures >= MAX_FAILURES:
        return now + SLOW
    return now + min(INTERVALS[status], RETRY)


@dataclass(slots=True)
class Backoff:
    """One carrier's backoff after rate limits or outages."""

    failures: int = 0
    until: dt.datetime | None = None

    def blocked(self, now: dt.datetime) -> bool:
        """Whether to leave the carrier alone for now."""
        return self.until is not None and now < self.until

    def failed(self, now: dt.datetime, retry_after: float | None = None) -> None:
        """Record a carrier-wide failure."""
        self.failures += 1
        if retry_after is not None and retry_after > 0:
            delay = min(dt.timedelta(seconds=retry_after), RETRY_AFTER_MAX)
        else:
            doublings = min(self.failures - 1, _MAX_DOUBLINGS)
            delay = min(BACKOFF_START * 2**doublings, BACKOFF_MAX)
        self.until = now + delay

    def succeeded(self) -> None:
        """Clear the backoff."""
        self.failures = 0
        self.until = None
