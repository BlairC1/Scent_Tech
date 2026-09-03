"""Scent Tech BLE diffuser integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .client import ScentTechClient
from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SEND_WAKE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SEND_WAKE,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

type ScentTechConfigEntry = ConfigEntry[ScentTechClient]


async def async_setup_entry(
    hass: HomeAssistant, entry: ScentTechConfigEntry
) -> bool:
    """Set up Scent Tech from a config entry."""
    entry.runtime_data = ScentTechClient(
        hass,
        entry.data[CONF_ADDRESS],
        entry.data[CONF_NAME],
        send_wake_packet=entry.options.get(CONF_SEND_WAKE, DEFAULT_SEND_WAKE),
    )
    client = entry.runtime_data

    # Read the device before creating entities so a restart restores real state
    # instead of falling back to defaults. A diffuser that is asleep or out of
    # range must not block setup: entities appear and the next poll fills them in.
    try:
        await client.async_connect()
        await client.async_refresh()
        await client.async_ensure_powered()
    except Exception:  # noqa: BLE001 - setup must survive any connection problem
        _LOGGER.debug(
            "Could not read %s during setup; will retry on the next poll",
            client.address,
            exc_info=True,
        )

    interval = timedelta(
        seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    )

    async def _async_poll(_now) -> None:
        await client.async_refresh()

    entry.async_on_unload(async_track_time_interval(hass, _async_poll, interval))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ScentTechConfigEntry
) -> None:
    """Reload after options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: ScentTechConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_disconnect()
    return unloaded
