"""Diagnostics hide account details and anything identifying the mower or the lawn."""
from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.imow_v2.const import DOMAIN
from custom_components.imow_v2.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacted(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    config_entry.add_to_hass(hass)
    mower = {
        "deviceId": "123456789",
        "device": {"serialNumber": "SN1", "cellularIMEI": "IMEI1", "overallState": {"state": "docked"}},
        "_settings": {"location": {"latitude": -43.5, "longitude": 172.6}, "ssid": "HomeWifi"},
        "setting": {"deviceNickname": "Blade"},
    }
    hass.data[DOMAIN] = {
        config_entry.entry_id: SimpleNamespace(
            data={"123456789": mower}, signalr=SimpleNamespace(connected=True), last_update_success=True
        )
    }

    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    text = repr(diag)
    for secret in ("old-password", "old-refresh-token", "owner@example.com", "123456789",
                   "SN1", "IMEI1", "-43.5", "172.6", "HomeWifi"):
        assert secret not in text
    assert diag["mowers"]["mower_1"]["device"]["overallState"] == {"state": "docked"}
    assert diag["mowers"]["mower_1"]["setting"]["deviceNickname"] == "Blade"
    assert diag["entry"]["options"] == {"scan_interval": 10, "tracking_interval": 60}
    assert diag["signalr_connected"] is True
