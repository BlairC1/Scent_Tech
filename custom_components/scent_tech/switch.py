"""Switch platform for Smart Technology BLE scent diffusers."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ScentTechConfigEntry
from .const import DOMAIN, MANUFACTURER, MODEL


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentTechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up automatic diffusion."""
    async_add_entities([ScentTechAutomaticDiffusionSwitch(entry)])


class ScentTechAutomaticDiffusionSwitch(SwitchEntity):
    """Enable or disable the repeating spray/pause cycle."""

    _attr_has_entity_name = True
    _attr_name = "Automatic diffusion"
    _attr_icon = "mdi:autorenew"
    _attr_should_poll = False

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        self._client = entry.runtime_data
        # Preserve the v2 schedule unique ID so existing installations retain
        # their entity ID, history, dashboard references and automations.
        self._attr_unique_id = f"{self._client.address}_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._client.address)},
            connections={("bluetooth", self._client.address)},
            name=self._client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to shared state changes."""
        self.async_on_remove(self._client.async_add_listener(self._handle_client_update))

    def _handle_client_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Report unavailable only after repeated polls have failed."""
        return self._client.available

    @property
    def is_on(self) -> bool:
        return self._client.schedule_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable automatic repeating diffusion."""
        await self._client.async_set_schedule(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable automatic repeating diffusion."""
        await self._client.async_set_schedule(False)
