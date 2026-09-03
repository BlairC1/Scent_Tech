"""Preset and indicator LED selectors for Smart Technology scent diffusers."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ScentTechConfigEntry
from .const import (
    DOMAIN,
    LED_COLOUR_OPTIONS,
    MANUFACTURER,
    MODEL,
    PRESET_OPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentTechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the preset and indicator LED selectors."""
    async_add_entities(
        [ScentTechPresetSelect(entry), ScentTechLedColourSelect(entry)]
    )


class ScentTechPresetSelect(SelectEntity):
    """Select a coordinated spray-duration and pause-time preset."""

    _attr_has_entity_name = True
    _attr_name = "Preset"
    _attr_icon = "mdi:tune-variant"
    _attr_should_poll = False
    _attr_options = PRESET_OPTIONS

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        self._client = entry.runtime_data
        self._attr_unique_id = f"{self._client.address}_preset"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._client.address)},
            connections={("bluetooth", self._client.address)},
            name=self._client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.async_add_listener(self._handle_client_update))

    def _handle_client_update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str:
        return self._client.preset

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        """Expose the remembered Custom pair so it can be checked in the UI."""
        return {
            "custom_spray_duration": self._client.custom_spray_duration,
            "custom_pause_time": self._client.custom_pause_time,
        }

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen preset.

        Custom is selectable rather than a read-only label: it restores the
        spray duration and pause the user last set by hand.
        """
        await self._client.async_set_preset(option)


class ScentTechLedColourSelect(SelectEntity):
    """Select the indicator LED colour, or switch it off.

    The firmware supports three lit colours and off, reachable only by stepping
    through a fixed cycle, so this selects rather than sets. Each step makes the
    diffuser beep, so an already-correct colour is left alone.
    """

    _attr_has_entity_name = True
    _attr_name = "LED colour"
    _attr_icon = "mdi:led-on"
    _attr_should_poll = False
    _attr_options = LED_COLOUR_OPTIONS

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        self._client = entry.runtime_data
        self._attr_unique_id = f"{self._client.address}_led_colour"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._client.address)},
            connections={("bluetooth", self._client.address)},
            name=self._client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.async_add_listener(self._handle_client_update))

    def _handle_client_update(self) -> None:
        self.async_write_ha_state()

    @property
    def current_option(self) -> str | None:
        """Return the reported colour, or None before the first status push."""
        return self._client.led_colour

    async def async_select_option(self, option: str) -> None:
        await self._client.async_set_led_colour(option)
