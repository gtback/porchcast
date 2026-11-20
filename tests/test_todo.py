"""Tests for the Packages to-do list: setup, item changes and persistence."""

import datetime as dt
from typing import Any

from homeassistant.components.todo import TodoItemStatus
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porchcast.const import DOMAIN, NAME
from custom_components.porchcast.store import NO_NUMBER_LINE, SEPARATOR

ENTITY_ID = "todo.porchcast_packages"
UPS = "1Z999AA10123456784"


@pytest.fixture
async def entry(hass: HomeAssistant) -> MockConfigEntry:
    """A loaded Porchcast entry."""
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, entry_id="entry1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass: HomeAssistant, service: str, **data: Any) -> None:
    await hass.services.async_call(
        "todo", service, data, target={"entity_id": ENTITY_ID}, blocking=True
    )


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


async def test_setup_shows_empty_packages_list(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Setting up the entry creates an empty Packages list; unloading works."""
    assert entry.state is ConfigEntryState.LOADED
    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0"
    assert state.attributes["friendly_name"] == "Porchcast Packages"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_add_item_finds_tracking_number(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A new item gets the status block under its notes."""
    await _call(
        hass,
        "add_item",
        item=f"Bike rack, REI {UPS}",
        description="Roof rack, order 42",
    )
    [item] = await _items(hass)
    assert item["summary"] == f"Bike rack, REI {UPS}"
    assert item["status"] == TodoItemStatus.NEEDS_ACTION
    assert item["description"] == (
        f"Roof rack, order 42\n\n{SEPARATOR}\nUPS {UPS}\nStatus: not checked yet"
    )
    assert hass.states.get(ENTITY_ID).state == "1"  # type: ignore[union-attr]


async def test_add_item_without_number(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """No number: the item is kept and says so."""
    await _call(hass, "add_item", item="Something from grandma")
    [item] = await _items(hass)
    assert item["description"] == f"{SEPARATOR}\n{NO_NUMBER_LINE}"


async def test_number_in_notes(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """A number pasted into the notes is found too."""
    await _call(hass, "add_item", item="Bike rack", description=f"Tracking {UPS}")
    [item] = await _items(hass)
    assert f"UPS {UPS}" in item["description"]


async def test_editing_keeps_notes_and_status(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Edits change only the notes; the status block is re-rendered."""
    await _call(hass, "add_item", item=f"Rack {UPS}", description="old notes")
    [item] = await _items(hass)

    # The UI sends the whole description back, with the user's change on top.
    edited = item["description"].replace("old notes", "new notes")
    await _call(hass, "update_item", item=item["uid"], description=edited)
    [item] = await _items(hass)
    assert item["description"] == (
        f"new notes\n\n{SEPARATOR}\nUPS {UPS}\nStatus: not checked yet"
    )

    # Renaming alone keeps the notes.
    await _call(hass, "update_item", item=item["uid"], rename=f"Roof rack {UPS}")
    [item] = await _items(hass)
    assert item["summary"] == f"Roof rack {UPS}"
    assert item["description"].startswith("new notes\n\n")

    # Clearing the description clears the notes, not the status block.
    await _call(hass, "update_item", item=item["uid"], description=None)
    [item] = await _items(hass)
    assert item["description"] == f"{SEPARATOR}\nUPS {UPS}\nStatus: not checked yet"


async def test_rename_changes_tracking_number(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """A new number in the text replaces the old one."""
    await _call(hass, "add_item", item="Desk")
    await _call(hass, "update_item", item="Desk", rename="Desk 123456789012")
    [item] = await _items(hass)
    assert "FedEx 123456789012" in item["description"]


async def test_due_dates(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Due date and datetime can be set and cleared."""
    await _call(hass, "add_item", item="Desk", due_date="2026-11-24")
    [item] = await _items(hass)
    assert item["due"] == "2026-11-24"

    await _call(hass, "update_item", item="Desk", due_datetime="2026-11-24 09:00:00")
    [item] = await _items(hass)
    assert item["due"].startswith("2026-11-24T09:00:00")

    await _call(hass, "update_item", item="Desk", due_date=None)
    [item] = await _items(hass)
    assert "due" not in item


async def test_complete_and_uncheck(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Checking an item off records when; unchecking clears it."""
    await _call(hass, "add_item", item="Desk")
    await _call(hass, "update_item", item="Desk", status="completed")
    [item] = await _items(hass)
    assert item["status"] == TodoItemStatus.COMPLETED
    assert "completed" in item
    assert hass.states.get(ENTITY_ID).state == "0"  # type: ignore[union-attr]
    first_completed = item["completed"]

    # Another edit while completed keeps the original time.
    await _call(hass, "update_item", item="Desk", rename="Big desk")
    [item] = await _items(hass)
    assert item["completed"] == first_completed

    await _call(hass, "update_item", item="Big desk", status="needs_action")
    [item] = await _items(hass)
    assert item["status"] == TodoItemStatus.NEEDS_ACTION
    assert "completed" not in item


async def test_delete_and_remove_completed(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Items can be removed one at a time or all completed at once."""
    for name in ("A", "B", "C"):
        await _call(hass, "add_item", item=name)
    await _call(hass, "remove_item", item="B")
    await _call(hass, "update_item", item="C", status="completed")
    await _call(hass, "remove_completed_items")
    assert [i["summary"] for i in await _items(hass)] == ["A"]


async def test_move(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Items can be reordered."""
    for name in ("A", "B", "C"):
        await _call(hass, "add_item", item=name)
    uids = {i["summary"]: i["uid"] for i in await _items(hass)}
    packages = entry.runtime_data

    await packages.async_move(uids["C"], None)
    await packages.async_move(uids["A"], uids["B"])
    await packages.async_move(uids["A"], uids["A"])
    assert [p.summary for p in packages] == ["C", "B", "A"]

    with pytest.raises(HomeAssistantError):
        await packages.async_move("missing", None)
    with pytest.raises(HomeAssistantError):
        await packages.async_move(uids["A"], "missing")


async def test_items_survive_reload(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Items, notes, due dates and completion are stored and reloaded."""
    await _call(hass, "add_item", item=f"Rack {UPS}", description="notes")
    await _call(hass, "add_item", item="Desk", due_date="2026-11-24")
    await _call(hass, "update_item", item="Desk", status="completed")
    before = await _items(hass)

    stored = hass_storage["porchcast.entry1"]
    assert stored["version"] == 1
    assert [i["summary"] for i in stored["data"]["items"]] == [f"Rack {UPS}", "Desk"]

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert await _items(hass) == before


async def test_loads_newer_minor_version(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """After a rollback, data from a newer minor version loads, keeping its keys."""
    hass_storage["porchcast.entry1"] = {
        "version": 1,
        "minor_version": 7,
        "key": "porchcast.entry1",
        "data": {
            "future": True,
            "items": [
                {
                    "uid": "u1",
                    "summary": f"Rack {UPS}",
                    "notes": "notes",
                    "status": "needs_action",
                    "due": "2026-11-24",
                    "completed": None,
                    "tracking": {
                        "number": UPS,
                        "carriers": ["ups", "dhl"],
                        "forced": False,
                        "poll": {"next": "2026-11-24T10:00:00+00:00"},
                    },
                    "poll": {"failures": 2},
                },
                "not a dict",
            ],
        },
    }
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, entry_id="entry1")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    [item] = await _items(hass)
    assert item["uid"] == "u1"
    assert item["due"] == "2026-11-24"
    assert item["description"].startswith("notes\n\n")

    await _call(hass, "update_item", item="u1", rename=f"Roof rack {UPS}")
    data = hass_storage["porchcast.entry1"]["data"]
    assert data["future"] is True
    assert data["items"][0]["poll"] == {"failures": 2}
    assert data["items"][0]["tracking"]["carriers"] == ["ups", "dhl"]
    assert data["items"][0]["tracking"]["poll"] == {"next": "2026-11-24T10:00:00+00:00"}


async def test_remove_entry_deletes_storage(
    hass: HomeAssistant, entry: MockConfigEntry, hass_storage: dict[str, Any]
) -> None:
    """Removing the integration deletes its stored packages."""
    await _call(hass, "add_item", item="Desk")
    assert "porchcast.entry1" in hass_storage
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert "porchcast.entry1" not in hass_storage


async def test_due_datetime_is_aware(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Datetimes are stored with their time zone."""
    await _call(hass, "add_item", item="Desk", due_datetime="2026-11-24 09:00:00")
    [package] = entry.runtime_data
    assert isinstance(package.due, dt.datetime)
    assert package.due.tzinfo is not None
