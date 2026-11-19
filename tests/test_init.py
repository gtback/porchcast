"""Tests for setting up Porchcast and its config flow."""

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.porchcast.const import DOMAIN, NAME

ENTITY_ID = "todo.porchcast_packages"


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    """The user step shows a confirm form, then creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert hass.states.get(ENTITY_ID) is not None


async def test_single_instance(hass: HomeAssistant) -> None:
    """A second setup attempt aborts."""
    MockConfigEntry(domain=DOMAIN, title=NAME).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


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
