"""Regression tests for the byte-9 fan/vane fix and the wide-vane axis.

Ground truth is the user's own learned captures from the target unit, quoted in
README section 3 and in the power-off comment in climate.py:

    cool @ 24 C, fan auto  : 23 CB 26 01 00 20 58 08 06 40 62 00 00 80 10 00 00 CD
    power off @ heat 22 C  : 23 CB 26 01 00 00 48 06 00 69 53 00 00 80 14 40 00 <ck>

Run with:
    uv run --with 'homeassistant==2025.1.4' python tests/verify_vane.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from custom_components.mitsubishi_remote.climate import (  # noqa: E402
    FAN_MODES,
    SWING_HORIZONTAL_MODES,
    SWING_MODES,
    MitsubishiExtraStoredData,
    MitsubishiRemoteClimate,
    normalise_install_position,
)
from custom_components.mitsubishi_remote.mitsubishi_protocol import (  # noqa: E402
    CleanMode,
    ClimateMode,
    FanMode,
    InstallPosition,
    PlasmaMode,
    PowerMode,
    VanneHorizontalMode,
    VanneVerticalMode,
    build_frame,
    validate_byte9_fields,
)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((bool(condition), name))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not condition else ""))


def checksum_ok(frame: bytes) -> bool:
    return frame[17] == sum(frame[:17]) % 256


# --- learned captures -------------------------------------------------------
CAP_COOL = bytes.fromhex("23CB26010020580806406200008010000 0CD".replace(" ", ""))
CAP_OFF = bytes.fromhex("23CB2601000048060069530000801440")

# The two captured bytes that this whole change is about.
CAP_COOL_B9 = 0x40
CAP_OFF_B9 = 0x69


def build(climate_mode, fan, vane, vane_h=0, **kw):
    opts = {
        "clean_mode": CleanMode.ON,
        "plasma_mode": PlasmaMode.ON,
    }
    opts.update(kw)
    return build_frame(
        climate_mode=climate_mode,
        temperature=24,
        fan_mode=fan,
        vanne_vertical_mode=vane,
        vanne_horizontal_mode=vane_h,
        clock=0x62,  # pin the clock so frames are deterministic
        **opts,
    )


def main() -> int:
    # 1. Field disjointness guard.
    try:
        validate_byte9_fields()
        check("byte 9 fields are disjoint", True)
    except (ValueError, AssertionError) as err:  # pragma: no cover
        check("byte 9 fields are disjoint", False, str(err))

    # 2. The regression itself: fan auto + vane auto must be 0x40, not 0x68.
    frame = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO)
    check(
        "fan auto + vane auto -> byte9 0x40 (was 0x68 = vane BOTTOM)",
        frame[9] == CAP_COOL_B9,
        f"got {frame[9]:#04x}",
    )

    # 3. The second learned capture: fan low + vane bottom -> 0x69.
    frame = build(ClimateMode.HOT, FanMode.SPEED1, VanneVerticalMode.BOTTOM)
    check(
        "fan low + vane bottom -> byte9 0x69 (power-off capture)",
        frame[9] == CAP_OFF_B9,
        f"got {frame[9]:#04x}",
    )

    # 4. Full cool frame reproduces the learned capture byte-for-byte,
    #    except byte 15 where we deliberately differ (see README).
    frame = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO, isee_mode=0x40)
    diffs = {i: (CAP_COOL[i], frame[i]) for i in range(17) if CAP_COOL[i] != frame[i]}
    # Known/expected differences: byte 14 (clean: 0x10 vs 0x14) and byte 15
    # (plasma hypothesis: 0x00 vs 0x40). Everything else must match.
    unexpected = {i: v for i, v in diffs.items() if i not in (14, 15)}
    check(
        "cool frame matches capture except bytes 14/15",
        not unexpected,
        f"unexpected diffs {unexpected}",
    )
    check(
        "byte 14 diff is exactly the clean bit (0x10 -> 0x14)",
        diffs.get(14) == (0x10, 0x14),
        str(diffs.get(14)),
    )
    check(
        "byte 15 diff is exactly the plasma bit (0x00 -> 0x40)",
        diffs.get(15) == (0x00, 0x40),
        str(diffs.get(15)),
    )

    # 5. Defensive: clean OFF must reproduce the raw capture byte 14 = 0x10.
    frame = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO, clean_mode=CleanMode.OFF)
    check("clean off -> byte14 0x10 (matches capture)", frame[14] == 0x10, f"got {frame[14]:#04x}")

    frame = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO, plasma_mode=PlasmaMode.OFF)
    check("plasma off -> byte15 0x00 (matches capture)", frame[15] == 0x00, f"got {frame[15]:#04x}")

    # 6. Swing must actually move the vane: 0x78, and bit 7 must stay clear.
    frame_swing = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.SWING)
    check("vertical swing -> vane bits 0x78", frame_swing[9] == 0x78, f"got {frame_swing[9]:#04x}")
    check("vertical swing does not set bit 7 (old 0x80 bug)", not (frame_swing[9] & 0x80))
    check(
        "swing differs from auto (it actually does something)",
        frame_swing[9] != build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO)[9],
    )

    # 7. Every fan/vane combination is unique and in range (no field bleed).
    seen = {}
    for fan_name, fan in (("auto", 0), ("low", 1), ("medium", 2), ("high", 3)):
        for vane_name, vane in (
            ("auto", 0x40), ("top", 0x48), ("middle_top", 0x50), ("middle", 0x58),
            ("middle_bottom", 0x60), ("bottom", 0x68), ("swing", 0x78),
        ):
            b = build(ClimateMode.COLD, fan, vane)[9]
            key = (fan_name, vane_name)
            if b in seen:
                check(f"byte9 unique for {key}", False, f"collides with {seen[b]}")
                break
            seen[b] = key
    else:
        check("all 28 fan/vane combinations encode uniquely", True, f"{len(seen)} distinct bytes")

    # 8. Wide vane lives in byte 8 and is independent of the vertical vane.
    base_v = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO)
    for label, code in (
        ("off", VanneHorizontalMode.NOT_SET),
        ("on", VanneHorizontalMode.SWING),
    ):
        f = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO, vane_h=code)
        check(f"wide vane {label} -> byte8 contains {code:#04x}", (f[8] & 0xF0) == (code & 0xF0),
              f"byte8 {f[8]:#04x}")
        check(f"wide vane {label} leaves byte9 unchanged", f[9] == base_v[9])

    # 9. Install position is opt-in and only touches byte 15 bits 3-4.
    for label, code in (
        ("left", InstallPosition.LEFT),
        ("middle", InstallPosition.MIDDLE),
        ("right", InstallPosition.RIGHT),
    ):
        f = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO, install_position=code)
        check(f"install_position {label} -> byte15 bits3-4 {code:#04x}",
              (f[15] & 0x18) == code, f"byte15 {f[15]:#04x}")
        # plasma bit must survive
        check(f"install_position {label} keeps plasma bit", (f[15] & 0x40) == 0x40,
              f"byte15 {f[15]:#04x}")
    f_unset = build(ClimateMode.COLD, FanMode.AUTO, VanneVerticalMode.AUTO)
    check("install_position unset leaves bits 3-4 clear", (f_unset[15] & 0x18) == 0,
          f"byte15 {f_unset[15]:#04x}")

    # 10. Checksums still valid everywhere.
    bad = []
    for fan in (0, 1, 2, 3):
        for vane in (0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x78):
            f = build(ClimateMode.COLD, fan, vane)
            if not checksum_ok(f):
                bad.append((fan, vane, f.hex()))
    check("checksum valid across all combinations", not bad, str(bad[:3]))

    # 11. Install position config validation.
    check("install_position 'middle' accepted", normalise_install_position("middle") == "middle")
    check("install_position None accepted", normalise_install_position(None) is None)
    check("install_position '' treated as unset", normalise_install_position("") is None)
    try:
        normalise_install_position("ceiling")
        check("install_position rejects junk", False, "no error raised")
    except ValueError:
        check("install_position rejects junk", True)

    # 12. Icon-map keys exist for every advertised value.
    icons_path = os.path.join(os.path.dirname(__file__), "climate_icons.json")
    with open(icons_path, encoding="utf-8") as fh:
        icons = json.load(fh)
    sa = icons["entity_component"]["_"]["state_attributes"]
    for attr, values in (
        ("fan_mode", FAN_MODES),
        ("swing_mode", SWING_MODES),
        ("swing_horizontal_mode", SWING_HORIZONTAL_MODES),
    ):
        missing = [v for v in values if v not in sa[attr]["state"]]
        check(f"every {attr} value has an icon", not missing, f"missing {missing}")

    # 13. Entity-level: feature flag advertised, and encoders disagree correctly.
    async def entity_checks():
        ent = MitsubishiRemoteClimate(
            remote_entity="remote.x", name="t", command_format="hex",
            hex_prefix=False, retries=1, repeat_gap=0.0,
        )
        from homeassistant.components.climate import ClimateEntityFeature
        check(
            "SWING_HORIZONTAL_MODE advertised",
            bool(ent.supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE),
        )
        sent = []
        async def fake_send(frame):
            sent.append(frame)
        ent._send = fake_send
        # No real hass in this harness; stub the state writer (HA raises
        # "Attribute hass is None" otherwise).
        ent.async_write_ha_state = lambda: None

        ent._power = True
        ent._attr_hvac_mode = "cool"
        ent._active_mode = "cool"
        ent._attr_fan_mode = "low"
        ent._attr_swing_mode = "off"
        ent._attr_swing_horizontal_mode = "off"
        await ent.async_set_swing_horizontal_mode("on")
        f = sent[-1]
        check("async_set_swing_horizontal_mode('on') sets wide swing in byte8",
              (f[8] & 0xF0) == 0x80, f"byte8 {f[8]:#04x}")
        check("...and leaves the vertical vane at auto", (f[9] & 0x78) == 0x40,
              f"byte9 {f[9]:#04x}")

        # Legacy capitalised labels must still work and must now map to the
        # correct *protocol* code.
        await ent.async_set_fan_mode("High")
        check("legacy fan 'High' -> canonical 'high'", ent.fan_mode == "high", ent.fan_mode)
        check("fan 'high' -> byte9 fan bits = 3", (sent[-1][9] & 0x07) == 3,
              f"byte9 {sent[-1][9]:#04x}")

        await ent.async_set_swing_mode("swing")
        check("legacy swing 'swing' -> canonical 'on'", ent.swing_mode == "on", ent.swing_mode)
        check("swing 'on' -> vane 0x78", (sent[-1][9] & 0x78) == 0x78,
              f"byte9 {sent[-1][9]:#04x}")

        # Restore round-trip must carry the new axis.
        d = MitsubishiExtraStoredData(
            active_mode="heat", hvac_mode="heat", target_temperature=23,
            fan_mode="high", swing_mode="on", swing_horizontal_mode="on",
        ).as_dict()
        check("extra data includes swing_horizontal_mode", d["swing_horizontal_mode"] == "on")
        check("extra data is JSON round-trippable",
              json.loads(json.dumps(d))["swing_horizontal_mode"] == "on")

    asyncio.run(entity_checks())

    failed = [name for ok, name in RESULTS if not ok]
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("FAILED:")
        for name in failed:
            print("  -", name)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
