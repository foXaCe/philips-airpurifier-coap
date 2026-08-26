# Vendored: aioairctrl 0.3.1

This directory contains a vendored copy of [aioairctrl](https://github.com/kongo09/aioairctrl)
version **0.3.1** (MIT license, see `LICENSE`), the CoAP client library for
Philips air purifiers by betaboon and kongo09.

It is embedded in this integration instead of being pulled in as a PyPI
dependency so that protocol-level fixes and extensions can ship with the
integration without waiting for an upstream release. The CLI entry points
(`cli.py`, `__main__.py`) were intentionally not copied; only the library
surface (`Client`, `EncryptionContext`) is used.

## Deviations from upstream 0.3.1

- Absolute imports (`from aioairctrl...`) were rewritten to relative imports
  so the package works as a subpackage of the integration.
- No functional changes. Any future deviation from upstream must be listed here.

## Dependencies

The library requires `aiocoap>=0.4.17,<0.5` and `pycryptodomex`; both are
declared in `manifest.json` requirements.

## Upgrading

To upgrade, copy the new upstream `aioairctrl/coap/` sources over this
directory, re-apply the import rewrite above, update this note, and re-run
the test suite.
