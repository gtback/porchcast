"""Tests for polling: scheduling, due dates, events, errors and backoff.

Each test runs a real entry with UPS credentials against mocked UPS endpoints.
The ``hass`` fixture's time zone is US/Pacific; UPS fixture times are read in
it too.
"""

import datetime as dt
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.todo import TodoItemStatus
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.porchcast.const import (
    DOMAIN,
    EVENT_DELIVERED,
    EVENT_ETA_CHANGED,
    EVENT_STATUS_CHANGED,
    NAME,
    Carrier,
)
from custom_components.porchcast.coordinator import (
    PorchcastCoordinator,
    auth_failed_line,
    failing_line,
    not_found_line,
)
from custom_components.porchcast.store import Package
from custom_components.porchcast.tracking import TrackingNumber

from .common import UPS_DATA, UPS_NUMBER, UPS_TOKEN_URL, UPS_TRACK_URL, fixture

ENTITY_ID = "todo.porchcast_packages"
START = dt.datetime(2026, 11, 21, 17, 0, tzinfo=dt.UTC)  # 9 am Pacific
OTHER_NUMBER = "1Z12345E0205271686"
OTHER_URL = f"https://onlinetools.ups.com/api/track/v1/details/{OTHER_NUMBER}"


@pytest.fixture
async def entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> MockConfigEntry:
    """A loaded entry with UPS credentials, at a fixed time."""
    freezer.move_to(START)
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, entry_id="entry1", data=UPS_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _ups(
    aioclient_mock: AiohttpClientMocker,
    name: str | None = None,
    *,
    status: int = 200,
    url: str = UPS_TRACK_URL,
    **kwargs: Any,
) -> None:
    """Answer UPS tracking requests for ``url`` with a fixture (replacing any)."""
    aioclient_mock._mocks = [m for m in aioclient_mock._mocks if str(m._url) != url]
    aioclient_mock.get(
        url, status=status, json=fixture(f"ups/{name}") if name else None, **kwargs
    )


def _track_calls(aioclient_mock: AiohttpClientMocker, url: str = UPS_TRACK_URL) -> int:
    return sum(
        1
        for method, called, *_ in aioclient_mock.mock_calls
        if method.lower() == "get" and str(called).split("?")[0] == url
    )


def _coordinator(entry: MockConfigEntry) -> PorchcastCoordinator:
    coordinator = entry.runtime_data.coordinator
    assert isinstance(coordinator, PorchcastCoordinator)
    return coordinator


def _package(entry: MockConfigEntry, index: int = 0) -> Package:
    package = list(entry.runtime_data.packages)[index]
    assert isinstance(package, Package)
    return package


async def _call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(
        "todo", service, data, target={"entity_id": ENTITY_ID}, blocking=True
    )
    await hass.async_block_till_done()


async def _items(hass: HomeAssistant) -> list[dict[str, Any]]:
    result = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": ENTITY_ID},
        blocking=True,
        return_response=True,
    )
    items = result[ENTITY_ID]["items"]  # type: ignore[index]
    assert isinstance(items, list)
    return items


async def _later(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    delta: dt.timedelta,
) -> None:
    """Move the clock and run a coordinator pass."""
    freezer.tick(delta)
    await _coordinator(entry).async_refresh()
    await hass.async_block_till_done()


async def test_new_item_is_polled_and_gets_eta(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Adding an item polls UPS at once; the ETA becomes the due date."""
    _ups(aioclient_mock, "in_transit")
    eta_events = async_capture_events(hass, EVENT_ETA_CHANGED)
    status_events = async_capture_events(hass, EVENT_STATUS_CHANGED)

    await _call(hass, "add_item", item=f"Bike rack, REI {UPS_NUMBER}")

    [item] = await _items(hass)
    assert item["due"] == "2026-11-24"
    assert item["description"].splitlines()[1:] == [
        f"UPS {UPS_NUMBER}",
        "Status: In transit",
        "Expected Nov 24",
        "Last scan: Departed from Facility, Louisville, KY, Nov 21, 1:05 am",
        "Checked Nov 21, 9 am",
    ]
    [eta] = eta_events
    assert eta.data == {
        "uid": item["uid"],
        "summary": f"Bike rack, REI {UPS_NUMBER}",
        "carrier": "ups",
        "tracking_number": UPS_NUMBER,
        "old_eta_start": None,
        "old_eta_end": None,
        "new_eta_start": "2026-11-24",
        "new_eta_end": "2026-11-24",
        "status": "in_transit",
    }
    [status] = status_events
    assert status.data["old_status"] is None
    assert status.data["new_status"] == "in_transit"
    assert status.data["description"] == "Departed from Facility"


async def test_polls_on_schedule_and_fires_on_change_only(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """In transit polls every 2 h; events fire only when something changes."""
    _ups(aioclient_mock, "in_transit")
    await _call(hass, "add_item", item=UPS_NUMBER)
    eta_events = async_capture_events(hass, EVENT_ETA_CHANGED)
    status_events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    assert _track_calls(aioclient_mock) == 1

    await _later(hass, entry, freezer, dt.timedelta(hours=1, minutes=59))
    assert _track_calls(aioclient_mock) == 1
    await _later(hass, entry, freezer, dt.timedelta(minutes=1))
    assert _track_calls(aioclient_mock) == 2
    assert eta_events == status_events == []

    _ups(aioclient_mock, "rescheduled")
    await _later(hass, entry, freezer, dt.timedelta(hours=2))
    [eta] = eta_events
    [status] = status_events
    assert eta.data["old_eta_end"] == "2026-11-24"
    assert eta.data["new_eta_end"] == "2026-11-25"
    assert status.data["old_status"] == "in_transit"
    assert status.data["new_status"] == "exception"
    [item] = await _items(hass)
    assert item["due"] == "2026-11-25"


async def test_coordinator_ticks_by_itself(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """The 15-minute tick polls packages that are due, with no prompting."""
    _ups(aioclient_mock, "out_for_delivery")
    await _call(hass, "add_item", item=UPS_NUMBER)
    assert _track_calls(aioclient_mock) == 1
    for _ in range(2):
        freezer.tick(dt.timedelta(minutes=15))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    # Out for delivery polls every 20 minutes: the 30-minute tick is the next.
    assert _track_calls(aioclient_mock) == 2


async def test_out_for_delivery_window_sets_due_datetime(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """A window sets the due datetime to its end, and the block shows it all."""
    _ups(aioclient_mock, "out_for_delivery")
    await _call(hass, "add_item", item=UPS_NUMBER)
    [item] = await _items(hass)
    assert dt.datetime.fromisoformat(item["due"]) == dt.datetime(
        2026, 11, 25, 2, tzinfo=dt.UTC
    )
    assert "Expected Nov 24, 2-6 pm" in item["description"]
    package = _package(entry)
    assert package.poll.next_poll == START + dt.timedelta(minutes=20)


async def test_typed_due_date_kept_until_estimate(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A due date the user typed stays until UPS gives one; then UPS's wins."""
    _ups(aioclient_mock, "label_created")
    await _call(hass, "add_item", item=UPS_NUMBER, due_date="2026-12-01")
    [item] = await _items(hass)
    assert item["due"] == "2026-12-01"
    assert "Status: Label created" in item["description"]
    assert _package(entry).poll.next_poll == START + dt.timedelta(hours=6)

    _ups(aioclient_mock, "in_transit")
    await _later(hass, entry, freezer, dt.timedelta(hours=6))
    [item] = await _items(hass)
    assert item["due"] == "2026-11-24"

    # A later edit to the due date is overwritten by the next poll.
    await _call(hass, "update_item", item=item["uid"], due_date="2026-12-05")
    await _later(hass, entry, freezer, dt.timedelta(hours=2))
    [item] = await _items(hass)
    assert item["due"] == "2026-11-24"


async def test_delivered_completes_item_and_stops_polling(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Delivery checks the item off, fires once, and ends polling."""
    _ups(aioclient_mock, "out_for_delivery")
    await _call(hass, "add_item", item=UPS_NUMBER)
    delivered = async_capture_events(hass, EVENT_DELIVERED)

    _ups(aioclient_mock, "delivered")
    await _later(hass, entry, freezer, dt.timedelta(minutes=20))
    [item] = await _items(hass)
    assert item["status"] == TodoItemStatus.COMPLETED
    # The ETA stays the due date; the block says when and where it was left.
    assert "Delivered Nov 24, 3:10 pm, Front Door" in item["description"]
    assert "Expected" not in item["description"]
    [event] = delivered
    assert event.data["delivered_at"] == "2026-11-24T15:10:00-08:00"
    assert event.data["location"] == "Front Door"

    calls = _track_calls(aioclient_mock)
    await _later(hass, entry, freezer, dt.timedelta(days=1))
    assert _track_calls(aioclient_mock) == calls

    # Unchecking a delivered item doesn't restart polling or fire again.
    await _call(hass, "update_item", item=item["uid"], status="needs_action")
    await _later(hass, entry, freezer, dt.timedelta(days=1))
    assert _track_calls(aioclient_mock) == calls
    assert len(delivered) == 1


async def test_manual_complete_pauses_polling(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Checking an item off stops polling; unchecking resumes it."""
    _ups(aioclient_mock, "in_transit")
    await _call(hass, "add_item", item=UPS_NUMBER)
    [item] = await _items(hass)
    await _call(hass, "update_item", item=item["uid"], status="completed")

    await _later(hass, entry, freezer, dt.timedelta(hours=3))
    assert _track_calls(aioclient_mock) == 1

    await _call(hass, "update_item", item=item["uid"], status="needs_action")
    await _later(hass, entry, freezer, dt.timedelta(seconds=1))
    assert _track_calls(aioclient_mock) == 2


async def test_new_number_resets_poll_state(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Changing the number polls the new one at once, from a clean slate."""
    _ups(aioclient_mock, "in_transit")
    _ups(aioclient_mock, "label_created", url=OTHER_URL)
    await _call(hass, "add_item", item=UPS_NUMBER)
    [item] = await _items(hass)
    assert _package(entry).poll.status == "in_transit"

    # The debouncer delays a second refresh; run it now.
    await _call(hass, "update_item", item=item["uid"], rename=f"Rack {OTHER_NUMBER}")
    await _coordinator(entry).async_refresh()
    await hass.async_block_till_done()
    assert _track_calls(aioclient_mock, OTHER_URL) == 1
    package = _package(entry)
    assert package.poll.status == "pre_transit"
    assert package.poll.eta is None


async def test_not_found(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """An unknown number says so and is asked about again in 6 h."""
    _ups(aioclient_mock, "not_found", status=404)
    await _call(hass, "add_item", item=UPS_NUMBER)
    [item] = await _items(hass)
    assert not_found_line((Carrier.UPS,)) in item["description"]
    assert _package(entry).poll.next_poll == START + dt.timedelta(hours=6)


async def test_repeated_failures_are_reported(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Failures retry soon; after five in a row the block says so."""
    _ups(aioclient_mock, "in_transit")
    await _call(hass, "add_item", item=UPS_NUMBER)
    _ups(aioclient_mock, status=500)

    for failures in range(1, 6):
        # Past both the 2 h in-transit interval and the carrier backoff.
        await _later(hass, entry, freezer, dt.timedelta(hours=2, minutes=1))
        assert _package(entry).poll.failures == failures
    [item] = await _items(hass)
    assert failing_line((Carrier.UPS,), 5) in item["description"]
    # Still shows what UPS said last.
    assert "Status: In transit" in item["description"]
    package = _package(entry)
    assert package.poll.next_poll == dt_now() + dt.timedelta(hours=6)

    _ups(aioclient_mock, "in_transit")
    await _later(hass, entry, freezer, dt.timedelta(hours=6))
    assert _package(entry).poll.failures == 0
    [item] = await _items(hass)
    assert "tries in a row" not in item["description"]


def dt_now() -> dt.datetime:
    """The frozen time."""
    return dt.datetime.now(dt.UTC)


async def test_carrier_backoff(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """After an outage or 429, the carrier is left alone for a while."""
    _ups(aioclient_mock, status=503)
    _ups(aioclient_mock, status=503, url=OTHER_URL)
    await _call(hass, "add_item", item=UPS_NUMBER)
    await _call(hass, "add_item", item=OTHER_NUMBER)
    await _coordinator(entry).async_refresh()
    # The second package wasn't tried: UPS is backed off for 15 minutes.
    assert _track_calls(aioclient_mock) == 1
    assert _track_calls(aioclient_mock, OTHER_URL) == 0

    await _later(hass, entry, freezer, dt.timedelta(minutes=14))
    assert _track_calls(aioclient_mock) == 1
    # 15 min later: the first package's retry isn't due (30 min), the second is.
    await _later(hass, entry, freezer, dt.timedelta(minutes=1))
    assert _track_calls(aioclient_mock, OTHER_URL) == 1
    # Second failure: 30 minutes of backoff.
    await _later(hass, entry, freezer, dt.timedelta(minutes=29))
    assert _track_calls(aioclient_mock) == 1

    _ups(aioclient_mock, "in_transit", status=429, headers={"Retry-After": "3600"})
    await _later(hass, entry, freezer, dt.timedelta(minutes=1))
    assert _track_calls(aioclient_mock) == 2
    await _later(hass, entry, freezer, dt.timedelta(minutes=59))
    assert _track_calls(aioclient_mock, OTHER_URL) == 1  # still backed off
    _ups(aioclient_mock, "in_transit")
    _ups(aioclient_mock, "in_transit", url=OTHER_URL)
    await _later(hass, entry, freezer, dt.timedelta(minutes=1))
    assert _package(entry).poll.status == "in_transit"
    assert _package(entry, 1).poll.status == "in_transit"


async def test_auth_failure_starts_reauth(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Rejected credentials start reauth and stop polling that carrier."""
    _ups(aioclient_mock, status=403)
    await _call(hass, "add_item", item=UPS_NUMBER)
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["source"] == SOURCE_REAUTH
    [item] = await _items(hass)
    assert auth_failed_line(Carrier.UPS) in item["description"]
    assert _package(entry).poll.failures == 0

    await _later(hass, entry, freezer, dt.timedelta(hours=7))
    assert _track_calls(aioclient_mock) == 1


async def test_item_deleted_during_poll(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """A result for an item that was deleted meanwhile is dropped quietly."""
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _call(hass, "add_item", item="No number yet")
    packages = entry.runtime_data.packages
    package = _package(entry)
    package.set_tracking(TrackingNumber(UPS_NUMBER, (Carrier.UPS,)))
    await packages.async_delete([package.uid])

    _ups(aioclient_mock, "in_transit")
    poll = _coordinator(entry)._async_poll
    assert await poll(package, START) is False
    assert _track_calls(aioclient_mock) == 1
    await hass.async_block_till_done()
    assert events == []
