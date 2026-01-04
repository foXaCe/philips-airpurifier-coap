"""New generation Philips AirPurifier devices (PhilipsNewGenericFan)."""

from __future__ import annotations

from datetime import timedelta

from ..const import (
    FanAttributes,
    PhilipsApi,
    PresetMode,
)
from .base import PhilipsGenericFanBase


class PhilipsNewGenericFan(PhilipsGenericFanBase):
    """Class to manage a new generic fan."""

    AVAILABLE_ATTRIBUTES = [
        # device information
        (FanAttributes.NAME, PhilipsApi.NEW_NAME),
        (FanAttributes.MODEL_ID, PhilipsApi.NEW_MODEL_ID),
        (FanAttributes.PRODUCT_ID, PhilipsApi.PRODUCT_ID),
        (FanAttributes.DEVICE_ID, PhilipsApi.DEVICE_ID),
        (FanAttributes.SOFTWARE_VERSION, PhilipsApi.NEW_SOFTWARE_VERSION),
        (FanAttributes.WIFI_VERSION, PhilipsApi.WIFI_VERSION),
        # device configuration
        (FanAttributes.LANGUAGE, PhilipsApi.NEW_LANGUAGE),
        (
            FanAttributes.PREFERRED_INDEX,
            PhilipsApi.NEW_PREFERRED_INDEX,
            PhilipsApi.NEW_PREFERRED_INDEX_MAP,
        ),
        # device sensors
        (
            FanAttributes.RUNTIME,
            PhilipsApi.RUNTIME,
            lambda x, _: str(timedelta(seconds=round(x / 1000))),
        ),
    ]

    AVAILABLE_LIGHTS = []
    AVAILABLE_SWITCHES = []
    AVAILABLE_SELECTS = [PhilipsApi.NEW_PREFERRED_INDEX]

    KEY_PHILIPS_POWER = PhilipsApi.NEW_POWER
    STATE_POWER_ON = "ON"
    STATE_POWER_OFF = "OFF"


# similar to the AC1715, the AC0850 seems to be a new class of devices that
# follows some patterns of its own


# the AC0850/11 comes in two versions.
# the first version has a Wifi string starting with "AWS_Philips_AIR"
# the second version has a Wifi string starting with "AWS_Philips_AIR_Combo"
class PhilipsAC085011(PhilipsNewGenericFan):
    """AC0850/11 with firmware AWS_Philips_AIR."""

    AVAILABLE_PRESET_MODES = {
        PresetMode.AUTO: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Auto General",
        },
        PresetMode.TURBO: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Turbo"},
        PresetMode.SLEEP: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Sleep"},
    }
    AVAILABLE_SPEEDS = {
        PresetMode.SLEEP: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Sleep"},
        PresetMode.TURBO: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Turbo"},
    }
    # the prefilter data is present but doesn't change for this device, so let's take it out
    UNAVAILABLE_FILTERS = [PhilipsApi.FILTER_NANOPROTECT_PREFILTER]


class PhilipsAC085020(PhilipsAC085011):
    """AC0850/20 with firmware AWS_Philips_AIR."""


class PhilipsAC085031(PhilipsAC085011):
    """AC0850/31 with firmware AWS_Philips_AIR."""


class PhilipsAC085041(PhilipsAC085011):
    """AC0850/41 with firmware AWS_Philips_AIR."""


class PhilipsAC085070(PhilipsAC085011):
    """AC0850/70 with firmware AWS_Philips_AIR."""


class PhilipsAC085085(PhilipsAC085011):
    """AC0850/85."""


# the AC1715 seems to be a new class of devices that follows some patterns of its own
class PhilipsAC1715(PhilipsNewGenericFan):
    """AC1715."""

    AVAILABLE_PRESET_MODES = {
        PresetMode.AUTO: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Auto General",
        },
        PresetMode.SPEED_1: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Gentle/Speed 1",
        },
        PresetMode.SPEED_2: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Speed 2",
        },
        PresetMode.TURBO: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Turbo"},
        PresetMode.SLEEP: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Sleep"},
    }
    AVAILABLE_SPEEDS = {
        PresetMode.SLEEP: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Sleep"},
        PresetMode.SPEED_1: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Gentle/Speed 1",
        },
        PresetMode.SPEED_2: {
            PhilipsApi.NEW_POWER: "ON",
            PhilipsApi.NEW_MODE: "Speed 2",
        },
        PresetMode.TURBO: {PhilipsApi.NEW_POWER: "ON", PhilipsApi.NEW_MODE: "Turbo"},
    }
    AVAILABLE_LIGHTS = [PhilipsApi.NEW_DISPLAY_BACKLIGHT]
