"""Parity checks between the code, strings.json and the translation files.

These tests guard against the renamed-translation-key regression (a
``translation_key`` changed in the code without updating strings.json left
entities literally named ``None`` in the UI) and against translation files
drifting behind strings.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

import pytest

from custom_components.philips_airpurifier_coap import (
    binary_sensor,
    light,
    number,
    select,
    sensor,
    switch,
)
from custom_components.philips_airpurifier_coap.const import PAP, FanAttributes

COMPONENT_DIR = Path(__file__).parent.parent / "custom_components" / "philips_airpurifier_coap"
TRANSLATIONS_DIR = COMPONENT_DIR / "translations"
LANGUAGES = sorted(p.stem for p in TRANSLATIONS_DIR.glob("*.json"))

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _load(path: Path) -> dict[str, Any]:
    with path.open() as file:
        return json.load(file)


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten(value, dotted))
        else:
            out[dotted] = value
    return out


def _code_translation_keys() -> dict[str, set[str]]:
    """Collect the translation keys each platform declares in the code."""
    keys: dict[str, set[str]] = {
        "binary_sensor": {str(d.translation_key) for d in binary_sensor.BINARY_SENSOR_TYPES},
        "button": {f"{d.translation_key}_reset" for d in sensor.FILTER_TYPES},
        # The fan, climate and humidifier entities use the class-level
        # ``_attr_translation_key = PAP`` from devices/base.py (their entity
        # descriptions do not set one).
        "climate": {str(PAP)},
        "fan": {str(PAP)},
        "humidifier": {str(PAP)},
        "light": {str(d.translation_key) for d in light.LIGHT_TYPES},
        "number": {str(d.translation_key) for d in number.NUMBER_TYPES},
        "select": {str(d.translation_key) for d in select.SELECT_TYPES},
        "sensor": {str(d.translation_key) for d in sensor.SENSOR_TYPES}
        | {str(d.translation_key) for d in sensor.FILTER_TYPES},
        "switch": {str(d.translation_key) for d in switch.SWITCH_TYPES},
    }
    # The filter-alert binary sensor sets its translation key on the class.
    keys["binary_sensor"].add(str(FanAttributes.FILTER_NEEDS_ATTENTION))
    return keys


def test_all_code_translation_keys_exist_in_strings() -> None:
    """Every translation_key used by an entity must exist in strings.json."""
    strings = _load(COMPONENT_DIR / "strings.json")
    entity_strings = strings.get("entity", {})

    problems: list[str] = []
    for platform, keys in _code_translation_keys().items():
        declared = set(entity_strings.get(platform, {}))
        for missing in sorted(keys - declared):
            problems.append(f"entity.{platform}.{missing} missing in strings.json")
        for orphan in sorted(declared - keys):
            problems.append(f"entity.{platform}.{orphan} in strings.json but unused in code")

    assert not problems, "\n".join(problems)


def test_strings_and_en_translation_are_identical() -> None:
    """translations/en.json must be an exact copy of strings.json."""
    strings = _flatten(_load(COMPONENT_DIR / "strings.json"))
    en = _flatten(_load(TRANSLATIONS_DIR / "en.json"))
    assert strings == en


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_file_parity(language: str) -> None:
    """Each translation file mirrors en.json keys and placeholders exactly."""
    en = _flatten(_load(TRANSLATIONS_DIR / "en.json"))
    translated = _flatten(_load(TRANSLATIONS_DIR / f"{language}.json"))

    assert set(translated) == set(en), (
        f"{language}.json keys diverge from en.json: "
        f"missing={sorted(set(en) - set(translated))} "
        f"extra={sorted(set(translated) - set(en))}"
    )

    for dotted, english in en.items():
        expected = sorted(_PLACEHOLDER.findall(str(english)))
        actual = sorted(_PLACEHOLDER.findall(str(translated[dotted])))
        assert actual == expected, (
            f"{language}.json placeholder mismatch at {dotted}: {actual} != {expected}"
        )


def test_icons_json_keys_match_code() -> None:
    """Icon translation keys must reference translation keys the code uses."""
    icons = _load(COMPONENT_DIR / "icons.json").get("entity", {})
    code_keys = _code_translation_keys()

    problems: list[str] = []
    for platform, entries in icons.items():
        known = code_keys.get(platform)
        if known is None:
            continue
        for orphan in sorted(set(entries) - known):
            problems.append(f"icons.json entity.{platform}.{orphan} unused in code")

    assert not problems, "\n".join(problems)
