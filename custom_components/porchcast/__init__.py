"""Porchcast: track UPS, FedEx and USPS packages on a Home Assistant to-do list."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .carriers.base import CarrierClient
from .carriers.ups import UpsClient
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_SANDBOX, Carrier
from .coordinator import PorchcastCoordinator
from .store import PackageList

PLATFORMS: list[Platform] = [Platform.TODO]


@dataclass(slots=True)
class PorchcastData:
    """What a loaded entry holds."""

    packages: PackageList
    coordinator: PorchcastCoordinator


type PorchcastConfigEntry = ConfigEntry[PorchcastData]


def build_clients(
    hass: HomeAssistant, data: Mapping[str, Any]
) -> dict[Carrier, CarrierClient]:
    """Create a client for each carrier that has credentials in ``data``."""
    clients: dict[Carrier, CarrierClient] = {}
    if ups := data.get(Carrier.UPS):
        clients[Carrier.UPS] = UpsClient(
            async_get_clientsession(hass),
            ups[CONF_CLIENT_ID],
            ups[CONF_CLIENT_SECRET],
            sandbox=bool(ups.get(CONF_SANDBOX)),
            tz=dt_util.get_default_time_zone(),
        )
    return clients


async def async_setup_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> bool:
    """Set up Porchcast from a config entry."""
    packages = PackageList(hass, entry.entry_id)
    await packages.async_load()
    coordinator = PorchcastCoordinator(
        hass, entry, packages, build_clients(hass, entry.data)
    )
    entry.runtime_data = PorchcastData(packages, coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Poll anything that's due without holding up HA's startup; after this the
    # coordinator ticks on its own.
    entry.async_create_background_task(
        hass, coordinator.async_refresh(), "porchcast first poll"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> None:
    """Delete stored packages when the integration is removed."""
    await PackageList(hass, entry.entry_id).async_remove()
