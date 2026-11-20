"""To-do list platform for Porchcast."""

from typing import override

from homeassistant.components.todo import (
    TodoItem,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PorchcastConfigEntry
from .const import DOMAIN, NAME, TODO_LIST_NAME
from .coordinator import PorchcastCoordinator
from .store import Package, PackageList


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PorchcastConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Packages to-do list."""
    async_add_entities([PackagesTodoListEntity(entry)])


class PackagesTodoListEntity(CoordinatorEntity[PorchcastCoordinator], TodoListEntity):
    """The Packages to-do list. Items are packages being tracked."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, entry: PorchcastConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry.runtime_data.coordinator)
        self._packages: PackageList = entry.runtime_data.packages
        self._attr_unique_id = f"{entry.entry_id}_packages"
        self._attr_name = TODO_LIST_NAME
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            entry_type=DeviceEntryType.SERVICE,
        )
        self._refresh_items()

    def _refresh_items(self) -> None:
        self._attr_todo_items = [p.to_todo_item() for p in self._packages]

    def _async_changed(self) -> None:
        self._refresh_items()
        self.async_write_ha_state()

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """A poll changed the packages."""
        self._async_changed()

    @callback
    def _async_poll_if_due(self, package: Package) -> None:
        """Check a new or re-numbered package now, not at the next tick.

        The poll runs in a task, so adding an item doesn't wait on the carrier.
        """
        if self.coordinator.is_due(package, dt_util.utcnow()):
            self.coordinator.config_entry.async_create_task(
                self.hass,
                self.coordinator.async_request_refresh(),
                "porchcast poll new number",
            )

    @override
    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a package."""
        package = await self._packages.async_create(item)
        self._async_changed()
        self._async_poll_if_due(package)

    @override
    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Edit a package's text, notes, due date or completion."""
        package = await self._packages.async_update(item)
        self._async_changed()
        self._async_poll_if_due(package)

    @override
    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Remove packages."""
        await self._packages.async_delete(uids)
        self._async_changed()

    @override
    async def async_move_todo_item(
        self, uid: str, previous_uid: str | None = None
    ) -> None:
        """Reorder the list."""
        await self._packages.async_move(uid, previous_uid)
        self._async_changed()
