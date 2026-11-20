"""Tests for the Porchcast config, reconfigure and reauth flows."""

from typing import Any

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.porchcast.const import DOMAIN, NAME

from .common import UPS_DATA, UPS_TOKEN_URL, fixture

ENTITY_ID = "todo.porchcast_packages"


def _form(
    client_id: str = "", secret: str = "", sandbox: bool = False
) -> dict[str, Any]:
    return {
        "ups": {"client_id": client_id, "client_secret": secret, "sandbox": sandbox}
    }


async def test_config_flow_creates_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Valid UPS credentials create the entry and the Packages list."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _form(" id ", "secret")
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == UPS_DATA
    assert hass.states.get(ENTITY_ID) is not None


@pytest.mark.parametrize(
    ("form", "token_status", "error"),
    [
        (_form(), 200, "no_carrier"),
        (_form("id"), 200, "incomplete"),
        (_form(secret="secret"), 200, "incomplete"),
        (_form("id", "bad"), 401, "invalid_auth"),
        (_form("id", "secret"), 503, "cannot_connect"),
    ],
)
async def test_config_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    form: dict[str, Any],
    token_status: int,
    error: str,
) -> None:
    """Bad input shows the form again with an error; it can then succeed."""
    aioclient_mock.post(UPS_TOKEN_URL, status=token_status, json=fixture("ups/token"))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _form("id", "secret")
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_single_instance(hass: HomeAssistant) -> None:
    """A second setup attempt aborts."""
    MockConfigEntry(domain=DOMAIN, title=NAME).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_entry_without_credentials_loads(hass: HomeAssistant) -> None:
    """An entry made by 0.2.0 (no credentials) still loads."""
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, data={}, version=1)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_reconfigure_adds_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Reconfigure adds credentials to an entry that has none, and reloads."""
    aioclient_mock.post(
        "https://wwwcie.ups.com/security/v1/oauth/token", json=fixture("ups/token")
    )
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _form("id", "secret", sandbox=True)
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {
        "ups": {"client_id": "id", "client_secret": "secret", "sandbox": True}
    }
    assert entry.state is ConfigEntryState.LOADED


async def test_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """Reauth asks for new credentials and stores them."""
    aioclient_mock.post(UPS_TOKEN_URL, json=fixture("ups/token"))
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, data=UPS_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _form("id", "new-secret")
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["ups"]["client_secret"] == "new-secret"
