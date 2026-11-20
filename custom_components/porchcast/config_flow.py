"""Config flow for Porchcast: carrier credentials, with reconfigure and reauth.

The entry's data holds one key per configured carrier (``"ups"``), each with a
client ID, client secret and sandbox flag. Every carrier is optional, but at
least one is needed to set up. Credentials are checked by fetching a token.

An entry made by 0.1.0 or 0.2.0 has no credentials; it still loads, and the
user adds them with Reconfigure.
"""

from collections.abc import Mapping
import logging
from typing import Any, override

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import probatio

from . import build_clients
from .carriers.base import AuthError, CarrierError
from .const import (
    CARRIER_NAMES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SANDBOX,
    DOMAIN,
    NAME,
    Carrier,
)

_LOGGER = logging.getLogger(__name__)

# Carriers with a client so far, in form order.
CARRIERS: tuple[Carrier, ...] = (Carrier.UPS,)


def _carrier_schema() -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Optional(CONF_CLIENT_ID): str,
            probatio.Optional(CONF_CLIENT_SECRET): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            probatio.Optional(CONF_SANDBOX, default=False): bool,
        }
    )


CREDENTIALS_SCHEMA = probatio.Schema(
    {
        probatio.Required(str(carrier)): section(
            _carrier_schema(), {"collapsed": False}
        )
        for carrier in CARRIERS
    }
)


class PorchcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Porchcast."""

    # Stays 1: credentials were added without breaking 0.2.0's entries, and a
    # higher major version would stop an older Porchcast from loading the entry
    # after a rollback.
    VERSION = 1

    async def _async_check(
        self, user_input: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
        """Return (entry data, errors, description placeholders)."""
        data: dict[str, Any] = {}
        for carrier in CARRIERS:
            fields = user_input.get(carrier) or {}
            client_id = (fields.get(CONF_CLIENT_ID) or "").strip()
            secret = (fields.get(CONF_CLIENT_SECRET) or "").strip()
            if not client_id and not secret:
                continue
            name = {"carrier": CARRIER_NAMES[carrier]}
            if not client_id or not secret:
                return {}, {"base": "incomplete"}, name
            data[carrier] = {
                CONF_CLIENT_ID: client_id,
                CONF_CLIENT_SECRET: secret,
                CONF_SANDBOX: bool(fields.get(CONF_SANDBOX)),
            }
            client = build_clients(self.hass, {carrier: data[carrier]})[carrier]
            try:
                await client.async_validate()
            except AuthError:
                return {}, {"base": "invalid_auth"}, name
            except CarrierError as err:
                _LOGGER.warning(
                    "Couldn't check %s credentials: %s", CARRIER_NAMES[carrier], err
                )
                return {}, {"base": "cannot_connect"}, name
        if not data:
            return {}, {"base": "no_carrier"}, {}
        return data, {}, {}

    async def _async_credentials_step(
        self,
        step_id: str,
        user_input: dict[str, Any] | None,
        current: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, ConfigFlowResult | None]:
        """Show the form, or return checked entry data once it's valid."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            data, errors, placeholders = await self._async_check(user_input)
            if not errors:
                return data, None
        schema = self.add_suggested_values_to_schema(
            CREDENTIALS_SCHEMA, user_input if user_input is not None else current
        )
        return None, self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=errors,
            description_placeholders=placeholders,
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for carrier credentials and create the entry."""
        data, form = await self._async_credentials_step("user", user_input, None)
        if form is not None:
            return form
        return self.async_create_entry(title=NAME, data=data or {})

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change carrier credentials."""
        entry = self._get_reconfigure_entry()
        data, form = await self._async_credentials_step(
            "reconfigure", user_input, entry.data
        )
        if form is not None:
            return form
        return self.async_update_reload_and_abort(entry, data=data or {})

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """A carrier rejected its credentials."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials."""
        entry = self._get_reauth_entry()
        data, form = await self._async_credentials_step(
            "reauth_confirm", user_input, entry.data
        )
        if form is not None:
            return form
        return self.async_update_reload_and_abort(entry, data=data or {})
