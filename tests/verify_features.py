"""Regression tests for the i-see / clean / plasma switch entities.

Covers the three feature bits, the climate entity's ownership of them, the
`async_load_platform` hand-off that creates the switches, and restoration
(which must never transmit).

Run with:
    uv run --with 'homeassistant==2025.1.4' python tests/verify_features.py
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.mitsubishi_remote.climate import (  # noqa: E402
    MitsubishiRemoteClimate,
)
from custom_components.mitsubishi_remote.const import (  # noqa: E402
    DATA_SWITCHES,
    FEATURE_DEFAULTS,
    FEATURE_KEYS,
)
from custom_components.mitsubishi_remote.mitsubishi_protocol import (  # noqa: E402
    CleanMode,
    ClimateMode,
    FanMode,
    ISeeMode,
    PlasmaMode,
    PowerfulMode,
    InstallPosition,
    VanneVerticalMode,
    build_frame,
    validate_byte15_fields,
)
from custom_components.mitsubishi_remote.switch import (  # noqa: E402
    FEATURES,
    MitsubishiFeatureSwitch,
    feature_switches_for,
)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((bool(condition), name))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not condition else ""))


def checksum_ok(frame: bytes) -> bool:
    return frame[17] == sum(frame[:17]) % 256


def build(**kw):
    opts = {"clock": 0}
    opts.update(kw)
    return build_frame(
        climate_mode=ClimateMode.COLD,
        temperature=24,
        fan_mode=FanMode.AUTO,
        vanne_vertical_mode=VanneVerticalMode.AUTO,
        **opts,
    )


# --- fakes -----------------------------------------------------------------

class FakeState:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attributes: dict = {}


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.registered: dict[tuple[str, str], object] = {}

    async def async_call(self, domain, service, data, blocking=False):
        self.calls.append((domain, service, data))

    def has_service(self, domain, service) -> bool:
        return (domain, service) in self.registered

    def async_register(self, domain, service, handler) -> None:
        self.registered[(domain, service)] = handler


class FakeHass:
    def __init__(self) -> None:
        self.services = FakeServices()
        self.data: dict = {}
        self.created: list = []

    def async_create_task(self, coro):
        self.created.append(coro)
        coro.close()


def make_climate(**kw) -> MitsubishiRemoteClimate:
    entity = MitsubishiRemoteClimate(
        remote_entity="remote.blaster",
        name="Study AC",
        command_format="hex",
        hex_prefix=False,
        retries=1,
        repeat_gap=0.0,
        **kw,
    )
    entity.hass = FakeHass()
    entity.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    entity.entity_id = "climate.study_ac"
    return entity


def make_switch(climate, key, last_state=None) -> MitsubishiFeatureSwitch:
    sw = MitsubishiFeatureSwitch(climate, key)
    sw.hass = FakeHass()
    sw.async_write_ha_state = lambda *a, **k: None  # type: ignore[assignment]
    sw.entity_id = f"switch.study_ac_{key}"

    # `async_get_last_state` is the seam HA provides, and the same one the other
    # suites override. Stubbing it here avoids standing up HA's real Store
    # machinery just to test restoration logic.
    async def _last_state():
        return last_state

    sw.async_get_last_state = _last_state  # type: ignore[assignment]
    return sw


def frames_sent(climate) -> list:
    return [c[2]["command"] for c in climate.hass.services.calls]


# --- tests -----------------------------------------------------------------

def test_bit_values() -> None:
    check("i-see is byte 6 bit 6", ISeeMode.ON == 0x40)
    check("clean is byte 14 bit 2", CleanMode.ON == 0x04)
    check("clean base is 0x10", CleanMode.BASE == 0x10)
    check("plasma ON is byte 15 bit 6", PlasmaMode.ON == 0x40)

    on = build()
    off = build(isee_mode=ISeeMode.OFF, clean_mode=CleanMode.OFF,
                plasma_mode=PlasmaMode.OFF)
    check("i-see on sets b6 bit6", on[6] & 0x40 == 0x40, f"b6 {on[6]:#04x}")
    check("i-see off clears b6 bit6", off[6] & 0x40 == 0, f"b6 {off[6]:#04x}")
    check("clean on sets b14 bit2", on[14] & 0x04 == 0x04, f"b14 {on[14]:#04x}")
    check("clean off clears b14 bit2", off[14] & 0x04 == 0, f"b14 {off[14]:#04x}")
    check("plasma on sets b15 bit6", on[15] & 0x40 == 0x40, f"b15 {on[15]:#04x}")
    check("plasma off clears b15 bit6", off[15] & 0x40 == 0, f"b15 {off[15]:#04x}")
    check("feature bits never touch each other's bytes",
          off[14] == 0x10 and on[14] == 0x14)
    check("checksums valid", checksum_ok(on) and checksum_ok(off))


def test_each_bit_independent() -> None:
    """Toggling one feature must change exactly one byte."""
    base = build()
    combos = {
        "isee": build(isee_mode=ISeeMode.OFF),
        "clean": build(clean_mode=CleanMode.OFF),
        "plasma": build(plasma_mode=PlasmaMode.OFF),
    }
    for key, frame in combos.items():
        changed = [i for i in range(17) if frame[i] != base[i]]
        # byte 17 is the checksum and legitimately changes too
        expected = {"isee": 6, "clean": 14, "plasma": 15}[key]
        check(f"{key} off changes only byte {expected}", changed == [expected],
              f"changed {changed}")
        check(f"{key} off keeps checksum valid", checksum_ok(frame))


def test_byte15_validator() -> None:
    try:
        validate_byte15_fields()
        check("validate_byte15_fields passes", True)
    except ValueError as exc:  # pragma: no cover
        check("validate_byte15_fields passes", False, str(exc))

    try:
        build(install_position=InstallPosition.LEFT, powerful=PowerfulMode.ON)
        check("powerful+install LEFT collision rejected", False, "no error")
    except ValueError:
        check("powerful+install LEFT collision rejected", True)

    ok = build(install_position=InstallPosition.MIDDLE)
    check("install MIDDLE keeps plasma bit", ok[15] & 0x40 == 0x40)


def test_climate_owns_features() -> None:
    climate = make_climate()
    check("climate starts with default feature states",
          climate.feature_states == FEATURE_DEFAULTS,
          str(climate.feature_states))

    frame = climate._current_code()
    check("default frame carries all three bits on",
          (frame[6] & 0x40) and (frame[14] & 0x04) and (frame[15] & 0x40),
          frame.hex())

    climate.feature_states["clean"] = False
    frame = climate._current_code()
    check("clearing clean drops b14 bit2", frame[14] & 0x04 == 0)
    check("clearing clean leaves i-see/plasma", (frame[6] & 0x40) and (frame[15] & 0x40))


def test_switch_entities() -> None:
    climate = make_climate()
    switches = feature_switches_for(climate)
    check("three switches created", len(switches) == 3, str(len(switches)))
    check("switch keys match FEATURE_KEYS",
          [s._feature for s in switches] == FEATURE_KEYS)
    check("switch names", [s.name for s in switches] == ["I-See", "Clean", "Plasma"])
    check("unique ids are stable",
          [s.unique_id for s in switches] == [
              "mitsubishi_remote_remote_blaster_isee",
              "mitsubishi_remote_remote_blaster_clean",
              "mitsubishi_remote_remote_blaster_plasma",
          ], str([s.unique_id for s in switches]))
    check("switch inherits current state",
          all(s.is_on == FEATURE_DEFAULTS[s._feature] for s in switches))

    # Every switch must declare an icon, or the card shows a blank dot.
    for sw in switches:
        check(f"{sw._feature} has an icon", bool(sw.icon), str(sw.icon))


def test_switch_transmits() -> None:
    asyncio.run(_switch_transmits())


async def _switch_transmits() -> None:
    climate = make_climate()
    climate._power = True  # unit running, so setters transmit
    sw = make_switch(climate, "clean")
    await sw.async_added_to_hass()

    await sw.async_turn_off()
    sent = frames_sent(climate)
    check("turn_off transmits one frame", len(sent) == 1, str(len(sent)))
    check("switch reports off", sw.is_on is False)
    check("climate feature state updated", climate.feature_states["clean"] is False)

    # No-op toggles must not spam the blaster.
    await sw.async_turn_off()
    check("repeated turn_off sends nothing", len(frames_sent(climate)) == 1,
          str(len(frames_sent(climate))))

    await sw.async_turn_on()
    check("turn_on transmits again", len(frames_sent(climate)) == 2)

    # While the unit is off, a switch must not transmit (it would power it on).
    climate._power = False
    await sw.async_turn_off()
    check("no transmission while unit is off", len(frames_sent(climate)) == 2,
          str(len(frames_sent(climate))))
    check("state still updates while off", sw.is_on is False)


def test_switch_restore() -> None:
    asyncio.run(_switch_restore())


async def _switch_restore() -> None:
    climate = make_climate()
    climate._power = True
    sw = make_switch(climate, "plasma", last_state=FakeState("off"))
    await sw.async_added_to_hass()

    check("restored switch reports off", sw.is_on is False)
    check("restore writes through to climate", climate.feature_states["plasma"] is False)
    check("restore transmits nothing", frames_sent(climate) == [],
          str(frames_sent(climate)))

    sw2 = make_switch(climate, "isee", last_state=None)
    await sw2.async_added_to_hass()
    check("no history falls back to climate default", sw2.is_on is True)
    check("no-history restore transmits nothing",
          frames_sent(climate) == [], str(frames_sent(climate)))


def test_switch_platform_handoff() -> None:
    """The climate platform must load the switch platform with discovery info."""
    from custom_components.mitsubishi_remote import climate as climate_mod

    climate = make_climate()
    hass = FakeHass()
    hass.data = {}
    added: list = []

    asyncio.run(
        climate_mod.async_setup_platform(
            hass,
            {"remote_entity": "remote.blaster", "name": "Study AC"},
            lambda entities, update_before_add=False: added.extend(entities),
            None,
        )
    )
    check("climate platform adds one entity", len(added) == 1, str(added))
    check("switch platform load scheduled", len(hass.created) == 1,
          str(len(hass.created)))

    # Now run the switch platform the way HA would, after the task is created.
    from custom_components.mitsubishi_remote import switch as switch_mod

    entities: list = []
    asyncio.run(
        switch_mod.async_setup_platform(
            hass,
            {},
            lambda ents, update_before_add=False: entities.extend(ents),
            {"climate": added[0]},
        )
    )
    check("switch platform creates three entities", len(entities) == 3,
          str(len(entities)))
    check("switches stored under their own key (hass.data[DOMAIN] is a list)",
          len(hass.data.get(DATA_SWITCHES, {})) == 3, str(hass.data.keys()))
    check("switches attached to the same climate entity",
          all(e._climate is added[0] for e in entities))

    # And a missing discovery info must not explode.
    try:
        asyncio.run(switch_mod.async_setup_platform(hass, {}, lambda e, **k: None, None))
        check("switch platform tolerates missing discovery info", True)
    except Exception as exc:  # pragma: no cover
        check("switch platform tolerates missing discovery info", False, repr(exc))


def test_force_send_includes_features() -> None:
    asyncio.run(_force_send())


async def _force_send() -> None:
    climate = make_climate()
    climate.feature_states["plasma"] = False
    await climate.async_send_command(
        hvac_mode="cool", temperature=24, fan_mode="auto", power=True
    )
    sent = frames_sent(climate)
    check("force_send transmitted", len(sent) == 1, str(len(sent)))
    # decode the raw: payload back into bytes to check the plasma bit
    pulses = [int(p) for p in sent[0].removeprefix("raw:").split(",")]
    # 18 bytes, 8 bits each = 144 bit pairs after the 2-pulse header
    bits = pulses[2:]
    frame = bytearray()
    for i in range(0, 18 * 16, 16):
        byte = 0
        for b in range(8):
            space = bits[i + b * 2 + 1]
            if space > 800:  # ONE_SPACE = 1300, ZERO_SPACE = 420
                byte |= 1 << b
        frame.append(byte)
    check("force_send byte15 has plasma cleared", frame[15] & 0x40 == 0,
          f"b15 {frame[15]:#04x} frame {bytes(frame).hex()}")
    check("force_send still carries i-see and clean",
          (frame[6] & 0x40) and (frame[14] & 0x04),
          f"b6 {frame[6]:#04x} b14 {frame[14]:#04x}")


def main() -> int:
    test_bit_values()
    test_each_bit_independent()
    test_byte15_validator()
    test_climate_owns_features()
    test_switch_entities()
    test_switch_transmits()
    test_switch_restore()
    test_switch_platform_handoff()
    test_force_send_includes_features()

    failed = [name for ok, name in RESULTS if not ok]
    print()
    if failed:
        print(f"{len(failed)} FAILED:")
        for name in failed:
            print(f"  - {name}")
        return 1
    print(f"ALL PASS ({len(RESULTS)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
