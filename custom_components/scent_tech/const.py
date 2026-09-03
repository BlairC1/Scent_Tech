"""Constants for the Smart Technology Scent Diffuser integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "scent_tech"
PLATFORMS: Final = [
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]

CONF_ADDRESS: Final = "address"
CONF_NAME: Final = "name"
CONF_SEND_WAKE: Final = "send_wake_packet"
CONF_POLL_INTERVAL: Final = "poll_interval"

DEFAULT_NAME: Final = "Scent Diffuser"
DEFAULT_SEND_WAKE: Final = False
DEFAULT_POLL_INTERVAL: Final = 300
MIN_POLL_INTERVAL: Final = 60
MAX_POLL_INTERVAL: Final = 3600
# Tolerate one missed poll before entities go unavailable: a single dropped BLE
# connection is far more common than the diffuser actually going away.
POLL_FAILURE_TOLERANCE: Final = 2

SERVICE_UUID: Final = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_UUID: Final = "0000ffe1-0000-1000-8000-00805f9b34fb"

COMMAND_ON: Final = bytes.fromhex("55aa0407120100e35a")
COMMAND_OFF: Final = bytes.fromhex("55aa0407120000e45a")
COMMAND_WAKE: Final = bytes.fromhex("55aa0147b95a")
# Read every stored timer record. The device answers with 0x88.
COMMAND_QUERY_SCHEDULES: Final = bytes.fromhex("55aa0108f85a")
# Command 0x16 fires one immediate burst and leaves the power register alone,
# unlike an ON/sleep/OFF pair which switches the diffuser off afterwards and
# silently stops the stored schedule from running.
COMMAND_DISPENSE: Final = bytes.fromhex("55aa0116ea5a")

SCHEDULE_RESPONSE: Final = 0x88
SCHEDULE_RECORD_SIZE: Final = 16
SCHEDULE_QUERY_TIMEOUT: Final = 5.0

# Home Assistant owns record 1 and keeps it covering every day, all day, so the
# diffuser always matches it and never falls through to a record the phone app
# wrote. Spray and pause are then the only things that vary.
HA_SCHEDULE_SLOT: Final = 1
HA_SCHEDULE_WEEKDAYS: Final = 0x00FF
HA_SCHEDULE_START_MINUTE: Final = 0
HA_SCHEDULE_END_MINUTE: Final = 1439
HA_SCHEDULE_TIMER_ID: Final = 1

# Command 0x07 register 0x15 with any non-zero value steps the indicator LED one
# place through a fixed four-colour cycle. A zero value is a no-op, and there is
# no known way to address a colour directly.
COMMAND_LED_CYCLE: Final = bytes.fromhex("55aa0407150100e05a")

# Unsolicited status push. The colour triple is transmitted as blue, green, red.
STATUS_COMMAND: Final = 0x21
STATUS_MIN_PAYLOAD: Final = 39
STATUS_FLAGS_OFFSET: Final = 4
STATUS_BGR_OFFSET: Final = 10
STATUS_UPTIME_OFFSET: Final = 31
STATUS_FLAG_POWERED: Final = 0x01
STATUS_FLAG_SPRAYING: Final = 0x08

LED_OFF_RGB: Final = (0x00, 0x00, 0x00)
LED_PALETTE: Final = {
    "white": (0xE5, 0xE5, 0xE5),
    "yellow": (0xFF, 0xED, 0x3D),
    "blue": (0x2A, 0x82, 0xE4),
    "off": LED_OFF_RGB,
}
# Order the hardware steps through, used to bound the cycle loop.
LED_CYCLE_ORDER: Final = ("white", "yellow", "blue", "off")
# Options offered in the UI, in the order the hardware steps through them.
LED_COLOUR_OPTIONS: Final = list(LED_CYCLE_ORDER)
LED_DEFAULT_COLOUR: Final = "white"
LED_STEP_TIMEOUT: Final = 2.0

MANUAL_DISPENSE_SECONDS: Final = 3

SPRAY_DURATION_MIN: Final = 3
SPRAY_DURATION_MAX: Final = 8
SPRAY_DURATION_DEFAULT: Final = 5
PAUSE_TIME_MIN: Final = 90
PAUSE_TIME_MAX: Final = 600
PAUSE_TIME_STEP: Final = 30
PAUSE_TIME_DEFAULT: Final = 300
SCHEDULE_ENABLED_DEFAULT: Final = False

PRESET_LIGHT: Final = "Light"
PRESET_BALANCED: Final = "Balanced"
PRESET_INTENSE: Final = "Intense"
PRESET_CUSTOM: Final = "Custom"
PRESET_OPTIONS: Final = [
    PRESET_LIGHT,
    PRESET_BALANCED,
    PRESET_INTENSE,
    PRESET_CUSTOM,
]
PRESET_VALUES: Final = {
    PRESET_LIGHT: (3, 600),
    PRESET_BALANCED: (5, 300),
    PRESET_INTENSE: (8, 120),
}

MANUFACTURER: Final = "Smart Technology"
MODEL: Final = "Scent Tech B30N BLE Diffuser"

COMMAND_DEDUPLICATION_SECONDS: Final = 1.5
