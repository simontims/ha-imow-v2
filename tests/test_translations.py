"""Every entity translation_key needs a name in strings.json."""
import json
import re
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "imow_v2"
PLATFORMS = ("binary_sensor", "button", "device_tracker", "number", "sensor")


def test_en_matches_strings() -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text())
    en = json.loads((COMPONENT / "translations" / "en.json").read_text())
    assert en == strings


def test_every_translation_key_has_a_name() -> None:
    entity = json.loads((COMPONENT / "strings.json").read_text())["entity"]
    for platform in PLATFORMS:
        source = (COMPONENT / f"{platform}.py").read_text()
        keys = set(re.findall(r'translation_key(?: =|=) ?"([a-z_]+)"', source))
        assert keys, platform
        assert keys == set(entity[platform]), platform
        for key in keys:
            assert entity[platform][key]["name"]
