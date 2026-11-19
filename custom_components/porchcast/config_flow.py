"""Config flow for Porchcast."""

from typing import Any, override

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, NAME


class PorchcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Porchcast.

    Carrier credentials are added to this flow in later versions; for now it
    only confirms and creates the single entry.
    """

    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm setup."""
        if user_input is not None:
            return self.async_create_entry(title=NAME, data={})
        return self.async_show_form(step_id="user")
