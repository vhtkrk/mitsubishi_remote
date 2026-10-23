"""Verify fan/swing icon vocabulary, legacy aliases, and force_send registration."""

import asyncio
import json
import sys
from pathlib import Path

CC = Path("/home/user/mitsubishi_remote/custom_components/mitsubishi_remote")
sys.path.insert(0, str(CC.parent))

from homeassistant.components.climate import HVACMode  # noqa: E402

from mitsubishi_remote import climate as C  # noqa: E402

# Icons as published by HA core for the climate component's state attributes.
ICONS = json.load(
    Path(__file__).with_name("climate_icons.json").open()
)["entity_component"]["_"]["state_attributes"]


def icon_for(attribute: str, value: str):
    """Replicate frontend getIconFromTranslations: exact state, else default."""
    node = ICONS[attribute]
    return node["state"].get(value, node["default"])


class Services:
    def __init__(self):
        self.registered = {}
        self.calls = []

    def has_service(self, domain, service):
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler):
        self.registered[(domain, service)] = handler


class Hass:
    def __init__(self):
        self.services = Services()
        self.data = {}
        self.created = []

    def async_create_task(self, coro):
        # async_setup_platform schedules the switch-platform load; the stub just
        # records and closes it so no coroutine is left un-awaited.
        self.created.append(coro)
        coro.close()


async def main():
    hass = Hass()
    entity = C.MitsubishiRemoteClimate(
        remote_entity="remote.tuya",
        name="Bedroom AC",
        command_format="hex",
        hex_prefix=False,
        retries=1,
        repeat_gap=0.0,
    )
    entity.hass = hass
    entity.entity_id = "climate.bedroom_ac"
    entity.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    sent = []

    async def fake_send(frame):
        sent.append(frame)

    entity._send = fake_send  # type: ignore[assignment]

    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")

    # --- 1. every fan mode resolves to a real icon, not the fallback dot ---
    print("-- fan mode icons --")
    dot = ICONS["fan_mode"]["default"]
    for mode in C.FAN_MODES:
        icon = icon_for("fan_mode", mode)
        check(f"fan {mode!r} -> {icon}", icon != dot, "" if icon != dot else "FALLBACK DOT")

    # --- 2. swing modes resolve too (the reported bug) ---
    print("-- swing mode icons --")
    sdot = ICONS["swing_mode"]["default"]
    for mode in C.SWING_MODES:
        icon = icon_for("swing_mode", mode)
        check(f"swing {mode!r} -> {icon}", icon != sdot, "" if icon != sdot else "FALLBACK DOT")

    # --- 3. entity's own advertised attributes are all icon-resolvable ---
    print("-- entity advertises only resolvable values --")
    for mode in entity._attr_fan_modes:
        check(f"advertised fan {mode!r}", icon_for("fan_mode", mode) != dot)
    for mode in entity._attr_swing_modes:
        check(f"advertised swing {mode!r}", icon_for("swing_mode", mode) != sdot)

    # --- 4. legacy aliases still accepted + protocol codes unchanged ---
    print("-- legacy alias normalisation --")
    for legacy, canon in [
        ("Auto", "auto"), ("Low", "low"), ("Med", "medium"), ("High", "high"),
        ("MEDIUM", "medium"), (" high ", "high"),
    ]:
        got = C.normalise_fan_mode(legacy)
        check(f"fan {legacy!r} -> {got!r}", got == canon, f"expected {canon!r}")
    for legacy, canon in [
        ("swing", "on"), ("on", "on"), ("off", "off"), ("auto", "off"),
        ("Swing", "on"), ("vertical", "on"),
    ]:
        got = C.normalise_swing_mode(legacy)
        check(f"swing {legacy!r} -> {got!r}", got == canon, f"expected {canon!r}")

    check("junk fan -> None", C.normalise_fan_mode("turbo") is None)
    check("junk swing -> None", C.normalise_swing_mode("weird") is None)

    # --- 5. protocol frames: fan codes must not have changed meaning ---
    print("-- protocol frames unchanged --")
    entity._power = True
    entity._active_mode = HVACMode.COOL
    entity._attr_target_temperature = 24
    frames = {}
    for label in ["auto", "low", "medium", "high"]:
        entity._attr_fan_mode = label
        frames[label] = entity._current_code()
    # data[9] = fan (bits 0-2) | vertical vane (bits 3-6), two DISJOINT
    # fields. With the vane left at auto (0x40) the speeds are
    # 0x40/0x41/0x42/0x43. (The pre-fix code treated 0x68 as the fan base,
    # which actually encodes vane=BOTTOM, so every command pinned the vane.)
    fan_bytes = {k: v[9] for k, v in frames.items()}
    check("fan byte auto", fan_bytes["auto"] == 0x40, hex(fan_bytes["auto"]))
    check("fan byte low", fan_bytes["low"] == 0x41, hex(fan_bytes["low"]))
    check("fan byte medium", fan_bytes["medium"] == 0x42, hex(fan_bytes["medium"]))
    check("fan byte high", fan_bytes["high"] == 0x43, hex(fan_bytes["high"]))
    check("distinct fan bytes", len(set(fan_bytes.values())) == 4)

    # legacy label must encode identically to canonical
    entity._attr_fan_mode = "High"
    legacy_frame = entity._current_code()
    check("legacy 'High' encodes as 'high'", legacy_frame == frames["high"])

    # swing
    entity._attr_fan_mode = "high"
    entity._attr_swing_mode = "on"
    on_frame = entity._current_code()
    entity._attr_swing_mode = "off"
    off_frame = entity._current_code()
    check("swing on != off", on_frame != off_frame)
    # vertical vane lives in bits 3-6 and swing is 0x78; bit 7 is unused, so
    # the old 0x80 "swing" only ever set a dead bit and parked the louvre.
    check("swing on sets vane 0x78", (on_frame[9] & 0x78) == 0x78, hex(on_frame[9]))
    check("swing on does not set unused bit 7", not (on_frame[9] & 0x80), hex(on_frame[9]))
    check("swing off parks vane at auto 0x40", (off_frame[9] & 0x78) == 0x40, hex(off_frame[9]))
    entity._attr_swing_mode = "swing"
    check("legacy 'swing' encodes as 'on'", entity._current_code() == on_frame)

    # --- 6. setters store canonical values ---
    print("-- setters canonicalise --")
    await entity.async_set_fan_mode("High")
    check("set_fan_mode('High') stored as 'high'", entity._attr_fan_mode == "high")
    await entity.async_set_fan_mode("nonsense")
    check("set_fan_mode(junk) falls back to 'auto'", entity._attr_fan_mode == "auto")
    await entity.async_set_swing_mode("swing")
    check("set_swing_mode('swing') stored as 'on'", entity._attr_swing_mode == "on")
    await entity.async_set_swing_mode("nonsense")
    check("set_swing_mode(junk) falls back to 'off'", entity._attr_swing_mode == "off")

    # --- 7. restore migrates pre-0.2 persisted values ---
    print("-- restore migration --")

    class Extra:
        def __init__(self, d):
            self._d = d

        def as_dict(self):
            return self._d

    e2 = C.MitsubishiRemoteClimate(
        remote_entity="remote.tuya", name="X", command_format="hex",
        hex_prefix=False, retries=1, repeat_gap=0.0,
    )
    e2.hass = hass
    e2.entity_id = "climate.x"
    e2.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    sent2 = []

    async def fake_send2(frame):
        sent2.append(frame)

    e2._send = fake_send2  # type: ignore[assignment]

    async def get_extra():
        return Extra({
            "active_mode": "heat", "hvac_mode": "heat",
            "target_temperature": 23, "fan_mode": "High", "swing_mode": "swing",
        })

    async def get_state():
        return None

    e2.async_get_last_extra_data = get_extra  # type: ignore[assignment]
    e2.async_get_last_state = get_state  # type: ignore[assignment]
    await e2.async_added_to_hass()
    check("restored fan 'High' -> 'high'", e2._attr_fan_mode == "high", e2._attr_fan_mode)
    check("restored swing 'swing' -> 'on'", e2._attr_swing_mode == "on", e2._attr_swing_mode)
    check("restore sent no IR", sent2 == [])

    # --- 8. force_send service registration & dispatch ---
    print("-- force_send service --")
    config = {"remote_entity": "remote.tuya", "name": "Bedroom AC",
              "command_format": "hex", "retries": 1, "repeat_gap": 0.0}
    added = []

    def add_entities(ents, **kw):  # sync callback, like HA's
        added.extend(ents)

    await C.async_setup_platform(hass, config, add_entities)
    check("service registered", hass.services.has_service("mitsubishi_remote", "force_send"))
    check("entity added", len(added) == 1)

    live = added[0]
    live.hass = hass
    # HA assigns entity_id during add; simulate that for the service lookup.
    live.entity_id = "climate.bedroom_ac"
    live.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    sent3 = []

    async def fake_send3(frame):
        sent3.append(frame)

    live._send = fake_send3  # type: ignore[assignment]

    handler = hass.services.registered[("mitsubishi_remote", "force_send")]
    await handler(type("Call", (), {"data": {
        "hvac_mode": "heat", "temperature": 22, "fan_mode": "high", "power": True,
    }})())
    check("force_send emitted 1 frame", len(sent3) == 1, len(sent3))
    check("force_send frame is heat", sent3 and sent3[0][6] & 0x0F == 0x08, hex(sent3[0][6]))

    # legacy lowercase/old-style fan value in the service call
    sent3.clear()
    await handler(type("Call", (), {"data": {
        "hvac_mode": "cool", "temperature": 24, "fan_mode": "Med", "power": True,
    }})())
    # byte 9 is fan(bits 0-2) | vane(bits 3-6); with the vane left at auto
    # (0x40) medium is 0x40 | 0x02 = 0x42. The old expectation of 0x6A came
    # from the pre-fix encoding where 0x68 was mistaken for the fan base.
    check("force_send accepts legacy 'Med'", sent3 and sent3[0][9] == 0x42, hex(sent3[0][9]))

    # entity targeting + junk target
    sent3.clear()
    await handler(type("Call", (), {"data": {
        "entity_id": "climate.bedroom_ac", "hvac_mode": "cool", "temperature": 24,
        "fan_mode": "low",
    }})())
    check("targeted call emits 1 frame", len(sent3) == 1)
    sent3.clear()
    await handler(type("Call", (), {"data": {
        "entity_id": "climate.nope", "hvac_mode": "cool", "temperature": 24,
    }})())
    check("unknown target emits nothing", sent3 == [])

    # reload must not double-register or double-send
    try:
        await C.async_setup_platform(hass, config, add_entities)
        check("reload: no duplicate registration", True)
    except Exception as exc:  # noqa: BLE001
        check("reload: no duplicate registration", False, exc)
    sent3.clear()
    await handler(type("Call", (), {"data": {
        "hvac_mode": "cool", "temperature": 24, "fan_mode": "low",
    }})())
    check("reload: still 1 frame, not 2", len(sent3) == 1, len(sent3))

    # power=False on hvac_mode off
    sent3.clear()
    await handler(type("Call", (), {"data": {
        "hvac_mode": "off", "temperature": 24, "fan_mode": "low", "power": True,
    }})())
    check("hvac_mode off forces power bit off", sent3 and sent3[0][5] & 0x20 == 0)

    print()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
