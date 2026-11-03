"""Verify fan/swing values: icons, labels, legacy aliases, frames and force_send."""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from homeassistant.components.climate import HVACMode  # noqa: E402

from custom_components.mitsubishi_remote import climate as C  # noqa: E402

COMPONENT = ROOT / "custom_components" / "mitsubishi_remote"
# The class attribute is a property object, so read the key from an instance.
KEY = C.MitsubishiRemoteClimate(
    remote_entity="remote.k", name="k", retries=1, repeat_gap=0.0
).translation_key
# HA core's icon map for climate state attributes (copied from 2025.1.4).
HA_ICONS = json.loads((Path(__file__).with_name("climate_icons.json")).read_text())[
    "entity_component"]["_"]["state_attributes"]
# This integration's own icons and labels, found through the translation_key.
OWN_ICONS = json.loads((COMPONENT / "icons.json").read_text())["entity"]["climate"][
    KEY]["state_attributes"]
OWN_LABELS = json.loads((COMPONENT / "translations" / "en.json").read_text())["entity"][
    "climate"][KEY]["state_attributes"]


def icon_for(attribute: str, value: str) -> str | None:
    """Replicate the frontend: integration icon first, then HA's map, else None."""
    own = OWN_ICONS.get(attribute, {}).get("state", {}).get(value)
    return own or HA_ICONS[attribute]["state"].get(value)


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


def make_entity(hass, entity_id):
    entity = C.MitsubishiRemoteClimate(
        remote_entity="remote.tuya", name="Bedroom AC", retries=1, repeat_gap=0.0,
    )
    entity.hass = hass
    entity.entity_id = entity_id
    entity.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    entity.sent = []

    async def fake_send(frame):
        entity.sent.append(frame)

    entity._send = fake_send  # type: ignore[assignment]
    return entity


async def main():
    hass = Hass()
    entity = make_entity(hass, "climate.bedroom_ac")
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {label}{'  ' + str(detail) if detail else ''}")

    # --- 1. every advertised value has an icon and a label ---
    print("-- icons and labels --")
    for attribute, values in (
        ("fan_mode", entity._attr_fan_modes),
        ("swing_mode", entity._attr_swing_modes),
        ("swing_horizontal_mode", entity._attr_swing_horizontal_modes),
    ):
        for value in values:
            icon = icon_for(attribute, value)
            check(f"{attribute} {value!r} -> {icon}", icon is not None, "FALLBACK DOT")
            label = OWN_LABELS[attribute]["state"].get(value)
            check(f"{attribute} {value!r} has a label", bool(label))

    # --- 2. legacy aliases map to the current values ---
    print("-- alias normalisation --")
    for raw, canon in [
        ("Auto", "auto"), ("Low", "low"), ("Med", "medium"), ("High", "high"),
        ("MEDIUM", "medium"), (" high ", "high"), ("super_high", "super_high"),
    ]:
        got = C.normalise_fan_mode(raw)
        check(f"fan {raw!r} -> {got!r}", got == canon, f"expected {canon!r}")
    for raw, canon in [
        ("on", "swing"), ("off", "auto"), ("Swing", "swing"), ("vertical", "swing"),
        ("auto", "auto"), ("POS2", "pos2"),
    ]:
        got = C.normalise_swing_mode(raw)
        check(f"swing {raw!r} -> {got!r}", got == canon, f"expected {canon!r}")
    for raw, canon in [
        ("off", "area_auto"), ("on", "swing"), ("horizontal", "swing"),
        ("Center", "center"), ("area_right", "area_right"),
    ]:
        got = C.normalise_swing_horizontal_mode(raw)
        check(f"swing_horizontal {raw!r} -> {got!r}", got == canon, f"expected {canon!r}")
    check("junk fan -> None", C.normalise_fan_mode("turbo") is None)
    check("junk swing -> None", C.normalise_swing_mode("weird") is None)
    check("junk swing_horizontal -> None", C.normalise_swing_horizontal_mode("up") is None)

    # --- 3. frames: FAN in byte 9 bits 2-0, VANE in bits 5-3, bit 6 = 1 ---
    print("-- frames --")
    entity._power = True
    entity._active_mode = HVACMode.COOL
    expected_fan = {"auto": 0x40, "low": 0x41, "medium": 0x42, "high": 0x43, "super_high": 0x44}
    for label, value in expected_fan.items():
        entity._attr_fan_mode = label
        b9 = entity._current_code()[9]
        check(f"fan {label} -> byte 9 {value:#04x}", b9 == value, hex(b9))
    entity._attr_fan_mode = "High"
    check("legacy 'High' encodes as 'high'", entity._current_code()[9] == 0x43)

    entity._attr_fan_mode = "auto"
    expected_vane = {
        "auto": 0x40, "pos1": 0x48, "pos2": 0x50, "pos3": 0x58,
        "pos4": 0x60, "pos5": 0x68, "swing": 0x78,
    }
    for label, value in expected_vane.items():
        entity._attr_swing_mode = label
        b9 = entity._current_code()[9]
        check(f"swing {label} -> byte 9 {value:#04x}", b9 == value, hex(b9))
    entity._attr_swing_mode = "on"
    check("legacy 'on' encodes as 'swing'", entity._current_code()[9] == 0x78)

    # --- 4. setters store canonical values ---
    print("-- setters canonicalise --")
    await entity.async_set_fan_mode("High")
    check("set_fan_mode('High') stored as 'high'", entity._attr_fan_mode == "high")
    await entity.async_set_fan_mode("nonsense")
    check("set_fan_mode(junk) falls back to 'auto'", entity._attr_fan_mode == "auto")
    await entity.async_set_swing_mode("on")
    check("set_swing_mode('on') stored as 'swing'", entity._attr_swing_mode == "swing")
    await entity.async_set_swing_mode("nonsense")
    check("set_swing_mode(junk) falls back to 'auto'", entity._attr_swing_mode == "auto")

    # --- 5. restore migrates values from earlier versions ---
    print("-- restore migration --")

    class Extra:
        def __init__(self, d):
            self._d = d

        def as_dict(self):
            return self._d

    e2 = make_entity(hass, "climate.x")

    async def get_extra():
        return Extra({
            "active_mode": "heat", "hvac_mode": "heat", "target_temperature": 23,
            "fan_mode": "High", "swing_mode": "on", "swing_horizontal_mode": "off",
        })

    async def get_state():
        return None

    e2.async_get_last_extra_data = get_extra  # type: ignore[assignment]
    e2.async_get_last_state = get_state  # type: ignore[assignment]
    await e2.async_added_to_hass()
    check("restored fan 'High' -> 'high'", e2._attr_fan_mode == "high", e2._attr_fan_mode)
    check("restored swing 'on' -> 'swing'", e2._attr_swing_mode == "swing", e2._attr_swing_mode)
    check("restored swing_horizontal 'off' -> 'area_auto'",
          e2._attr_swing_horizontal_mode == "area_auto", e2._attr_swing_horizontal_mode)
    check("restore sent no IR", e2.sent == [])

    # --- 6. force_send service registration and dispatch ---
    print("-- force_send service --")
    config = {"remote_entity": "remote.tuya", "name": "Bedroom AC", "retries": 1,
              "repeat_gap": 0.0}
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

    async def call(**data):
        await handler(type("Call", (), {"data": data})())

    await call(hvac_mode="heat", temperature=22, fan_mode="high", power=True)
    check("force_send emitted 1 frame", len(sent3) == 1, len(sent3))
    check("force_send frame is HEAT (MODE field = 0b001)",
          sent3 and sent3[0][6] & 0x38 == 0x08, hex(sent3[0][6]))

    sent3.clear()
    await call(hvac_mode="cool", temperature=24, fan_mode="Med", power=True)
    check("force_send accepts legacy 'Med'", sent3 and sent3[0][9] == 0x42, hex(sent3[0][9]))

    sent3.clear()
    await call(entity_id="climate.bedroom_ac", hvac_mode="cool", temperature=24, fan_mode="low")
    check("targeted call emits 1 frame", len(sent3) == 1)
    sent3.clear()
    await call(entity_id="climate.nope", hvac_mode="cool", temperature=24)
    check("unknown target emits nothing", sent3 == [])

    # A YAML reload must not register twice or send twice.
    try:
        await C.async_setup_platform(hass, config, add_entities)
        check("reload: no duplicate registration", True)
    except Exception as exc:  # noqa: BLE001
        check("reload: no duplicate registration", False, exc)
    sent3.clear()
    await call(hvac_mode="cool", temperature=24, fan_mode="low")
    check("reload: still 1 frame, not 2", len(sent3) == 1, len(sent3))

    sent3.clear()
    await call(hvac_mode="off", temperature=24, fan_mode="low", power=True)
    check("hvac_mode off forces power bit off", sent3 and sent3[0][5] & 0x20 == 0)

    print()
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
