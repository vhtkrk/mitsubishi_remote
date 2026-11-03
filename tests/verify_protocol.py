"""Protocol checks against IR_PROTOCOL.md and the real captures in it.

Run with:
    uv run --python 3.13 --with 'homeassistant==2025.1.4' python tests/verify_protocol.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from homeassistant.components.climate import ClimateEntityFeature  # noqa: E402
from homeassistant.exceptions import ServiceValidationError  # noqa: E402

from custom_components.mitsubishi_remote.climate import (  # noqa: E402
    MitsubishiRemoteClimate,
    normalise_install_position,
)
from custom_components.mitsubishi_remote.mitsubishi_protocol import (  # noqa: E402
    Area,
    Fan,
    InstallPos,
    Mode,
    Timing,
    Vane,
    WideVane,
    build_frame,
    modulate,
)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((bool(condition), name))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not condition else ""))


# Real frames from MSZ-FD remotes (IR_PROTOCOL.md §5).
CAP_A = bytes.fromhex("23 CB 26 01 00 20 58 08 06 40 62 00 00 80 10 00 00 CD")
CAP_B = bytes.fromhex("23 CB 26 01 00 20 58 08 06 40 37 00 00 40 18 00 00 6A")
CAP_C16 = bytes.fromhex("23 CB 26 01 00 00 48 06 00 69 53 00 00 80 14 40")  # bytes 0-15
# Built frames E1 and E2 from IR_PROTOCOL.md §5.4.
DOC_E1 = bytes.fromhex("23 CB 26 01 00 20 48 05 C0 62 2D 00 00 00 10 40 00 21")
DOC_E2 = bytes.fromhex("23 CB 26 01 00 20 58 09 06 40 85 8A 27 87 14 00 00 AD")


def frame(**kw) -> bytes:
    """Capture A's state, with `kw` changed."""
    fields: dict = {"power": True, "mode": Mode.COOL, "temperature": 24, "clock": time(16, 20)}
    fields.update(kw)
    return build_frame(**fields)


def raises_value_error(**kw) -> bool:
    try:
        frame(**kw)
    except ValueError:
        return True
    return False


def test_captures() -> None:
    check("capture A rebuilt byte for byte", frame() == CAP_A, frame().hex(" "))
    b = frame(area=Area.LEFT, install_pos=InstallPos.RIGHT, clock=time(9, 10))
    check("capture B rebuilt byte for byte", b == CAP_B, b.hex(" "))
    c = frame(
        power=False, mode=Mode.HEAT, temperature=22, fan=Fan.LOW, vane=Vane.POS5,
        clean=True, plasma=True, clock=time(13, 50),
    )
    check("capture C bytes 0-15 rebuilt", c[:16] == CAP_C16, c.hex(" "))
    check("capture C bytes 16-17 = 00 F3", c[16:] == bytes([0x00, 0xF3]), c[16:].hex(" "))

    e1 = frame(
        mode=Mode.HEAT, temperature=21, fan=Fan.MED, vane=Vane.POS4,
        wide_vane=WideVane.SWING, area=Area.OFF, plasma=True, clock=time(7, 30),
    )
    check("document example E1", e1 == DOC_E1, e1.hex(" "))
    e2 = frame(
        temperature=25, clean=True, clock=time(22, 10),
        off_timer=time(23, 0), on_timer=time(6, 30),
    )
    check("document example E2", e2 == DOC_E2, e2.hex(" "))


def test_fields() -> None:
    expected6 = {Mode.HEAT: 0x08, Mode.DRY: 0x10, Mode.COOL: 0x18, Mode.AUTO: 0x20}
    expected8 = {Mode.HEAT: 0x00, Mode.DRY: 0x02, Mode.COOL: 0x06, Mode.AUTO: 0x00}
    for mode, value in expected6.items():
        check(f"byte 6 {mode.name} ISEE=1 = {value | 0x40:#04x}", frame(mode=mode)[6] == value | 0x40)
        f = frame(mode=mode, isee=False, area=Area.OFF, wide_vane=WideVane.CENTER)
        check(f"byte 6 {mode.name} ISEE=0 = {value:#04x}", f[6] == value)
        check(f"byte 8 MODE2 for {mode.name}", frame(mode=mode)[8] == expected8[mode])

    wide = {
        WideVane.FAR_LEFT: 0x10, WideVane.LEFT: 0x20, WideVane.CENTER: 0x30,
        WideVane.RIGHT: 0x40, WideVane.FAR_RIGHT: 0x50, WideVane.SWING: 0xC0,
    }
    for position, value in wide.items():
        f = frame(area=Area.OFF, wide_vane=position)
        check(f"WIDE_VANE {position.name} -> byte 8 {value | 0x06:#04x}", f[8] == value | 0x06)
        check(f"WIDE_VANE {position.name} -> AREA OFF", f[13] & 0xC0 == 0)

    for area, value in ((Area.LEFT, 0x40), (Area.AUTO, 0x80), (Area.RIGHT, 0xC0)):
        check(f"AREA {area.name} -> byte 13 {value:#04x}", frame(area=area)[13] == value)

    vane = {
        Vane.AUTO: 0x40, Vane.POS1: 0x48, Vane.POS2: 0x50, Vane.POS3: 0x58,
        Vane.POS4: 0x60, Vane.POS5: 0x68, Vane.SWING: 0x78,
    }
    seen = set()
    for v, v_value in vane.items():
        for fan in Fan:
            b9 = frame(vane=v, fan=fan)[9]
            seen.add(b9)
            if b9 != v_value | fan:
                check(f"byte 9 for {v.name}/{fan.name}", False, f"{b9:#04x}")
    check("byte 9 = 0x40 | VANE << 3 | FAN for all 35 combinations", len(seen) == 35)
    check("byte 9 bit 7 never set (FAN=AUTO included)", all(not b & 0x80 for b in seen))

    for pos, value in ((InstallPos.LEFT, 0x08), (InstallPos.CENTER, 0x10), (InstallPos.RIGHT, 0x18)):
        check(f"INSTALL_POS {pos.name} -> byte 14 {value:#04x}", frame(install_pos=pos)[14] == value)
    check("CLEAN -> byte 14 bit 2", frame(clean=True)[14] == 0x14)
    check("ECONO_COOL -> byte 14 bit 5", frame(econo_cool=True)[14] == 0x30)
    check("PLASMA -> byte 15 = 0x40", frame(plasma=True)[15] == 0x40 and frame()[15] == 0)
    check("POWER off -> byte 5 = 0x00", frame(power=False)[5] == 0x00)

    check("CLOCK 23:59 -> 0x8F (rounds down to 23:50)", frame(clock=time(23, 59))[10] == 0x8F)
    check("CLOCK 00:00 = 0x00", frame(clock=time(0, 0))[10] == 0x00)
    check("OFF_TIMER only -> TIMER 0b011", frame(off_timer=time(1, 0))[13] & 0x07 == 0b011)
    check("ON_TIMER only -> TIMER 0b101", frame(on_timer=time(1, 0))[13] & 0x07 == 0b101)
    check("ON_TIMER at 00:00 still sets TIMER", frame(on_timer=time(0, 0))[13] & 0x07 == 0b101)
    check("TEMP clamps to 16..31", frame(temperature=10)[7] == 0 and frame(temperature=40)[7] == 15)
    check("checksum = sum of bytes 0-16 mod 256",
          all(f[17] == sum(f[:17]) % 256 for f in (frame(), frame(power=False), DOC_E2)))


def test_rules() -> None:
    check("R3: AREA and WIDE_VANE both active -> ValueError",
          raises_value_error(area=Area.AUTO, wide_vane=WideVane.CENTER))
    check("R3: neither AREA nor WIDE_VANE -> ValueError",
          raises_value_error(area=Area.OFF, wide_vane=WideVane.NONE))
    check("R4: AREA without ISEE -> ValueError", raises_value_error(isee=False))
    check("R6: ECONO_COOL outside COOL -> ValueError",
          raises_value_error(mode=Mode.HEAT, econo_cool=True))


def test_modulate() -> None:
    pulses = modulate(CAP_A)
    one_copy = 2 + 18 * 8 * 2 + 1
    check("transmission length = 2 copies + gap", len(pulses) == 2 * one_copy + 1, str(len(pulses)))
    check("starts with HDR_MARK, HDR_SPACE", pulses[:2] == [Timing.HDR_MARK, Timing.HDR_SPACE])
    check("ends with STOP_MARK", pulses[-1] == Timing.STOP_MARK)
    check("STOP_MARK then GAP between the copies",
          pulses[one_copy - 1:one_copy + 1] == [Timing.STOP_MARK, Timing.GAP])
    decoded = []
    for copy in (0, 1):
        start = copy * (one_copy + 1) + 2
        bits = pulses[start:start + 288]
        decoded.append(bytes(
            sum((bits[(i * 8 + b) * 2 + 1] == Timing.ONE_SPACE) << b for b in range(8))
            for i in range(18)
        ))
    check("both copies decode back to the frame, bit 0 first", decoded == [CAP_A, CAP_A])


async def entity_checks() -> None:
    ent = MitsubishiRemoteClimate(remote_entity="remote.x", name="t", retries=1, repeat_gap=0.0)
    sent: list[bytes] = []

    async def fake_send(f: bytes) -> None:
        sent.append(f)

    ent._send = fake_send
    ent.async_write_ha_state = lambda: None
    ent._power = True
    ent._active_mode = "cool"
    ent._attr_hvac_mode = "cool"

    check("SWING_HORIZONTAL_MODE advertised",
          bool(ent.supported_features & ClimateEntityFeature.SWING_HORIZONTAL_MODE))
    check("default left/right airflow is area_auto", ent.swing_horizontal_mode == "area_auto")
    f = ent._current_code()
    check("default frame: AREA AUTO, WIDE_VANE NONE", f[13] & 0xC0 == 0x80 and f[8] & 0xF0 == 0)

    await ent.async_set_swing_horizontal_mode("swing")
    check("swing -> WIDE_VANE 0xC, AREA OFF",
          sent[-1][8] == 0xC6 and sent[-1][13] & 0xC0 == 0, sent[-1].hex(" "))
    await ent.async_set_swing_horizontal_mode("area_left")
    check("area_left -> AREA LEFT, WIDE_VANE NONE",
          sent[-1][13] & 0xC0 == 0x40 and sent[-1][8] & 0xF0 == 0, sent[-1].hex(" "))

    await ent.async_set_feature("isee", False)
    check("i-see off: area choice falls back to the last WIDE_VANE (R4, R5)",
          ent.swing_horizontal_mode == "swing", ent.swing_horizontal_mode)
    check("i-see off: frame has ISEE 0, AREA OFF, WIDE_VANE SWING",
          sent[-1][6] & 0x40 == 0 and sent[-1][13] & 0xC0 == 0 and sent[-1][8] & 0xF0 == 0xC0,
          sent[-1].hex(" "))
    try:
        await ent.async_set_swing_horizontal_mode("area_auto")
        check("area choice without i-see is rejected", False, "no error")
    except ServiceValidationError:
        check("area choice without i-see is rejected", True)

    await ent.async_set_feature("isee", True)
    await ent.async_set_swing_horizontal_mode("off")
    check("legacy 'off' -> area_auto", ent.swing_horizontal_mode == "area_auto")
    await ent.async_set_swing_horizontal_mode("on")
    check("legacy 'on' -> swing", ent.swing_horizontal_mode == "swing")

    await ent.async_set_swing_mode("pos3")
    check("swing_mode pos3 -> VANE 0x58", sent[-1][9] & 0x78 == 0x58, f"{sent[-1][9]:#04x}")
    await ent.async_set_fan_mode("super_high")
    check("fan super_high -> FAN 4", sent[-1][9] & 0x07 == 4, f"{sent[-1][9]:#04x}")

    left = MitsubishiRemoteClimate(
        remote_entity="remote.y", name="u", retries=1, repeat_gap=0.0, install_position="left"
    )
    check("install_position left -> byte 14 bits 4-3 = 01", left._current_code()[14] & 0x18 == 0x08)


def test_install_position_option() -> None:
    check("install_position unset -> center", normalise_install_position(None) == "center")
    check("install_position '' -> center", normalise_install_position("") == "center")
    check("install_position 'middle' -> center", normalise_install_position("middle") == "center")
    check("install_position 'Right' -> right", normalise_install_position("Right") == "right")
    try:
        normalise_install_position("ceiling")
        check("install_position rejects other text", False, "no error raised")
    except ValueError:
        check("install_position rejects other text", True)


def main() -> int:
    test_captures()
    test_fields()
    test_rules()
    test_modulate()
    test_install_position_option()
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
