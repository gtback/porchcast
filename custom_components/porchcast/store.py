"""Stored packages, and rendering each one's description as notes + status.

Home Assistant doesn't store to-do items for an integration, so this module
keeps every item (our text) and its tracking data (the integration's) in one
``Store``, in list order.

Schema changes are additive and bump ``STORAGE_MINOR_VERSION``. HA's ``Store``
hands data with a different minor version straight through when no migration
is needed, and loading ignores unknown keys, so an older Porchcast still reads
newer data after a rollback. A change that can't be additive bumps
``STORAGE_VERSION`` and adds a step to ``_PackageStore._async_migrate_func``.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
import datetime as dt
import logging
import re
from typing import Any, override

from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util, ulid as ulid_util

from . import render
from .carriers.base import Eta, Event, Status
from .const import CARRIER_NAMES, DOMAIN, Carrier
from .tracking import TrackingNumber, find_tracking_number

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# 1.2 (0.3.0): poll state under tracking.poll.
STORAGE_MINOR_VERSION = 2

SEPARATOR = "--- tracking ---"
# Accept the separator however a phone keyboard or editor may have mangled it:
# any run of dashes (including en/em dashes from "smart punctuation"), any
# case, extra spaces.
_SEPARATOR_RE = re.compile(
    "^[ \\t]*[-\u2010-\u2015]+[ \\t]*tracking[ \\t]*[-\u2010-\u2015]+[ \\t]*$",
    re.IGNORECASE | re.MULTILINE,
)

NO_NUMBER_LINE = "No tracking number found."
NOT_CHECKED_LINE = "Status: not checked yet"

STATUS_LABELS: dict[Status, str] = {
    Status.PRE_TRANSIT: "Label created",
    Status.IN_TRANSIT: "In transit",
    Status.OUT_FOR_DELIVERY: "Out for delivery",
    Status.DELIVERED: "Delivered",
    Status.EXCEPTION: "Exception",
    Status.UNKNOWN: "Unknown",
}


@dataclass(slots=True)
class PollState:
    """What the integration last learned about a package, and when to ask again.

    It resets whenever the tracking number changes.
    """

    # The carrier that answered, once one has (an ambiguous number lists
    # several).
    carrier: Carrier | None = None
    status: Status | None = None
    description: str | None = None
    eta: Eta | None = None
    last_event: Event | None = None
    delivered_at: dt.datetime | None = None
    delivered_location: str | None = None
    # Last time a carrier answered.
    checked: dt.datetime | None = None
    # None: as soon as possible.
    next_poll: dt.datetime | None = None
    failures: int = 0
    # A line explaining why the status may be stale, e.g. repeated errors.
    problem: str | None = None

    def lines(self, tracking: TrackingNumber) -> list[str]:
        """Render the status block below the number line."""
        lines: list[str] = []
        if self.status is None:
            if self.problem is None:
                lines.append(NOT_CHECKED_LINE)
        else:
            label = STATUS_LABELS[self.status]
            lines.append(f"Status: {label}")
        if self.status is Status.DELIVERED:
            if self.delivered_at is not None or self.delivered_location:
                parts = [
                    render.when(self.delivered_at) if self.delivered_at else None,
                    self.delivered_location,
                ]
                lines.append("Delivered " + ", ".join(p for p in parts if p))
        elif self.eta is not None:
            lines.append(f"Expected {render.eta(self.eta)}")
        if (event := self.last_event) is not None:
            parts = [
                event.text,
                event.location,
                render.when(event.time) if event.time else None,
            ]
            lines.append("Last scan: " + ", ".join(p for p in parts if p))
        if self.problem:
            lines.append(self.problem)
        if self.checked is not None:
            lines.append(f"Checked {render.when(self.checked)}")
        return lines


@dataclass(slots=True)
class Package:
    """One item on the Packages list."""

    uid: str
    summary: str
    notes: str | None = None
    status: TodoItemStatus = TodoItemStatus.NEEDS_ACTION
    due: dt.date | dt.datetime | None = None
    completed: dt.datetime | None = None
    tracking: TrackingNumber | None = None
    poll: PollState = field(default_factory=PollState)
    # Stored keys this version doesn't know (written by a newer version), kept
    # so a rollback followed by an upgrade loses nothing.
    extra: dict[str, Any] = field(default_factory=dict, compare=False)
    # The stored ``tracking`` object as loaded, for the same reason.
    tracking_raw: dict[str, Any] | None = field(default=None, compare=False)

    def set_tracking(self, tracking: TrackingNumber | None) -> None:
        """Set the tracking number; a change discards the stored object."""
        if tracking != self.tracking:
            self.tracking = tracking
            self.tracking_raw = None
            self.poll = PollState()

    @property
    def carriers(self) -> tuple[Carrier, ...]:
        """The carriers to ask: the one that answered, else every candidate."""
        if self.tracking is None:
            return ()
        if self.poll.carrier is not None:
            return (self.poll.carrier,)
        return self.tracking.carriers

    def status_lines(self) -> list[str]:
        """Return the managed status block, one entry per line."""
        if self.tracking is None:
            return [NO_NUMBER_LINE]
        names = " or ".join(CARRIER_NAMES[c] for c in self.carriers)
        return [f"{names} {self.tracking.number}", *self.poll.lines(self.tracking)]

    def description(self) -> str:
        """Render notes, the separator, then the status block."""
        block = "\n".join([SEPARATOR, *self.status_lines()])
        return f"{self.notes}\n\n{block}" if self.notes else block

    def to_todo_item(self) -> TodoItem:
        """Return the item as HA shows it."""
        return TodoItem(
            uid=self.uid,
            summary=self.summary,
            status=self.status,
            due=self.due,
            description=self.description(),
            completed=self.completed,
        )


def notes_from_description(
    description: str | None, package: Package | None
) -> str | None:
    """Return the user's notes: the text above the separator.

    If the separator is gone (the user deleted or reworded it) but the text
    still ends with the status block we rendered for ``package``, drop that
    block. Otherwise all of the text is notes.
    """
    if not description:
        return None
    text = description.replace("\r\n", "\n").replace("\r", "\n")
    if match := _SEPARATOR_RE.search(text):
        text = text[: match.start()]
    elif package is not None:
        block = "\n".join(package.status_lines())
        if text.rstrip().endswith(block):
            text = text.rstrip()[: -len(block)]
    # Keep the first line's indentation; drop blank lines around the notes and
    # the trailing space the rendered layout adds.
    text = text.rstrip().lstrip("\n")
    return text if text.strip() else None


def _encode_due(value: dt.date | dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decode_due(value: Any) -> dt.date | dt.datetime | None:
    if not isinstance(value, str):
        return None
    if "T" in value:
        return dt_util.parse_datetime(value)
    return dt_util.parse_date(value)


def _encode_datetime(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decode_datetime(value: Any) -> dt.datetime | None:
    decoded = _decode_due(value)
    return decoded if isinstance(decoded, dt.datetime) else None


def _encode_poll(poll: PollState) -> dict[str, Any]:
    eta = poll.eta
    event = poll.last_event
    return {
        "carrier": str(poll.carrier) if poll.carrier else None,
        "status": str(poll.status) if poll.status else None,
        "description": poll.description,
        "eta": (
            {"start": eta.start.isoformat(), "end": eta.end.isoformat()}
            if eta
            else None
        ),
        "last_event": (
            {
                "text": event.text,
                "location": event.location,
                "time": _encode_datetime(event.time),
            }
            if event
            else None
        ),
        "delivered_at": _encode_datetime(poll.delivered_at),
        "delivered_location": poll.delivered_location,
        "checked": _encode_datetime(poll.checked),
        "next_poll": _encode_datetime(poll.next_poll),
        "failures": poll.failures,
        "problem": poll.problem,
    }


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _decode_poll(value: Any) -> PollState:
    if not isinstance(value, dict):
        return PollState()
    eta: Eta | None = None
    if isinstance(raw_eta := value.get("eta"), dict):
        start, end = _decode_due(raw_eta.get("start")), _decode_due(raw_eta.get("end"))
        if start is not None and end is not None:
            eta = Eta(start, end)
    event: Event | None = None
    if isinstance(raw_event := value.get("last_event"), dict) and (
        text := _optional_str(raw_event.get("text"))
    ):
        event = Event(
            text=text,
            location=_optional_str(raw_event.get("location")),
            time=_decode_datetime(raw_event.get("time")),
        )
    carrier = value.get("carrier")
    status = value.get("status")
    failures = value.get("failures")
    return PollState(
        carrier=Carrier(carrier) if carrier in set(Carrier) else None,
        status=Status(status) if status in set(Status) else None,
        description=_optional_str(value.get("description")),
        eta=eta,
        last_event=event,
        delivered_at=_decode_datetime(value.get("delivered_at")),
        delivered_location=_optional_str(value.get("delivered_location")),
        checked=_decode_datetime(value.get("checked")),
        next_poll=_decode_datetime(value.get("next_poll")),
        failures=failures if isinstance(failures, int) else 0,
        problem=_optional_str(value.get("problem")),
    )


def _encode_tracking(package: Package) -> dict[str, Any] | None:
    """Encode the number and its poll state.

    Until an edit changes the number, the stored object is written back as
    loaded (it may carry keys or carriers this version doesn't know), with
    only the poll state updated.
    """
    tracking = package.tracking
    if tracking is None:
        return package.tracking_raw
    raw = package.tracking_raw
    if raw is None:
        raw = {
            "number": tracking.number,
            "carriers": [str(c) for c in tracking.carriers],
            "forced": tracking.forced,
        }
    if package.poll == PollState():
        # Never polled: nothing to add (and nothing to overwrite).
        return raw
    raw_poll = raw.get("poll")
    poll = raw_poll if isinstance(raw_poll, dict) else {}
    return {**raw, "poll": {**poll, **_encode_poll(package.poll)}}


def _decode_tracking(value: Any) -> TrackingNumber | None:
    if not isinstance(value, dict) or not isinstance(value.get("number"), str):
        return None
    carriers = tuple(Carrier(c) for c in value.get("carriers", []) if c in set(Carrier))
    if not carriers:
        return None
    return TrackingNumber(
        number=value["number"], carriers=carriers, forced=bool(value.get("forced"))
    )


_KNOWN_KEYS = {"uid", "summary", "notes", "status", "due", "completed", "tracking"}


def _encode_package(package: Package) -> dict[str, Any]:
    return {
        # Keys a newer version wrote are kept, so a rollback followed by an
        # upgrade loses nothing.
        **package.extra,
        "uid": package.uid,
        "summary": package.summary,
        "notes": package.notes,
        "status": str(package.status),
        "due": _encode_due(package.due),
        "completed": _encode_due(package.completed),
        "tracking": _encode_tracking(package),
    }


def _decode_package(data: dict[str, Any]) -> Package | None:
    uid, summary = data.get("uid"), data.get("summary")
    if not isinstance(uid, str) or not isinstance(summary, str):
        return None
    status = (
        TodoItemStatus.COMPLETED
        if data.get("status") == TodoItemStatus.COMPLETED
        else TodoItemStatus.NEEDS_ACTION
    )
    completed = _decode_due(data.get("completed"))
    notes = data.get("notes")
    return Package(
        uid=uid,
        summary=summary,
        notes=notes if isinstance(notes, str) and notes else None,
        status=status,
        due=_decode_due(data.get("due")),
        completed=completed if isinstance(completed, dt.datetime) else None,
        tracking=_decode_tracking(tracking := data.get("tracking")),
        poll=_decode_poll(tracking.get("poll") if isinstance(tracking, dict) else None),
        tracking_raw=tracking if isinstance(tracking, dict) else None,
        extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
    )


class _PackageStore(Store[dict[str, Any]]):
    """The HA ``Store``, with a migration hook for future schema versions."""

    @override
    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        # No migrations yet. Minor versions only add keys; see the module
        # docstring.
        return old_data


def _tracking_for(summary: str, notes: str | None) -> TrackingNumber | None:
    """Look for a number in the summary first, then in the notes."""
    return find_tracking_number(summary) or find_tracking_number(notes)


class PackageList:
    """The packages, in list order, and their storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create the list; call ``async_load`` before use."""
        self._store = _PackageStore(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry_id}",
            minor_version=STORAGE_MINOR_VERSION,
        )
        self._packages: list[Package] = []
        self._extra: dict[str, Any] = {}

    def __iter__(self) -> Iterator[Package]:
        """Iterate over packages in list order."""
        return iter(self._packages)

    def __contains__(self, package: object) -> bool:
        """Whether ``package`` (the object, not a copy) is still on the list."""
        return any(p is package for p in self._packages)

    def get(self, uid: str) -> Package:
        """Return one package, or raise if it's gone."""
        for package in self._packages:
            if package.uid == uid:
                return package
        raise HomeAssistantError(f"Package {uid!r} not found")

    async def async_load(self) -> None:
        """Read stored packages."""
        data = await self._store.async_load() or {}
        items = data.get("items", [])
        self._extra = {k: v for k, v in data.items() if k != "items"}
        self._packages = [
            package
            for raw in items
            if isinstance(raw, dict) and (package := _decode_package(raw)) is not None
        ]
        if len(self._packages) != len(items):
            _LOGGER.warning(
                "Skipped %d unreadable stored packages",
                len(items) - len(self._packages),
            )

    async def async_save(self) -> None:
        """Write all packages."""
        await self._store.async_save(
            {**self._extra, "items": [_encode_package(p) for p in self._packages]}
        )

    async def async_remove(self) -> None:
        """Delete the stored data (when the config entry is removed)."""
        await self._store.async_remove()

    async def async_create(self, item: TodoItem) -> Package:
        """Add a package from a new to-do item."""
        summary = item.summary or ""
        notes = notes_from_description(item.description, None)
        package = Package(
            uid=ulid_util.ulid_now(),
            summary=summary,
            notes=notes,
            due=item.due,
            tracking=_tracking_for(summary, notes),
        )
        self._set_status(package, item.status or TodoItemStatus.NEEDS_ACTION)
        self._packages.append(package)
        await self.async_save()
        return package

    async def async_update(self, item: TodoItem) -> Package:
        """Apply an edit from HA to a package."""
        if item.uid is None:
            raise HomeAssistantError("Item has no uid")
        package = self.get(item.uid)
        package.summary = item.summary or package.summary
        package.notes = notes_from_description(item.description, package)
        package.due = item.due
        package.set_tracking(_tracking_for(package.summary, package.notes))
        self._set_status(package, item.status or package.status)
        await self.async_save()
        return package

    async def async_delete(self, uids: Iterable[str]) -> None:
        """Remove packages."""
        remove = set(uids)
        self._packages = [p for p in self._packages if p.uid not in remove]
        await self.async_save()

    async def async_move(self, uid: str, previous_uid: str | None) -> None:
        """Move a package to just after ``previous_uid`` (None: to the top)."""
        if uid == previous_uid:
            return
        package = self.get(uid)
        if previous_uid is not None:
            self.get(previous_uid)
        self._packages.remove(package)
        index = 0
        if previous_uid is not None:
            index = (
                next(i for i, p in enumerate(self._packages) if p.uid == previous_uid)
                + 1
            )
        self._packages.insert(index, package)
        await self.async_save()

    @staticmethod
    def _set_status(package: Package, status: TodoItemStatus) -> None:
        """Set completion; a completed item records when it was checked off."""
        status = TodoItemStatus(status)
        if status == package.status and (
            status != TodoItemStatus.COMPLETED or package.completed is not None
        ):
            return
        package.status = status
        package.completed = (
            dt_util.utcnow() if status == TodoItemStatus.COMPLETED else None
        )
