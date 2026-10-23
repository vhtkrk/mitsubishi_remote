"""Regression: state restoration after reboot (last turn's work) still holds."""

import asyncio
import json
import sys
from pathlib import Path

CC = Path("/home/user/mitsubishi_remote/custom_components/mitsubishi_remote")
sys.path.insert(0, str(CC.parent))

from homeassistant.components.climate import HVACMode  # noqa: E402
from homeassistant.helpers.restore_state import RestoredExtraData  # noqa: E402

from mitsubishi_remote import climate as C  # noqa: E402

ok = True


def check(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")


class Extra:
    def __init__(self, d):
        self._d = d

    def as_dict(self):
        return self._d


class State:
    def __init__(self, state, attrs):
        self.state = state
        self.attributes = attrs


def make(**kw):
    e = C.MitsubishiRemoteClimate(
        remote_entity="remote.tuya", name="AC", command_format="hex",
        hex_prefix=False, retries=1, repeat_gap=0.0,
    )
    e.hass = type("H", (), {"data": {}})()
    e.entity_id = "climate.ac"
    e.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    e.sent = []

    async def send(frame):
        e.sent.append(frame)

    e._send = send  # type: ignore[assignment]
    for k, v in kw.items():
        setattr(e, k, v)
    return e


async def restore(entity, extra=None, state=None):
    async def g_extra():
        return extra

    async def g_state():
        return state

    entity.async_get_last_extra_data = g_extra  # type: ignore[assignment]
    entity.async_get_last_state = g_state  # type: ignore[assignment]
    await entity.async_added_to_hass()


async def main():
    # 1. defaults when nothing stored, and no IR
    print("-- first run / no stored state --")
    e = make()
    await restore(e)
    check("default mode off", e._attr_hvac_mode == HVACMode.OFF)
    check("default temp 24", e._attr_target_temperature == 24)
    check("default fan auto", e._attr_fan_mode == "auto", e._attr_fan_mode)
    check("default swing off", e._attr_swing_mode == "off")
    check("no IR on first run", e.sent == [])

    # 2. full restore from extra data, no IR
    print("-- full restore --")
    e = make()
    await restore(e, extra=Extra({
        "active_mode": "heat", "hvac_mode": "heat", "target_temperature": 23,
        "fan_mode": "high", "swing_mode": "on",
    }))
    check("mode restored", e._attr_hvac_mode == HVACMode.HEAT, e._attr_hvac_mode)
    check("active_mode restored", e._active_mode == HVACMode.HEAT)
    check("temp restored", e._attr_target_temperature == 23)
    check("fan restored", e._attr_fan_mode == "high")
    check("swing restored", e._attr_swing_mode == "on")
    check("power restored to on", e._power is True)
    check("restore sent no IR", e.sent == [])

    # 3. off state keeps the underlying mode so power-on returns to it
    print("-- off restores active mode --")
    e = make()
    await restore(e, extra=Extra({
        "active_mode": "heat", "hvac_mode": "off", "target_temperature": 22,
        "fan_mode": "low", "swing_mode": "off",
    }))
    check("shown as off", e._attr_hvac_mode == HVACMode.OFF)
    check("power flag off", e._power is False)
    check("active mode still heat", e._active_mode == HVACMode.HEAT)
    await e.async_set_hvac_mode(HVACMode.HEAT)
    check("power-on frame is heat", e.sent and e.sent[-1][6] & 0x0F == 0x08,
          hex(e.sent[-1][6]) if e.sent else "no frame")

    # 4. fallback to old-style last_state attributes only
    print("-- legacy last_state only --")
    e = make()
    await restore(e, state=State("cool", {
        "temperature": 20, "fan_mode": "low", "swing_mode": "off",
    }))
    check("mode from state", e._attr_hvac_mode == HVACMode.COOL, e._attr_hvac_mode)
    check("temp from attrs", e._attr_target_temperature == 20)
    check("fan from attrs", e._attr_fan_mode == "low")
    check("no IR", e.sent == [])

    # 5. garbage is sanitised, not fatal
    print("-- garbage sanitised --")
    e = make()
    await restore(e, extra=Extra({
        "active_mode": "banana", "hvac_mode": "banana",
        "target_temperature": 999, "fan_mode": "turbo", "swing_mode": "sideways",
    }))
    check("bad mode ignored", e._attr_hvac_mode == HVACMode.OFF)
    check("bad active ignored", e._active_mode == HVACMode.COOL)
    check("temp clamped to max", e._attr_target_temperature == 31,
          e._attr_target_temperature)
    check("bad fan -> default", e._attr_fan_mode == "auto")
    check("bad swing -> default", e._attr_swing_mode == "off")
    check("no IR", e.sent == [])

    # 6. non-numeric temp does not raise
    e = make()
    await restore(e, extra=Extra({
        "active_mode": "cool", "hvac_mode": "cool", "target_temperature": "warm",
        "fan_mode": "auto", "swing_mode": "off",
    }))
    check("bad temp text survives", e._attr_target_temperature == 24,
          e._attr_target_temperature)

    # 7. extra data round-trips through HA's real storage class + JSON
    print("-- storage round-trip --")
    e = make()
    e._active_mode = HVACMode.HEAT
    e._attr_hvac_mode = HVACMode.HEAT
    e._attr_target_temperature = 23
    e._attr_fan_mode = "high"
    e._attr_swing_mode = "on"
    blob = json.loads(json.dumps(e.extra_restore_state_data.as_dict()))
    check("as_dict is JSON-clean", blob["active_mode"] == "heat", blob)
    restored = RestoredExtraData(blob)
    check("RestoredExtraData round-trip", restored.as_dict() == blob)
    check("all keys present", set(blob) == {
        "active_mode", "hvac_mode", "target_temperature", "fan_mode", "swing_mode",
        "swing_horizontal_mode",
    }, sorted(blob))

    # 8. power-off preserves mode/temp/fan bytes (byte 5 only)
    print("-- power-off frame --")
    e = make()
    e._power = True
    e._active_mode = HVACMode.HEAT
    e._attr_hvac_mode = HVACMode.HEAT
    e._attr_target_temperature = 22
    e._attr_fan_mode = "low"
    on_frame = e._current_code()
    await e.async_set_hvac_mode(HVACMode.OFF)
    off_frame = e.sent[-1]
    check("byte 5 power bit cleared", on_frame[5] == 0x20 and off_frame[5] == 0x00)
    check("mode/temp/fan bytes preserved", on_frame[6:10] == off_frame[6:10],
          f"{on_frame[6:10].hex()} vs {off_frame[6:10].hex()}")

    # 9. cool -> heat retags the mode byte
    print("-- mode switch ordering --")
    e = make()
    e._power = True
    e._active_mode = HVACMode.COOL
    e._attr_hvac_mode = HVACMode.COOL
    await e.async_set_hvac_mode(HVACMode.HEAT)
    check("switching to heat emits heat", e.sent[-1][6] & 0x0F == 0x08,
          hex(e.sent[-1][6]))

    print()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
