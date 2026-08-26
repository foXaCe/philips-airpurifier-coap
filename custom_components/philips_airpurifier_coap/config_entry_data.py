"""Module containing the ConfigEntryData class for the Philips Air Purifier integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aioairctrl import CoAPClient

if TYPE_CHECKING:
    from .aioairctrl import CoAPClient
    from .coordinator import Coordinator
    from .model import DeviceInformation, DeviceStatus


@dataclass
class ConfigEntryData:
    """Config entry data class."""

    device_information: DeviceInformation
    client: CoAPClient
    coordinator: Coordinator
    latest_status: DeviceStatus | None = None
