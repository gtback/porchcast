"""Tests for setting up Porchcast and its Packages to-do list."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porchcast.const import DOMAIN, NAME

ENTITY_ID = "todo.porchcast_packages"


async def test_setup_shows_empty_packages_list(hass: HomeAssistant) -> None:
    """Setting up the entry creates an empty Packages list; unloading works."""
    entry = MockConfigEntry(domain=DOMAIN, title=NAME)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    state = hass.states.get(ENTITY_ID)
    assert state is not None
    assert state.state == "0"
    assert state.attributes["friendly_name"] == "Porchcast Packages"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
