"""Tests for status-block date and time text (HA's zone is US/Pacific here)."""

import datetime as dt
from typing import Any

import pytest

from custom_components.porchcast import render
from custom_components.porchcast.carriers.base import Eta

PT = dt.timezone(dt.timedelta(hours=-8))  # US/Pacific in November
D = dt.date


def _t(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=PT)


@pytest.mark.parametrize(
    ("eta", "text"),
    [
        (Eta(D(2026, 11, 24), D(2026, 11, 24)), "Nov 24"),
        (Eta(D(2026, 11, 24), D(2026, 11, 28)), "Nov 24-28"),
        (Eta(D(2026, 11, 30), D(2026, 12, 2)), "Nov 30-Dec 2"),
        (Eta(_t(24, 14), _t(24, 18)), "Nov 24, 2-6 pm"),
        (Eta(_t(24, 9, 30), _t(24, 13)), "Nov 24, 9:30 am-1 pm"),
        (Eta(_t(24, 0), _t(24, 12)), "Nov 24, 12 am-12 pm"),
        (Eta(D(2026, 11, 24), _t(24, 10, 30)), "Nov 24, by 10:30 am"),
        (Eta(_t(24, 20), _t(25, 2)), "Nov 24, 8 pm-Nov 25, 2 am"),
        (Eta(D(2026, 11, 24), _t(25, 12)), "Nov 24-Nov 25, 12 pm"),
        (Eta(_t(24, 20), D(2026, 11, 25)), "Nov 24, 8 pm-Nov 25"),
        # A UTC window is shown in local time.
        (
            Eta(
                dt.datetime(2026, 11, 24, 22, tzinfo=dt.UTC),
                dt.datetime(2026, 11, 25, 2, tzinfo=dt.UTC),
            ),
            "Nov 24, 2-6 pm",
        ),
    ],
)
def test_eta(hass: Any, eta: Eta, text: str) -> None:
    """Days, ranges, windows and commit times read naturally."""
    assert render.eta(eta) == text


def test_when(hass: Any) -> None:
    """A moment is a day and a clock time."""
    assert render.when(_t(21, 8, 2)) == "Nov 21, 8:02 am"
    assert render.when(_t(21, 12)) == "Nov 21, 12 pm"
