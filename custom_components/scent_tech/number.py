"""Number entities for Smart Technology diffuser settings."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ScentTechConfigEntry
from .const import (
    DOMAIN,
    MANUFACTURER,
    MODEL,
    PAUSE_TIME_MAX,
    PAUSE_TIME_MIN,
    PAUSE_TIME_STEP,
    SPRAY_DURATION_MAX,
    SPRAY_DURATION_MIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ScentTechConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up diffuser setting entities."""
    async_add_entities(
        [ScentTechSprayDurationNumber(entry), ScentTechPauseTimeNumber(entry)]
    )


class ScentTechNumberBase(NumberEntity):
    """Base class for a diffuser number entity."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        self._client = entry.runtime_data
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._client.address)},
            connections={("bluetooth", self._client.address)},
            name=self._client.name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to shared client state updates."""
        self.async_on_remove(self._client.async_add_listener(self._handle_client_update))

    def _handle_client_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return True


class ScentTechSprayDurationNumber(ScentTechNumberBase):
    """Duration of each fragrance burst."""

    _attr_name = "Spray duration"
    _attr_icon = "mdi:spray"
    _attr_native_min_value = SPRAY_DURATION_MIN
    _attr_native_max_value = SPRAY_DURATION_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "s"

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{self._client.address}_intensity"

    @property
    def native_value(self) -> float:
        return self._client.spray_duration

    async def async_set_native_value(self, value: float) -> None:
        # A value set by hand defines the Custom preset.
        await self._client.async_set_settings(
            spray_duration=int(value), remember_custom=True
        )


class ScentTechPauseTimeNumber(ScentTechNumberBase):
    """Pause between fragrance bursts."""

    _attr_name = "Pause time"
    _attr_icon = "mdi:timer-pause-outline"
    _attr_native_min_value = PAUSE_TIME_MIN
    _attr_native_max_value = PAUSE_TIME_MAX
    _attr_native_step = PAUSE_TIME_STEP
    _attr_native_unit_of_measurement = "s"

    def __init__(self, entry: ScentTechConfigEntry) -> None:
        super().__init__(entry)
        self._attr_unique_id = f"{self._client.address}_stop_time"

    @property
    def native_value(self) -> float:
        return self._client.pause_time

    async def async_set_native_value(self, value: float) -> None:
        # A value set by hand defines the Custom preset.
        await self._client.async_set_settings(
            pause_time=int(value), remember_custom=True
        )
