# Changelog

All notable changes to the Philips AirPurifier CoAP integration will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Adopt `UnitOfDensity.MICROGRAMS_PER_CUBIC_METER` for the PM2.5 sensors:
  HA 2026.8 deprecates `CONCENTRATION_MICROGRAMS_PER_CUBIC_METER` (removal in
  2027.8) and logged a repair-style warning. A fallback keeps HA 2025.12-2026.6
  working, where the new enumerator does not exist yet. The unit string is
  unchanged, so recorded statistics are unaffected.

## [0.40.0] - 2026-07-17

### Changed
- **Home Assistant 2025.12.0 or newer is now required** (was 2024.12.0), and
  Python 3.13+ accordingly. This enables the native platform features below.
- Saving the integration options now reloads the entry through the options
  flow itself (`OptionsFlowWithReload`) instead of a global update listener.
  This removes the double reload that reauth, reconfigure and rediscovery
  triggered — a pattern Home Assistant deprecated in 2026.6 and will reject
  in 2026.12.
- Value-dependent sensor icons (temperature, water level, Wi-Fi signal) moved
  from Python code to native range-based icon translations in `icons.json`
  (HA 2025.6+). The filter sensors keep the in-code mechanism because two of
  them share the frozen `pre_filter` translation key with different icon
  tables.
- All numeric sensors now declare an explicit `suggested_display_precision`.
- The Wi-Fi signal (RSSI) diagnostic sensor is disabled by default for new
  installations, matching Home Assistant core conventions. Existing entities
  are not affected.
- The manifest now declares `"quality_scale": "gold"`.

### Fixed
- The gas/TVOC sensor (`gas_level`) and the target temperature number
  (`target_temperature`) were displayed without a name (literally `None` in
  the UI): their translation keys had been renamed in the code without
  updating `strings.json`, the translation files and `icons.json`. A new test
  now enforces code ↔ translations parity so this cannot regress.
- The bg, de, es, nl, ro and sk translations caught up on the 23 keys added
  in earlier releases (options, reauth/reconfigure steps, repair issue,
  filter-reset buttons, system health).
- The integration could permanently lose the device — no more status updates
  and every command failing — until Home Assistant was restarted. `aioairctrl`
  sends non-confirmable CoAP messages without any timeout, so a single lost UDP
  datagram during a watchdog reconnect left the coordinator waiting forever
  with the watchdog disarmed. Reconnects are now bounded by a 30s timeout and
  fall back to the normal retry loop. Control commands are bounded by the same
  timeout: instead of hanging the service call forever, they now fail with an
  error and immediately trigger a reconnect so the next command works.

## [0.39.1] - 2026-07-01

### Fixed
- A device already configured no longer logs a spurious `Timeout, host … looks
  like a Philips AirPurifier but doesn't answer` warning when it re-announces
  itself over DHCP or SSDP. The rediscovery is now aborted before probing, since
  the device only accepts the single CoAP connection already held by the
  coordinator. IP changes are still picked up and update the existing entry.

## [0.39.0] - 2026-07-01

### Changed
- Updated the bundled `aioairctrl` requirement from 0.2.5 to 0.3.1. Verified
  against a real AMF870 device: the CoAP status stream decrypts and parses
  correctly.

### Fixed
- A corrupt CoAP status packet (a truncated or mangled UDP datagram) no longer
  logs an `Error requesting data` error or briefly marks the device unavailable.
  The bad packet is discarded and the observe stream reconnects silently while
  the device keeps its last known state; a genuine connection loss still marks
  it unavailable.

## [0.38.2] - 2026-06-17

### Fixed
- Stopped logging a spurious `Error requesting data` error (and briefly flashing
  the device unavailable) on every watchdog reconnect. A reconnect intentionally
  drops the observe stream, so that case is now silent and the device keeps its
  last state; a genuine stream loss still marks it unavailable.

## [0.38.1] - 2026-06-17

### Fixed
- Control commands could stop working until Home Assistant was restarted. A
  transient observe-stream drop (a corrupted packet or a brief network blip)
  made the coordinator recreate the whole CoAP client; because `aioairctrl`
  shares one client context between observing and sending commands, this could
  leave the coordinator pointing at a shut-down client. The client is now left
  untouched on such drops, and only the watchdog performs a full reconnect.

## [0.38.0] - 2026-06-16

Full internal overhaul. The `unique_id` of every entity is unchanged, so existing
automations and history are preserved.

### Changed
- **Coordinator** now extends Home Assistant's `DataUpdateCoordinator` (push pattern via
  `async_set_updated_data`); the custom `Timer` was replaced by an `async_call_later`
  reconnect watchdog, and entities derive from `CoordinatorEntity`.
- **Entities** migrated from string-keyed `dict` descriptions to frozen
  `EntityDescription` dataclasses; the duplicated MRO walk is now `collect_class_attribute()`.
- **Config flow** uses `ConfigFlowResult` (not the deprecated `FlowResult`),
  `_get_reauth_entry()`/`_get_reconfigure_entry()` and `async_update_reload_and_abort()`.
- `const.py` reduced from 1066 to ~560 lines (pure constants); `model.py` from 126 to 24.

### Added
- Options flow to configure the filter-alert threshold per config entry.
- Filter-reset buttons: a `button` entity per resettable filter writes the filter's
  full life back to its counter (resets it to 100%, like the Philips Air+ app).
- Support for AC2210, AC2220, AC2221 and AC3021, plus a new DHCP discovery
  address (ported from upstream).
- Support for the AC4231, the HU4209/HU4210 humidifiers and the CX7550
  circulator (ported from upstream).
- Filter sensors expose a `measurement` state class so Home Assistant keeps
  long-term statistics for them.
- HVAC action and a detailed `heating_action` attribute for the CX3120/CX5120
  fan heaters (ported from upstream).
- Logbook descriptions for the filter-alert event, attached to the originating
  entity and rendered with the device name and filter percentage.
- A `py.typed` marker so the package ships its type information (Platinum
  strict-typing).
- A system health panel reporting the configured and connected device counts.
- `loggers` declared in `manifest.json`.
- Exhaustive pytest suite (100% coverage), enforced by a CI gate.
- Complete CI/CD: ruff, strict `mypy`, hassfest, HACS, Dependabot, issue/PR templates.
- Repair issue raised when a device stays unreachable, cleared once it reconnects.
- Translatable command-failure exceptions and a `fr` translation for them.
- Strict typing: the integration now passes `mypy --strict`.
- Documentation sections: removal, how data is updated, automation examples,
  known limitations and use cases.

### Fixed
- The network **scan flow never ran** (`async_show_progress` was missing its
  `progress_task`); scans now execute and a device can be picked.
- `light.is_on`/`brightness` could crash on `int(None)`; `light.async_turn_on` could raise
  `UnboundLocalError`.
- `switch.is_on` reported *on* when its key was absent; it now reports *unknown*.
- `select.current_option` returned the string `"None"` for unknown values; it now returns `None`.
- `climate.async_set_temperature` crashed when called without a temperature.
- `helpers.ping_sweep` always returned an empty set; `fan.async_set_percentage` could crash
  on an unknown speed.
- Device actions now raise `HomeAssistantError` on client failure.
- AC0950/AC0951 and AC3420/AC3421 fan presets, and the icon listing view
  (ported from upstream).
- CoAP now works on IPv4-only networks (forces the aiocoap `simple6` transport
  at import; ported from upstream).
- CX5120 oscillation used the wrong "D" value for the 5k series (ported from upstream).
- The coordinator now reconnects immediately when the CoAP observe stream is lost
  (corrupted packet or transient drop) instead of marking the device unavailable
  for a whole watchdog interval.
- Removed a duplicate "preferred index" select inherited by some models such as
  AC4220 (ported from upstream).
- Blocking network lookups during the scan now run in an executor, so they no
  longer block the event loop.

### Removed
- Dead code: `timer.py`, unused constants (`TEST_ON`, `DATA_KEY_*`, `FanUnits`, …) and
  redundant tooling (`[tool.black]`, `[tool.isort]`, `.flake8`).

## [0.37.0] - 2025-01-18

### Changed
- Optimized startup time with parallel operations
- Deferred MAC address lookup to background task (non-blocking)
- Added 5s timeout for CoAP client creation

### Fixed
- Pre-commit fixes and code quality improvements
- HA/HACS compliance fixes
- Complete missing translations for de, bg, nl, ro, sk

## [0.36.0] - 2025-01-17

### Added
- Spanish translation

### Fixed
- Capitalize 'Humidifying' state for consistency
- Replace ConfigEntryNotReady with proper abort in config flow

## [0.35.0] - 2025-01-04

### Added
- French translation
- Child lock support for AC303x family
- Water level sensor for AC3420
- Child lock for AC3858/50

### Fixed
- DhcpServiceInfo import deprecation
- Hassfest action configuration
- TVOC unit display

### Changed
- Major refactoring and new features
- Optimized network scan performance

## Previous Versions

For changes prior to version 0.35.0, please refer to the [commit history](https://github.com/kongo09/philips-airpurifier-coap/commits/master).
