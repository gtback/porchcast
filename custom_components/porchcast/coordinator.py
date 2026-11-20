"""The update coordinator: polls each package when it's due and fires events.

One coordinator ticks every 15 minutes. Each package has its own next-poll
time, set from its last status (see ``polling.py``). A carrier that rate-limits
us or is down is left alone for a while (backoff); a carrier whose credentials
are rejected is left alone until the user reauthenticates.
"""

import asyncio
import datetime as dt
import logging
from typing import Any, override

from homeassistant.components.todo import TodoItemStatus
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .carriers.base import (
    AuthError,
    CarrierClient,
    CarrierError,
    Eta,
    NotFoundError,
    RateLimitedError,
    RequestError,
    Status,
    TrackingResult,
)
from .const import (
    CARRIER_NAMES,
    DOMAIN,
    EVENT_DELIVERED,
    EVENT_ETA_CHANGED,
    EVENT_STATUS_CHANGED,
    Carrier,
)
from .polling import (
    MAX_FAILURES,
    TICK,
    Backoff,
    next_poll_after_failure,
    next_poll_after_success,
)
from .store import Package, PackageList

_LOGGER = logging.getLogger(__name__)


def _names(carriers: tuple[Carrier, ...]) -> str:
    return " or ".join(CARRIER_NAMES[c] for c in carriers)


def not_set_up_line(carriers: tuple[Carrier, ...]) -> str:
    """The problem line for a number whose carrier has no credentials."""
    return f"{_names(carriers)} isn't set up in Porchcast."


def auth_failed_line(carrier: Carrier) -> str:
    """The problem line while a carrier's credentials are rejected."""
    return f"{CARRIER_NAMES[carrier]} sign-in failed; reconfigure Porchcast."


def not_found_line(carriers: tuple[Carrier, ...]) -> str:
    """The problem line when no carrier knows the number (yet)."""
    return f"{_names(carriers)} has no tracking data for this number yet."


def failing_line(carriers: tuple[Carrier, ...], failures: int) -> str:
    """The problem line after MAX_FAILURES failed polls in a row."""
    return (
        f"Couldn't check with {_names(carriers)} ({failures} tries in a row); "
        "still trying."
    )


def _iso(value: dt.date | dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class PorchcastCoordinator(DataUpdateCoordinator[None]):
    """Polls packages that are due. Holds no data of its own: it updates the list."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        packages: PackageList,
        clients: dict[Carrier, CarrierClient],
    ) -> None:
        """Create the coordinator for one config entry."""
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=TICK
        )
        self.packages = packages
        self.clients = clients
        self._backoff: dict[Carrier, Backoff] = {c: Backoff() for c in clients}
        self._auth_failed: set[Carrier] = set()
        # A tick and a refresh for a new item must not poll at the same time.
        self._lock = asyncio.Lock()

    @staticmethod
    def is_due(package: Package, now: dt.datetime) -> bool:
        """Whether a package should be polled now (ignoring carrier state)."""
        poll = package.poll
        return (
            package.tracking is not None
            and package.status == TodoItemStatus.NEEDS_ACTION
            and poll.status is not Status.DELIVERED
            and (poll.next_poll is None or poll.next_poll <= now)
        )

    @override
    async def _async_update_data(self) -> None:
        """Poll every package that is due, then save."""
        async with self._lock:
            changed = False
            for package in list(self.packages):
                now = dt_util.utcnow()
                if self.is_due(package, now):
                    changed |= await self._async_poll(package, now)
            if changed:
                await self.packages.async_save()

    async def _async_poll(self, package: Package, now: dt.datetime) -> bool:
        """Ask the package's carrier(s). Return whether anything changed."""
        if (tracking := package.tracking) is None:
            return False
        poll = package.poll
        carriers = package.carriers
        available = tuple(c for c in carriers if c in self.clients)
        if not available:
            return _set_problem(package, not_set_up_line(carriers))
        if failed := next((c for c in available if c in self._auth_failed), None):
            return _set_problem(package, auth_failed_line(failed))
        if any(self._backoff[c].blocked(now) for c in available):
            return False

        result: TrackingResult | None = None
        error: CarrierError | None = None
        for carrier in available:
            try:
                result = await self.clients[carrier].async_track(tracking.number)
            except NotFoundError as err:
                _LOGGER.debug("%s: %s", CARRIER_NAMES[carrier], err)
                self._backoff[carrier].succeeded()
                continue
            except AuthError as err:
                _LOGGER.warning("%s: %s", CARRIER_NAMES[carrier], err)
                self._auth_failed.add(carrier)
                self.config_entry.async_start_reauth(self.hass)
                if package in self.packages and package.tracking is tracking:
                    _set_problem(package, auth_failed_line(carrier))
                return True
            except RequestError as err:
                # This package's problem, not the carrier's: no backoff.
                _LOGGER.warning("%s: %s", CARRIER_NAMES[carrier], err)
                error = err
                break
            except CarrierError as err:
                _LOGGER.warning("%s: %s", CARRIER_NAMES[carrier], err)
                retry_after = (
                    err.retry_after if isinstance(err, RateLimitedError) else None
                )
                self._backoff[carrier].failed(now, retry_after)
                error = err
                break
            else:
                self._backoff[carrier].succeeded()
                break

        # The user may have deleted the item, or changed its number, meanwhile.
        if package not in self.packages or package.tracking is not tracking:
            return False

        if result is not None:
            self._apply(package, result, now)
        elif error is not None:
            poll.failures += 1
            poll.next_poll = next_poll_after_failure(poll.status, poll.failures, now)
            if poll.failures >= MAX_FAILURES:
                poll.problem = failing_line(carriers, poll.failures)
        else:
            poll.failures = 0
            poll.problem = not_found_line(available)
            poll.checked = now
            poll.next_poll = next_poll_after_success(poll.status or Status.UNKNOWN, now)
        return True

    def _apply(
        self, package: Package, result: TrackingResult, now: dt.datetime
    ) -> None:
        """Record a carrier's answer, update the item and fire events."""
        poll = package.poll
        old_status, old_eta = poll.status, poll.eta

        poll.carrier = result.carrier
        poll.status = result.status
        poll.description = result.description
        poll.last_event = result.last_event or poll.last_event
        poll.delivered_at = result.delivered_at
        poll.delivered_location = result.delivered_location
        poll.checked = now
        poll.failures = 0
        poll.problem = None
        poll.next_poll = next_poll_after_success(result.status, now)
        if result.eta is not None:
            poll.eta = result.eta
        if poll.eta is not None:
            # Once known, the carrier's estimate (the latest one, kept when an
            # answer has none) replaces the due date on every poll, even one
            # the user typed. The due date is the end of the range: HA shows
            # an item as overdue once its due date passes.
            package.due = poll.eta.end

        if result.eta is not None and result.eta != old_eta:
            self._fire_eta_changed(package, old_eta, result.eta)
        if result.status is not old_status:
            self._fire(
                package,
                EVENT_STATUS_CHANGED,
                old_status=old_status,
                new_status=result.status,
                description=result.description,
            )
        if result.status is Status.DELIVERED and old_status is not Status.DELIVERED:
            package.status = TodoItemStatus.COMPLETED
            package.completed = result.delivered_at or now
            event = result.last_event
            self._fire(
                package,
                EVENT_DELIVERED,
                delivered_at=_iso(result.delivered_at),
                location=result.delivered_location or (event and event.location),
            )

    def _fire_eta_changed(self, package: Package, old: Eta | None, new: Eta) -> None:
        self._fire(
            package,
            EVENT_ETA_CHANGED,
            old_eta_start=_iso(old.start) if old else None,
            old_eta_end=_iso(old.end) if old else None,
            new_eta_start=_iso(new.start),
            new_eta_end=_iso(new.end),
            status=package.poll.status,
        )

    def _fire(self, package: Package, event_type: str, **data: Any) -> None:
        tracking = package.tracking
        carrier = package.poll.carrier
        self.hass.bus.async_fire(
            event_type,
            {
                "uid": package.uid,
                "summary": package.summary,
                "carrier": carrier,
                "tracking_number": tracking.number if tracking else None,
                **data,
            },
        )


def _set_problem(package: Package, line: str) -> bool:
    """Show why a package isn't being checked. Return whether that changed."""
    if package.poll.problem == line:
        return False
    package.poll.problem = line
    return True
