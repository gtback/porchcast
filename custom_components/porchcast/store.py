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

from .const import CARRIER_NAMES, DOMAIN, Carrier
from .tracking import TrackingNumber, find_tracking_number

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_MINOR_VERSION = 1

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
    # Stored keys this version doesn't know (written by a newer version), kept
    # so a rollback followed by an upgrade loses nothing.
    extra: dict[str, Any] = field(default_factory=dict, compare=False)
    # The stored ``tracking`` object as loaded, for the same reason.
    tracking_raw: dict[str, Any] | None = field(default=None, compare=False)

    def status_lines(self) -> list[str]:
        """Return the managed status block, one entry per line."""
        if self.tracking is None:
            return [NO_NUMBER_LINE]
        names = " or ".join(CARRIER_NAMES[c] for c in self.tracking.carriers)
        return [f"{names} {self.tracking.number}", NOT_CHECKED_LINE]

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
    return text.strip() or None


def _encode_due(value: dt.date | dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _decode_due(value: Any) -> dt.date | dt.datetime | None:
    if not isinstance(value, str):
        return None
    if "T" in value:
        return dt_util.parse_datetime(value)
    return dt_util.parse_date(value)


def _encode_tracking(tracking: TrackingNumber | None) -> dict[str, Any] | None:
    if tracking is None:
        return None
    return {
        "number": tracking.number,
        "carriers": [str(c) for c in tracking.carriers],
        "forced": tracking.forced,
    }


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
        "tracking": (
            package.tracking_raw
            if package.tracking_raw is not None
            and _decode_tracking(package.tracking_raw) == package.tracking
            else _encode_tracking(package.tracking)
        ),
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
        package.tracking = _tracking_for(package.summary, package.notes)
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
        if status == package.status and (
            status != TodoItemStatus.COMPLETED or package.completed is not None
        ):
            return
        package.status = status
        package.completed = (
            dt_util.utcnow() if status == TodoItemStatus.COMPLETED else None
        )
