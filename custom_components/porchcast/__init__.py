"""Porchcast: track UPS, FedEx and USPS packages on a Home Assistant to-do list."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .store import PackageList

PLATFORMS: list[Platform] = [Platform.TODO]

type PorchcastConfigEntry = ConfigEntry[PackageList]


async def async_setup_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> bool:
    """Set up Porchcast from a config entry."""
    packages = PackageList(hass, entry.entry_id)
    await packages.async_load()
    entry.runtime_data = packages
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: PorchcastConfigEntry) -> None:
    """Delete stored packages when the integration is removed."""
    await PackageList(hass, entry.entry_id).async_remove()
