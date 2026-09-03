"""Config flow for Scent Tech."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_ADDRESS,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_SEND_WAKE,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SEND_WAKE,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)


class ScentTechConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Scent Tech."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        if not discovery_info.name.startswith("Scent-"):
            return self.async_abort(reason="not_supported")

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm a discovered diffuser."""
        if self._discovery_info is None:
            return self.async_abort(reason="not_supported")

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name,
                },
            )
        return self.async_show_form(step_id="confirm")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            await self.async_set_unique_id(address)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={CONF_ADDRESS: address, CONF_NAME: user_input[CONF_NAME]},
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ScentTechOptionsFlow:
        """Return the options flow."""
        return ScentTechOptionsFlow(config_entry)


class ScentTechOptionsFlow(config_entries.OptionsFlow):
    """Handle Scent Tech options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SEND_WAKE,
                        default=self._config_entry.options.get(
                            CONF_SEND_WAKE, DEFAULT_SEND_WAKE
                        ),
                    ): bool,
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL),
                    ),
                }
            ),
        )
