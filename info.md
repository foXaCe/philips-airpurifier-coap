# Philips AirPurifier (with CoAP)

This is a `Local Push` integration for Philips air purifiers and humidifiers.
Currently only encrypted-CoAP is implemented.

## Features

- Local push over CoAP (no cloud required)
- Auto-discovery of purifiers (DHCP / SSDP based on MAC address and hostname)
- Fan, sensor, switch, select, light, climate, humidifier, number and binary
  sensor entities
- Automatic reconnection with a watchdog and a repair issue when the device
  stays unreachable

## Installation

1. Open HACS in Home Assistant
2. Add this repository as a custom repository (type: Integration)
3. Search for "Philips AirPurifier" and install
4. Restart Home Assistant

## Configuration

The integration attempts to autodiscover your purifiers. Alternatively:

1. Go to Configuration → Devices & Services
2. Click `Add Integration`
3. Search for "Philips AirPurifier"

See the [README](https://github.com/foXaCe/philips-airpurifier-coap#readme)
for the full documentation.
