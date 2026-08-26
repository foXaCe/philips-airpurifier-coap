# Philips CoAP property map

How the same function is named across the three generations of Philips
devices, reconstructed by observing the wire format the official Philips
Air+ / Air Matters app exercises on the local network.

This document describes **the format of the messages exchanged on the local
network**, so that this integration can talk to the devices — an
interoperability reference. No code and no resource from the application is
reproduced here.

Three naming schemes coexist:

| Generation | Key shape | Example devices |
|---|---|---|
| `legacy` | short words (`pwr`, `om`, `pm25`) | AC2889, AC3059… |
| `new` | `D0x-yy` | AC0850, AC1715 |
| `new2` | `D0xyyy` | AC3033, AC3737, CX5120… |

## Common properties

| Function | `legacy` | `new` | `new2` | Notes |
|---|---|---|---|---|
| Power | `pwr` (`"1"`/`"0"`) | `D03-02` (`"ON"`/`"OFF"`) | `D03102` (`1`/`0`) | |
| Child lock | `cl` (boolean) | `D03-03` (boolean) | `D03103` (`1`/`0`) | |
| Light brightness | `aqil` | `D03-04` | `D03104` | 0–100 |
| Display backlight | `uil` | `D03-05` | `D03105` | written together with the brightness |
| Mode | `mode` | `D03-12` | `D0310C` | |
| Fan speed | `om` (`"s"`,`"1"`…`"t"`) | `D03-13` (same values) | `D0310D` | |
| Allergen index (IAI) | `iaql` | `D03-32` | `D03120` | |
| PM2.5 | `pm25` | `D03-33` | `D03221` | |
| Gas / TVOC | `tvoc` | `D03-34` | `D03122` | |
| Temperature | `temp` | `D03-36` | `D03224` | **`new2` is in tenths of a degree** |
| Humidity | `rh` | `D03-37` | `D03125` | |
| Target humidity | `rhset` | — | `D03128` | |
| Preferred index | `ddp` | `D03-42` | `D0312A` | |
| Air-quality threshold | `aqit` | `D03-44` | `D0312C` | |
| Error field | `err` | `D03-64` | `D03240` | see below |
| Timer | `dt` | — | `D03110` | |
| Time remaining | `dtrs` | — | `D03211` | |
| Oscillation | — | — | `D0320F` | |
| Beep | — | — | `D03130` | |
| Range / model name | `range` | `D01-04` | `D01S04` | |
| Language | `language` | `D01-07` | `D01107` | |

## Filters

| Filter | `legacy` state | `legacy` total | `new` state | `new` total | `new2` state | `new2` total |
|---|---|---|---|---|---|---|
| Pre-filter | `fltsts0` | `flttotal0` | `D05-13` | `D05-07` | `D0520D` | `D05207` |
| HEPA / NanoProtect | `fltsts1` | `flttotal1` | `D05-14` | `D05-08` | `D0540E` | `D05408` |
| Active carbon | `fltsts2` | `flttotal2` | `D05-15` | `D05-09` | `D0540F` | `D05409` |
| Wick (humidifier) | `wicksts` | `wicktotal` | — | — | `D05213` | `D05212` |

The filter type is carried by `fltt0`/`fltt1`/`fltt2` on `legacy`, `D05-02` on
`new` and `D05102` on `new2`.

## Error field

`err` (`legacy`), `D03-64` (`new`) and `D03240` (`new2`) carry a bitfield. The
app does not map values to labels: it tests bit patterns, and raises the
condition when **every** bit of a pattern is set.

| Pattern | Bits | Condition |
|---|---|---|
| `32781` or `32782` | 0 or 1, plus 2, 3, 15 | no filter detected — missing, installed incorrectly, or unreadable tag |
| `49408` | 7, 8, 14, 15 | water tank needs refilling (the app also requires the measured humidity to be below the target) |
| `193` or `49153` | 0, 6, 7 — or 0, 14, 15 | a condition on the pre-filter |
| `49184` | 5, 14, 15 | a condition on the filter set, first level |
| `49216` | 6, 14, 15 | a condition on the filter set, second level |

Bits 14 and 15 behave like a warning prefix: they appear in most patterns and
never suffice on their own.

Only the first two patterns are used by the integration; the meaning of the
last three is not established with certainty.

## Transport and recovery

Every request is a non-confirmable CoAP message on port 5683.

| Resource | Purpose |
|---|---|
| `/sys/dev/sync` | nonce exchange; the device answers with the starting counter |
| `/sys/dev/status` | current state, and the `observe` subscription for pushes |
| `/sys/dev/control` | sending commands |
| `/sys/dev/info/tls` | key exchange for TLS-capable devices |
| `224.0.1.187:5683/sys/dev/info` | multicast discovery |
| `224.0.1.187:5683/sys/dev/info/encryption` | discovery of encrypted devices |

### Freshness window

Every message carries a 4-byte counter in its header. A message is accepted
when its id lies **between the last retained id and that id plus 10**, taking
the counter wrap at 2,000,000,000 into account.

An id **equal** to the last retained one is accepted: a device answering a
fresh request with its current counter, or a duplicated UDP datagram, is not a
replay. Only ids that fall behind, or jump too far ahead, are rejected.

Past the maximum, the reference restarts at 1.

### Recovery

The app treats any rejection — id outside the window, bad digest, failed
decryption — as a **lost connection**: it marks the device offline, and a
watchdog thread sends a CoAP `ping` every 3 seconds with a 10-second timeout.
When the device comes back it **re-runs the `sync`** before resuming; the RSA
key pair is kept and the TLS exchange is not replayed.

That re-sync is essential: a device that reboots restarts from a counter far
below the last id seen, and without a new synchronisation every subsequent
message stays outside the window — the stream never recovers on its own.

## Observed but unidentified keys

These keys appear in the exchanges without their meaning being established.
They are recorded so the analysis does not have to be redone.

| Key | Observation |
|---|---|
| `D01102` | device capability class; some functions are gated on its value |
| `D0110C` | capability bitfield (tested by mask) |
| `D01108` | integer, defaults to 2 |
| `D03115` | equals 1 when the sleep mode is the allergen variant |
| `D03129`, `D0313A`–`D0313C`, `D03136`, `D03182` | feature flags |
| `D031C1`, `D031C2`, `D031C3` | triplet related to scheduling |
| `D0310B` | personalisation |
| `D03106`, `D0312E`, `D0312F` | backlight variants, depending on the model |
| `D03123` (`new2`) / `D03-35` (`new`) | numeric reading, matched across generations |
| `D03133` | boolean, active by default when the key is absent |
| `D05410`, `D0540A`, `D05103` | a second set of filter counters on some models |
