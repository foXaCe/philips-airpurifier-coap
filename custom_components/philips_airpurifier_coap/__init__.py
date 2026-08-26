"""Support for Philips AirPurifier with CoAP."""

from __future__ import annotations

import asyncio
from functools import partial
from ipaddress import IPv6Address, ip_address
import json
import logging
import os
from os import walk
from pathlib import Path
from typing import TYPE_CHECKING, Any

from getmac import get_mac_address

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.http.view import HomeAssistantView
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.typing import ConfigType

from .aioairctrl import CoAPClient
from .config_entry_data import ConfigEntryData
from .const import (
    CONF_DEVICE_ID,
    CONF_MODEL,
    CONF_STATUS,
    DOMAIN,
    ICONLIST_URL,
    ICONS_PATH,
    ICONS_URL,
    LOADER_PATH,
    LOADER_URL,
    PAP,
)
from .coordinator import Coordinator
from .model import DeviceInformation

if TYPE_CHECKING:
    from .const import PhilipsConfigEntry

_LOGGER = logging.getLogger(__name__)

# Force aiocoap to use the simple6 transport so CoAP also works on IPv4-only hosts.
# aiocoap reads these when it creates a context, so setting them here — at integration
# import, before any CoAPClient is created — covers both the config-flow network scan
# and the runtime connection. See https://github.com/kongo09/philips-airpurifier-coap/issues/256
os.environ.setdefault("AIOCOAP_CLIENT_TRANSPORT", "simple6")
os.environ.setdefault("AIOCOAP_SERVER_TRANSPORT", "simple6")


PLATFORMS = [
    "binary_sensor",
    "button",
    "climate",
    "fan",
    "humidifier",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
]

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)


# icons code thanks to Thomas Loven:
# https://github.com/thomasloven/hass-fontawesome/blob/master/custom_components/fontawesome/__init__.py


class ListingView(HomeAssistantView):
    """Provide a json list of the used icons."""

    requires_auth = False

    def __init__(self, url: str, iconpath: str, hass: HomeAssistant) -> None:
        """Initialize the ListingView with a URL and icon path."""
        self.url = url
        self.iconpath = iconpath
        self.name = "Icon Listing"
        self.hass = hass

    async def get(self, request: Any, *args: Any) -> str:
        """Call executor to avoid blocking I/O call to get list of used icons."""
        return await self.hass.async_add_executor_job(self.get_icons_list, self.iconpath)

    def get_icons_list(self, iconpath: str) -> str:
        """Handle GET request to provide a JSON list of the used icons."""
        icons = []
        for dirpath, _dirnames, filenames in walk(iconpath):
            icons.extend(
                [
                    {"name": (Path(dirpath[len(self.iconpath) :]) / fn[:-4]).as_posix()}
                    for fn in filenames
                    if fn.endswith(".svg")
                ]
            )
        return json.dumps(icons)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the icons for the Philips AirPurifier integration."""
    _LOGGER.debug("async_setup called")

    await hass.http.async_register_static_paths(
        [StaticPathConfig(LOADER_URL, hass.config.path(LOADER_PATH), True)]
    )
    add_extra_js_url(hass, LOADER_URL)

    iset = PAP
    iconpath = hass.config.path(ICONS_PATH + "/" + iset)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(ICONS_URL + "/" + iset, iconpath, True)]
    )
    hass.http.register_view(ListingView(ICONLIST_URL + "/" + iset, iconpath, hass))

    return True


async def async_get_mac_address_from_host(hass: HomeAssistant, host: str) -> str | None:
    """Get mac address from host."""
    mac_address: str | None

    # first we try if this is an ip address
    try:
        ip_addr = ip_address(host)
    except ValueError:
        # that didn't work, so try a hostname
        mac_address = await hass.async_add_executor_job(partial(get_mac_address, hostname=host))
    else:
        # it is an ip address, but it could be IPv4 or IPv6
        if ip_addr.version == 4:
            mac_address = await hass.async_add_executor_job(partial(get_mac_address, ip=host))
        else:
            ip_addr = IPv6Address(int(ip_addr))
            mac_address = await hass.async_add_executor_job(
                partial(get_mac_address, ip6=str(ip_addr))
            )
    if not mac_address:
        return None

    return format_mac(mac_address)


async def async_setup_entry(hass: HomeAssistant, entry: PhilipsConfigEntry) -> bool:
    """Set up the Philips AirPurifier integration."""

    host = entry.data[CONF_HOST]
    model = entry.data[CONF_MODEL]
    name = entry.data[CONF_NAME]
    device_id = entry.data[CONF_DEVICE_ID]

    # Defer MAC lookup - run in background after setup to avoid blocking startup
    async def get_mac_deferred() -> None:
        """Get MAC address in background and update device info."""
        try:
            mac = await asyncio.wait_for(async_get_mac_address_from_host(hass, host), timeout=3)
            if mac and entry.runtime_data:
                entry.runtime_data.device_information.mac = mac
                _LOGGER.debug("MAC address updated for %s: %s", host, mac)
        except Exception as ex:
            _LOGGER.debug("MAC lookup failed for %s: %s", host, ex)

    _LOGGER.debug("async_setup_entry called for host %s", host)

    # Old entries may not have a stored status yet. Fetch it before the
    # platforms are set up so they can initialise from real data.
    if CONF_STATUS not in entry.data:
        _LOGGER.warning("No status data found for model %s, trying to fetch it", model)
        try:
            client = await asyncio.wait_for(CoAPClient.create(host), timeout=5)
        except TimeoutError as ex:
            _LOGGER.warning("Timeout connecting to host %s after 5s", host)
            raise ConfigEntryNotReady from ex
        except Exception as ex:
            _LOGGER.warning("Failed to connect to host %s: %s", host, ex)
            raise ConfigEntryNotReady from ex
        coordinator = Coordinator(hass, client, host, None, config_entry=entry)
        try:
            await asyncio.wait_for(coordinator.async_first_refresh(), timeout=10)
        except TimeoutError as ex:
            _LOGGER.warning("Timeout fetching status for %s", host)
            raise ConfigEntryNotReady from ex
        status = coordinator.status

        # Update the entry with the status data
        new_data = {**entry.data}
        new_data[CONF_STATUS] = status
        hass.config_entries.async_update_entry(entry, data=new_data)
    else:
        # Modern entries carry the last known status, so the CoAP handshake can
        # run in the background instead of blocking Home Assistant startup.
        status = entry.data[CONF_STATUS]
        coordinator = Coordinator(hass, None, host, status, config_entry=entry)

    # Initialize device info without MAC (will be updated in background)
    device_information = DeviceInformation(
        host=host, mac=None, model=model, name=name, device_id=device_id
    )

    # Store runtime data in the config entry (new pattern)
    entry.runtime_data = ConfigEntryData(
        device_information=device_information,
        coordinator=coordinator,
        latest_status=status,
        client=coordinator.client,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Establish the CoAP connection in the background so a slow or unreachable
    # device never delays startup. The coordinator starts observing as soon as
    # the client is ready.
    if coordinator.client is None:
        entry.async_create_background_task(
            hass, coordinator.async_connect(), f"philips_connect_{host}"
        )

    # Start deferred MAC lookup in background (non-blocking, tied to the entry)
    entry.async_create_background_task(hass, get_mac_deferred(), "philips_mac_lookup")

    return True


async def async_unload_entry(hass: HomeAssistant, entry: PhilipsConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.coordinator.async_shutdown()

    return unload_ok
