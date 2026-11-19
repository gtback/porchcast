"""To-do list platform for Porchcast."""

from homeassistant.components.todo import TodoItem, TodoListEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PorchcastConfigEntry
from .const import DOMAIN, NAME, TODO_LIST_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PorchcastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Packages to-do list."""
    async_add_entities([PackagesTodoListEntity(entry)])


class PackagesTodoListEntity(TodoListEntity):
    """The Packages to-do list. Items are packages being tracked."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: PorchcastConfigEntry) -> None:
        """Initialize the entity."""
        self._attr_unique_id = f"{entry.entry_id}_packages"
        self._attr_name = TODO_LIST_NAME
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_todo_items: list[TodoItem] = []
