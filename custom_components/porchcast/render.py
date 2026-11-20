"""Short, phone-friendly text for dates, times and windows in the status block.

Times are shown in HA's time zone: "Nov 24", "Nov 24-28", "Nov 24, 2-6 pm",
"Nov 24, by 10:30 am", "Nov 21, 8:02 am".
"""

import datetime as dt

from homeassistant.util import dt as dt_util

from .carriers.base import Eta


def _day(value: dt.date) -> str:
    return f"{value:%b} {value.day}"


def _clock(value: dt.time, *, meridiem: bool = True) -> str:
    hour = value.hour % 12 or 12
    text = f"{hour}:{value.minute:02d}" if value.minute else str(hour)
    if meridiem:
        text += " am" if value.hour < 12 else " pm"
    return text


def _local(value: dt.datetime) -> dt.datetime:
    return dt_util.as_local(value)


def when(value: dt.datetime) -> str:
    """A moment: "Nov 21, 8:02 am"."""
    local = _local(value)
    return f"{_day(local.date())}, {_clock(local.time())}"


def _day_range(start: dt.date, end: dt.date) -> str:
    if start == end:
        return _day(start)
    if (start.year, start.month) == (end.year, end.month):
        return f"{_day(start)}-{end.day}"
    return f"{_day(start)}-{_day(end)}"


def eta(value: Eta) -> str:
    """The expected delivery, as a day, a range of days or a window."""
    start, end = value.start, value.end
    if isinstance(start, dt.datetime) and isinstance(end, dt.datetime):
        start, end = _local(start), _local(end)
        if start.date() == end.date():
            same_half = (start.hour < 12) == (end.hour < 12)
            window = (
                f"{_clock(start.time(), meridiem=not same_half)}-{_clock(end.time())}"
            )
            return f"{_day(start.date())}, {window}"
        return f"{when(start)}-{when(end)}"
    if isinstance(end, dt.datetime):
        end = _local(end)
        if start == end.date():
            return f"{_day(start)}, by {_clock(end.time())}"
        return f"{_day(start)}-{when(end)}"
    if isinstance(start, dt.datetime):
        return f"{when(start)}-{_day(end)}"
    return _day_range(start, end)
