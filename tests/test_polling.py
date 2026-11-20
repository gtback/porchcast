"""Tests for poll timing and carrier backoff."""

import datetime as dt

from custom_components.porchcast.polling import BACKOFF_MAX, Backoff

NOW = dt.datetime(2026, 11, 21, 17, tzinfo=dt.UTC)


def test_backoff_doubles_to_cap_without_overflow() -> None:
    """15, 30, 60 min, then 2 h, however long the outage lasts."""
    backoff = Backoff()
    delays = []
    for _ in range(100):
        backoff.failed(NOW)
        assert backoff.until is not None
        delays.append(backoff.until - NOW)
    assert delays[:4] == [dt.timedelta(minutes=m) for m in (15, 30, 60, 120)]
    assert delays[-1] == BACKOFF_MAX

    backoff.succeeded()
    assert not backoff.blocked(NOW)


def test_retry_after_is_honored_in_full() -> None:
    """A carrier's own wait isn't cut to 2 h; only absurd values are capped."""
    backoff = Backoff()
    backoff.failed(NOW, retry_after=4 * 3600)
    assert backoff.until == NOW + dt.timedelta(hours=4)
    backoff.failed(NOW, retry_after=10**12)
    assert backoff.until == NOW + dt.timedelta(days=1)
