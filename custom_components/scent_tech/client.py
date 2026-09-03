"""Persistent BLE client for Scent Tech diffusers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from time import monotonic
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CHARACTERISTIC_UUID,
    COMMAND_DISPENSE,
    COMMAND_LED_CYCLE,
    COMMAND_QUERY_SCHEDULES,
    COMMAND_OFF,
    COMMAND_ON,
    COMMAND_DEDUPLICATION_SECONDS,
    COMMAND_WAKE,
    LED_CYCLE_ORDER,
    LED_DEFAULT_COLOUR,
    LED_OFF_RGB,
    LED_PALETTE,
    LED_STEP_TIMEOUT,
    HA_SCHEDULE_END_MINUTE,
    HA_SCHEDULE_SLOT,
    HA_SCHEDULE_START_MINUTE,
    HA_SCHEDULE_TIMER_ID,
    HA_SCHEDULE_WEEKDAYS,
    PAUSE_TIME_DEFAULT,
    PAUSE_TIME_MAX,
    PAUSE_TIME_MIN,
    PRESET_CUSTOM,
    PRESET_VALUES,
    SPRAY_DURATION_DEFAULT,
    SPRAY_DURATION_MAX,
    CUSTOM_PAUSE_DEFAULT,
    CUSTOM_SPRAY_DEFAULT,
    DISPENSE_CONFIRM_TIMEOUT,
    DISPENSE_DURATION_DEFAULT,
    DISPENSE_DURATION_MAX,
    DISPENSE_DURATION_MIN,
    MANUAL_DISPENSE_SECONDS,
    SPRAY_DURATION_MIN,
    POLL_FAILURE_TOLERANCE,
    SCHEDULE_ENABLED_DEFAULT,
    SCHEDULE_QUERY_TIMEOUT,
    SCHEDULE_RECORD_SIZE,
    SCHEDULE_RESPONSE,
    STATUS_BGR_OFFSET,
    STATUS_COMMAND,
    STATUS_FLAG_POWERED,
    STATUS_FLAG_SPRAYING,
    STATUS_FLAGS_OFFSET,
    STATUS_MIN_PAYLOAD,
    STATUS_UPTIME_OFFSET,
)


_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ScentTechDiagnostics:
    """Runtime diagnostics that contain no credentials."""

    commands_requested: int = 0
    commands_written: int = 0
    commands_deduplicated: int = 0
    connection_attempts: int = 0
    connections_established: int = 0
    unexpected_disconnects: int = 0
    connection_failures: int = 0
    last_command: str | None = None
    last_notification: str | None = None
    last_status: str | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleRecord:
    """One 16-byte timer record as stored on the diffuser."""

    enabled: bool
    serial: int
    weekdays: int
    start_minute: int
    end_minute: int
    spray_duration: int
    pause_time: int
    timer_id: int

    @classmethod
    def from_bytes(cls, data: bytes) -> ScheduleRecord:
        """Decode one record."""
        return cls(
            enabled=bool(data[0]),
            serial=data[1],
            weekdays=int.from_bytes(data[2:4], "little"),
            start_minute=int.from_bytes(data[4:6], "little"),
            end_minute=int.from_bytes(data[6:8], "little"),
            spray_duration=int.from_bytes(data[8:10], "little"),
            pause_time=int.from_bytes(data[10:12], "little"),
            timer_id=int.from_bytes(data[12:16], "little"),
        )

    @property
    def is_all_day(self) -> bool:
        """Return whether this record covers every day, around the clock.

        A record shaped this way always matches, so the diffuser never falls
        through to a later one. Home Assistant keeps record 1 in this shape.
        """
        return (
            self.weekdays & 0x7F == 0x7F
            and self.start_minute <= HA_SCHEDULE_START_MINUTE
            and self.end_minute >= HA_SCHEDULE_END_MINUTE
        )


class ScentTechClient:
    """Maintain one BLE connection and serialize commands to a diffuser."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        name: str,
        *,
        send_wake_packet: bool,
    ) -> None:
        """Initialize the BLE client."""
        self._hass = hass
        self.address = address
        self.name = name
        self.send_wake_packet = send_wake_packet
        self.diagnostics = ScentTechDiagnostics()
        self._lock = asyncio.Lock()
        self._dispense_lock = asyncio.Lock()
        self._client: BleakClient | None = None
        self._closing = False
        self._last_payload: bytes | None = None
        self._last_write_at = 0.0
        self.spray_duration = SPRAY_DURATION_DEFAULT
        self.pause_time = PAUSE_TIME_DEFAULT
        self.schedule_enabled = SCHEDULE_ENABLED_DEFAULT
        self.custom_spray_duration = CUSTOM_SPRAY_DEFAULT
        self.custom_pause_time = CUSTOM_PAUSE_DEFAULT
        self.dispense_duration = DISPENSE_DURATION_DEFAULT
        self.led_rgb: tuple[int, int, int] | None = None
        self.powered: bool | None = None
        self.spraying: bool | None = None
        self.uptime: int | None = None
        self.last_lit_colour = LED_DEFAULT_COLOUR
        self._led_lock = asyncio.Lock()
        self._status_event = asyncio.Event()
        self._schedule_event = asyncio.Event()
        self.records: dict[int, ScheduleRecord] = {}
        self.ha_owns_schedule: bool | None = None
        self.last_poll_ok: bool | None = None
        self._poll_failures = 0
        self._rx = bytearray()
        self._listeners: set[Callable[[], None]] = set()

    @property
    def intensity(self) -> int:
        """Backward-compatible alias for spray duration."""
        return self.spray_duration

    @property
    def stop_time(self) -> int:
        """Backward-compatible alias for pause time."""
        return self.pause_time

    @property
    def led_colour(self) -> str | None:
        """Return the palette name for the last reported LED colour."""
        if self.led_rgb is None:
            return None
        for name, value in LED_PALETTE.items():
            if value == self.led_rgb:
                return name
        return None

    @property
    def preset(self) -> str:
        """Return the matching preset or Custom."""
        for name, values in PRESET_VALUES.items():
            if values == (self.spray_duration, self.pause_time):
                return name
        return PRESET_CUSTOM

    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entity state listener."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify_listeners(self) -> None:
        """Notify entities after local state changes."""
        for listener in tuple(self._listeners):
            listener()

    @property
    def is_connected(self) -> bool:
        """Return whether the persistent BLE session is connected."""
        return self._client is not None and self._client.is_connected

    def _disconnected(self, client: BleakClient) -> None:
        """Handle a disconnect reported by Bleak."""
        if client is not self._client:
            return
        self._client = None
        if not self._closing:
            self.diagnostics.unexpected_disconnects += 1
            _LOGGER.debug("Scent Tech diffuser %s disconnected", self.address)

    def _notification(self, _sender: Any, data: bytearray) -> None:
        """Reassemble notification bytes and decode any status frame."""
        value = bytes(data).hex()
        self.diagnostics.last_notification = value
        _LOGGER.debug("Notification from %s: %s", self.address, value)

        self._rx.extend(data)
        for frame in self._extract_frames():
            if frame[3] == STATUS_COMMAND:
                self._apply_status(frame)
            elif frame[3] == SCHEDULE_RESPONSE:
                self._apply_schedules(frame)

    def _extract_frames(self) -> list[bytes]:
        """Pull every complete, checksum-valid frame out of the receive buffer."""
        frames: list[bytes] = []
        while True:
            marker = self._rx.find(b"\x55\xaa")
            if marker < 0:
                # Keep a trailing 0x55 in case the header spans two notifications.
                self._rx[:] = b"\x55" if self._rx.endswith(b"\x55") else b""
                return frames
            if marker:
                del self._rx[:marker]
            if len(self._rx) < 3:
                return frames
            size = self._rx[2] + 5
            if len(self._rx) < size:
                return frames
            frame = bytes(self._rx[:size])
            del self._rx[:size]
            if frame[-1] != 0x5A or sum(frame[:-1]) & 0xFF:
                _LOGGER.debug("Discarding invalid frame: %s", frame.hex())
                continue
            frames.append(frame)

    def _apply_status(self, frame: bytes) -> None:
        """Decode one 0x21 status push and publish the result."""
        payload = frame[4:-2]
        if len(payload) < STATUS_MIN_PAYLOAD:
            _LOGGER.debug("Short status payload (%s bytes)", len(payload))
            return

        flags = payload[STATUS_FLAGS_OFFSET]
        self.powered = bool(flags & STATUS_FLAG_POWERED)
        self.spraying = bool(flags & STATUS_FLAG_SPRAYING)
        # The colour triple arrives as blue, green, red.
        self.led_rgb = (
            payload[STATUS_BGR_OFFSET + 2],
            payload[STATUS_BGR_OFFSET + 1],
            payload[STATUS_BGR_OFFSET],
        )
        self.uptime = int.from_bytes(
            payload[STATUS_UPTIME_OFFSET : STATUS_UPTIME_OFFSET + 4], "little"
        )
        if (colour := self.led_colour) is not None and colour != "off":
            self.last_lit_colour = colour

        self.diagnostics.last_status = frame.hex()
        self._status_event.set()
        self._notify_listeners()

    def _apply_schedules(self, frame: bytes) -> None:
        """Decode a 0x88 reply and adopt the diffuser's own settings.

        The device reports only the records it actually holds, preceded by a
        two-byte count, rather than a fixed five.
        """
        payload = frame[4:-2]
        if len(payload) < 2:
            _LOGGER.debug("Short schedule reply: %s", frame.hex())
            return

        records: dict[int, ScheduleRecord] = {}
        body = payload[2:]
        for offset in range(0, len(body) - SCHEDULE_RECORD_SIZE + 1, SCHEDULE_RECORD_SIZE):
            record = ScheduleRecord.from_bytes(body[offset : offset + SCHEDULE_RECORD_SIZE])
            records[record.serial] = record
        self.records = records

        owned = records.get(HA_SCHEDULE_SLOT)
        self.ha_owns_schedule = owned is not None and owned.is_all_day
        if owned is not None and self.ha_owns_schedule:
            self.spray_duration = owned.spray_duration
            self.pause_time = owned.pause_time
            self.schedule_enabled = owned.enabled
        elif owned is not None:
            # The phone app has narrowed record 1, so the diffuser can fall
            # through to another record and run when Home Assistant thinks it
            # is idle. Report what the record says and flag the mismatch.
            self.spray_duration = owned.spray_duration
            self.pause_time = owned.pause_time
            self.schedule_enabled = owned.enabled
            _LOGGER.warning(
                "Record 1 on %s is windowed %02d:%02d-%02d:%02d rather than all "
                "day, so other stored schedules can still run. Change any "
                "setting in Home Assistant to take it back.",
                self.address,
                owned.start_minute // 60,
                owned.start_minute % 60,
                owned.end_minute // 60,
                owned.end_minute % 60,
            )

        self._schedule_event.set()
        self._notify_listeners()

    async def _async_connect(self) -> BleakClient:
        """Return the live persistent client, connecting once when needed."""
        if self.is_connected:
            return self._client  # type: ignore[return-value]

        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self.address, connectable=True
        )
        if ble_device is None:
            detail = bluetooth.async_address_reachability_diagnostics(
                self._hass,
                self.address,
                bluetooth.BluetoothReachabilityIntent.CONNECTION,
            )
            message = f"Diffuser {self.address} is not reachable over Bluetooth: {detail}"
            self.diagnostics.connection_failures += 1
            self.diagnostics.last_error = message
            raise HomeAssistantError(message)

        self.diagnostics.connection_attempts += 1
        _LOGGER.debug("Connecting to Scent Tech diffuser %s", self.address)
        try:
            client = await establish_connection(
                client_class=BleakClient,
                device=ble_device,
                name=self.name,
                max_attempts=1,
            )
            client.set_disconnected_callback(self._disconnected)
            self._client = client
            self.diagnostics.connections_established += 1
            self.diagnostics.last_error = None

            # The captured application traffic uses the same FFE1 characteristic
            # for writes and notifications. Failure to subscribe must not prevent
            # the proven ON/OFF writes from working.
            try:
                await client.start_notify(CHARACTERISTIC_UUID, self._notification)
                _LOGGER.debug("Subscribed to notifications from %s", self.address)
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug(
                    "Notification subscription unavailable for %s: %s",
                    self.address,
                    err,
                )

            _LOGGER.debug("Persistent connection established to %s", self.address)
            return client
        except (BleakError, TimeoutError, OSError) as err:
            message = f"Unable to connect to diffuser: {err}"
            self.diagnostics.connection_failures += 1
            self.diagnostics.last_error = message
            raise HomeAssistantError(message) from err

    @staticmethod
    def _build_packet(command: int, data: bytes) -> bytes:
        """Build a framed Scent Tech packet with its protocol checksum."""
        length = 1 + len(data)
        body = bytes((length, command)) + data
        checksum = (0x101 - sum(body)) & 0xFF
        return b"\x55\xaa" + body + bytes((checksum, 0x5A))

    def build_settings_packet(
        self, spray_duration: int, pause_time: int, schedule_enabled: bool
    ) -> bytes:
        """Build command 0x14 for the Home Assistant-owned schedule record.

        The window is deliberately fixed at every day, 00:00-23:59. A record
        that always matches is one the diffuser never falls through, so any
        schedule the phone app left behind cannot fire behind our back. Spray
        duration and pause time are what Home Assistant actually varies.
        """
        data = (
            bytes((1 if schedule_enabled else 0, HA_SCHEDULE_SLOT))
            + HA_SCHEDULE_WEEKDAYS.to_bytes(2, "little")
            + HA_SCHEDULE_START_MINUTE.to_bytes(2, "little")
            + HA_SCHEDULE_END_MINUTE.to_bytes(2, "little")
            + spray_duration.to_bytes(2, "little")
            + pause_time.to_bytes(2, "little")
            + HA_SCHEDULE_TIMER_ID.to_bytes(4, "little")
        )
        return self._build_packet(0x14, data)

    async def async_set_settings(
        self,
        *,
        spray_duration: int | None = None,
        pause_time: int | None = None,
        intensity: int | None = None,
        stop_time: int | None = None,
        remember_custom: bool = False,
    ) -> bool:
        """Write the complete settings packet, preserving the other setting.

        intensity and stop_time remain accepted for upgrades from earlier builds.
        """
        if spray_duration is None:
            spray_duration = intensity
        if pause_time is None:
            pause_time = stop_time
        new_duration = self.spray_duration if spray_duration is None else spray_duration
        new_pause = self.pause_time if pause_time is None else pause_time

        if not SPRAY_DURATION_MIN <= new_duration <= SPRAY_DURATION_MAX:
            raise HomeAssistantError(
                f"Spray duration must be between {SPRAY_DURATION_MIN} and "
                f"{SPRAY_DURATION_MAX} seconds"
            )
        if not PAUSE_TIME_MIN <= new_pause <= PAUSE_TIME_MAX:
            raise HomeAssistantError(
                f"Pause time must be between {PAUSE_TIME_MIN} and "
                f"{PAUSE_TIME_MAX} seconds"
            )

        if remember_custom:
            self.custom_spray_duration = new_duration
            self.custom_pause_time = new_pause

        # Rewriting the timer record makes the firmware restart its cycle at the
        # spray phase, so a redundant write costs a burst of fragrance for no
        # change. Skip it when nothing would actually differ.
        if (
            new_duration == self.spray_duration
            and new_pause == self.pause_time
        ):
            self._notify_listeners()
            return True

        payload = self.build_settings_packet(
            new_duration, new_pause, self.schedule_enabled
        )
        written = await self.async_send(payload)
        if written:
            self.spray_duration = new_duration
            self.pause_time = new_pause
            self._notify_listeners()
        return written

    async def async_set_schedule(self, enabled: bool) -> bool:
        """Enable or disable the stored repeating spray/pause cycle.

        The schedule record and the power register are separate: a diffuser
        whose power register is off will not run an enabled schedule. Both are
        written so the switch means what it says.
        """
        payload = self.build_settings_packet(
            self.spray_duration, self.pause_time, enabled
        )
        written = await self.async_send(payload)
        if written:
            self.schedule_enabled = enabled
            await asyncio.sleep(0.25)
            await self.async_send(
                COMMAND_ON if enabled else COMMAND_OFF, allow_duplicate=True
            )
            self._notify_listeners()
        return written

    async def async_ensure_powered(self) -> None:
        """Switch the power register on when a schedule is meant to be running.

        Called after the setup poll so a restart cannot leave an enabled
        schedule sitting on a powered-off diffuser.
        """
        if not self.schedule_enabled:
            return
        if self.powered:
            return
        await self.async_send(COMMAND_ON, allow_duplicate=True)

    async def async_dispense_now(self) -> None:
        """Run one manual burst, whatever the diffuser's power state.

        Command 0x16 is a dedicated one-shot that leaves the power register
        alone, but the firmware ignores it while the diffuser is powered off.
        In that case, and for any non-default duration, the power register is
        held on for the requested time and then returned to how it was.
        """
        async with self._dispense_lock:
            if (
                self.powered is not False
                and self.dispense_duration == MANUAL_DISPENSE_SECONDS
            ):
                self._status_event.clear()
                await self.async_send(COMMAND_DISPENSE, allow_duplicate=True)
                try:
                    await asyncio.wait_for(
                        self._status_event.wait(), DISPENSE_CONFIRM_TIMEOUT
                    )
                except TimeoutError:
                    _LOGGER.debug(
                        "No status push after a one-shot dispense on %s; "
                        "falling back to a timed burst",
                        self.address,
                    )
                else:
                    return

            # Timed burst: hold the power register on, then put it back. The
            # schedule depends on the same register, so it must be restored.
            was_powered = bool(self.powered) or self.schedule_enabled
            await self.async_send(COMMAND_ON, allow_duplicate=True)
            try:
                await asyncio.sleep(self.dispense_duration)
            finally:
                if not was_powered:
                    await asyncio.shield(
                        self.async_send(COMMAND_OFF, allow_duplicate=True)
                    )

    async def async_set_preset(self, preset: str) -> bool:
        """Apply a fragrance preset in one BLE write.

        Custom is a real preset: it restores whatever spray and pause the user
        last set by hand, rather than being an unselectable label.
        """
        if preset == PRESET_CUSTOM:
            duration, pause = self.custom_spray_duration, self.custom_pause_time
        else:
            try:
                duration, pause = PRESET_VALUES[preset]
            except KeyError as err:
                raise HomeAssistantError(f"Unsupported preset: {preset}") from err
        return await self.async_set_settings(
            spray_duration=duration, pause_time=pause
        )

    async def async_set_dispense_duration(self, seconds: int) -> None:
        """Set how long the Dispense now button sprays for."""
        if not DISPENSE_DURATION_MIN <= seconds <= DISPENSE_DURATION_MAX:
            raise HomeAssistantError(
                f"Dispense duration must be between {DISPENSE_DURATION_MIN} "
                f"and {DISPENSE_DURATION_MAX} seconds"
            )
        self.dispense_duration = seconds
        self._notify_listeners()

    @property
    def available(self) -> bool:
        """Return whether recent polling supports showing a state.

        One missed poll is tolerated; a dropped BLE connection is far more
        common than the diffuser genuinely going away.
        """
        if self.last_poll_ok is None:
            return True
        return self._poll_failures < POLL_FAILURE_TOLERANCE

    async def async_connect(self) -> None:
        """Open the persistent session, for use during setup."""
        async with self._lock:
            await self._async_connect()

    async def async_refresh(self) -> bool:
        """Read the stored schedules and adopt them as Home Assistant state.

        Returns False when the diffuser could not be reached. State is only
        replaced on success, so a missed poll leaves the last known values in
        place rather than reverting entities to defaults.
        """
        self._schedule_event.clear()
        try:
            await self.async_send(COMMAND_QUERY_SCHEDULES, allow_duplicate=True)
            await asyncio.wait_for(
                self._schedule_event.wait(), SCHEDULE_QUERY_TIMEOUT
            )
        except (HomeAssistantError, TimeoutError) as err:
            self._poll_failures += 1
            self.last_poll_ok = False
            self.diagnostics.last_error = f"Schedule poll failed: {err}"
            _LOGGER.debug("Schedule poll failed for %s: %s", self.address, err)
            self._notify_listeners()
            return False

        self._poll_failures = 0
        self.last_poll_ok = True
        return True

    async def async_cycle_led(self) -> None:
        """Advance the indicator LED one place through the firmware palette."""
        async with self._led_lock:
            await self._async_step_led()

    async def _async_step_led(self) -> None:
        """Send one cycle command and wait briefly for the status push."""
        self._status_event.clear()
        await self.async_send(COMMAND_LED_CYCLE, allow_duplicate=True)
        try:
            await asyncio.wait_for(self._status_event.wait(), LED_STEP_TIMEOUT)
        except TimeoutError:
            # The colour still changed; only the confirmation is missing.
            _LOGGER.debug("No status push after an LED cycle on %s", self.address)

    async def async_set_led_colour(self, colour: str) -> None:
        """Cycle the LED until the diffuser reports the requested colour.

        The firmware exposes no direct colour command, so this steps and checks.
        Each write makes the diffuser beep, so an already-correct colour is left
        alone rather than driven a full loop back to itself.
        """
        if colour not in LED_PALETTE:
            raise HomeAssistantError(f"Unsupported LED colour: {colour}")

        async with self._led_lock:
            for _ in range(len(LED_CYCLE_ORDER)):
                if self.led_colour == colour:
                    return
                await self._async_step_led()
                if self.led_colour is None:
                    raise HomeAssistantError(
                        "The diffuser did not report its LED state; cannot "
                        "select a colour without status feedback"
                    )
            if self.led_colour != colour:
                _LOGGER.debug(
                    "LED did not settle on %s after a full cycle (now %s)",
                    colour,
                    self.led_colour,
                )

    async def async_send(
        self, payload: bytes, *, allow_duplicate: bool = False
    ) -> bool:
        """Send one packet on the persistent session.

        Return False when a rapid duplicate is deliberately suppressed. Pass
        allow_duplicate for commands whose repetition is meaningful, such as the
        LED cycle, where each identical write advances the device one step.
        """
        self.diagnostics.commands_requested += 1

        async with self._lock:
            now = monotonic()
            if (
                not allow_duplicate
                and payload == self._last_payload
                and now - self._last_write_at < COMMAND_DEDUPLICATION_SECONDS
            ):
                self.diagnostics.commands_deduplicated += 1
                _LOGGER.warning(
                    "Suppressed duplicate Scent Tech command %s for %s",
                    payload.hex(),
                    self.address,
                )
                return False

            client = await self._async_connect()
            try:
                if self.send_wake_packet:
                    _LOGGER.debug(
                        "Writing optional wake packet %s to %s",
                        COMMAND_WAKE.hex(),
                        self.address,
                    )
                    await client.write_gatt_char(
                        CHARACTERISTIC_UUID, COMMAND_WAKE, response=False
                    )
                    await asyncio.sleep(0.15)

                _LOGGER.debug(
                    "Writing one Scent Tech command %s to %s",
                    payload.hex(),
                    self.address,
                )
                await client.write_gatt_char(
                    CHARACTERISTIC_UUID, payload, response=False
                )

                self._last_payload = payload
                self._last_write_at = monotonic()
                self.diagnostics.commands_written += 1
                self.diagnostics.last_command = payload.hex()
                self.diagnostics.last_error = None
                return True
            except (BleakError, TimeoutError, OSError) as err:
                # Do not automatically replay a command: a failed acknowledgement
                # does not prove the diffuser failed to execute it, and replaying can
                # create duplicate beeps/actions.
                self._client = None
                try:
                    if client.is_connected:
                        await client.disconnect()
                except (BleakError, TimeoutError, OSError):
                    pass
                message = f"Unable to send command to diffuser: {err}"
                self.diagnostics.connection_failures += 1
                self.diagnostics.last_error = message
                raise HomeAssistantError(message) from err

    async def async_disconnect(self) -> None:
        """Close the persistent BLE session during integration unload."""
        async with self._lock:
            self._closing = True
            client = self._client
            self._client = None
            if client is None or not client.is_connected:
                return
            try:
                _LOGGER.debug("Disconnecting from Scent Tech diffuser %s", self.address)
                await client.disconnect()
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug("Error disconnecting from %s: %s", self.address, err)
