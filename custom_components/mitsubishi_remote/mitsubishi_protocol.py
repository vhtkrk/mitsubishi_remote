"""Encoder for the Mitsubishi MSZ-FD25VA infrared frame.

IR_PROTOCOL.md in the repository root is the specification for this module.
The names here match that document. The section numbers (§) refer to it.
"""

from __future__ import annotations

from datetime import datetime, time
from enum import IntEnum

HEADER = (0x23, 0xCB, 0x26, 0x01, 0x00)  # bytes 0-4 (§3.1)
CARRIER_HZ = 38_000  # §1

MIN_TEMP = 16
MAX_TEMP = 31


class Mode(IntEnum):
    """MODE, byte 6 bits 5-3 (§3.3)."""

    HEAT = 0b001
    DRY = 0b010
    COOL = 0b011
    AUTO = 0b100


# MODE2, byte 8 bits 2-0 (§3.5). It depends only on MODE (rule R2).
MODE2 = {Mode.HEAT: 0b000, Mode.DRY: 0b010, Mode.COOL: 0b110, Mode.AUTO: 0b000}


class Fan(IntEnum):
    """FAN, byte 9 bits 2-0 (§3.6). Bit 7 stays 0, also for AUTO."""

    AUTO = 0
    LOW = 1
    MED = 2
    HIGH = 3
    SUPER_HIGH = 4


class Vane(IntEnum):
    """VANE (up/down airflow), byte 9 bits 5-3 (§3.6). Byte 9 bit 6 is always 1."""

    AUTO = 0
    POS1 = 1  # highest
    POS2 = 2
    POS3 = 3
    POS4 = 4
    POS5 = 5  # lowest
    SWING = 7


class WideVane(IntEnum):
    """WIDE_VANE (left/right airflow), byte 8 bits 7-4 (§3.5)."""

    NONE = 0x0  # AREA is active
    FAR_LEFT = 0x1
    LEFT = 0x2
    CENTER = 0x3
    RIGHT = 0x4
    FAR_RIGHT = 0x5
    SWING = 0xC


class Area(IntEnum):
    """AREA (i-see area control), byte 13 bits 7-6 (§3.9)."""

    OFF = 0b00
    LEFT = 0b01
    AUTO = 0b10
    RIGHT = 0b11


class InstallPos(IntEnum):
    """INSTALL_POS (slide switch in the remote), byte 14 bits 4-3 (§3.10)."""

    LEFT = 0b01
    CENTER = 0b10
    RIGHT = 0b11


class Timing:
    """Pulse lengths in microseconds (§1)."""

    HDR_MARK = 3400
    HDR_SPACE = 1750
    BIT_MARK = 450
    ONE_SPACE = 1300
    ZERO_SPACE = 420
    STOP_MARK = 440
    GAP = 17100


def clock_units(value: time) -> int:
    """Return a time of day in 10-minute units since 00:00 (§3.7)."""
    return value.hour * 6 + value.minute // 10


def build_frame(
    *,
    power: bool,
    mode: Mode,
    temperature: int,
    fan: Fan = Fan.AUTO,
    vane: Vane = Vane.AUTO,
    wide_vane: WideVane = WideVane.NONE,
    area: Area = Area.AUTO,
    isee: bool = True,
    install_pos: InstallPos = InstallPos.CENTER,
    clean: bool = False,
    econo_cool: bool = False,
    plasma: bool = False,
    clock: time | None = None,
    off_timer: time | None = None,
    on_timer: time | None = None,
) -> bytes:
    """Return one 18-byte frame (§2).

    Raise ValueError for a combination that the real remote never sends (§4).
    `clock` defaults to the current local time.
    """
    if (area == Area.OFF) == (wide_vane == WideVane.NONE):
        raise ValueError("R3: exactly one of AREA and WIDE_VANE must be active")
    if area != Area.OFF and not isee:
        raise ValueError("R4: AREA needs ISEE")
    if econo_cool and mode != Mode.COOL:
        raise ValueError("R6: ECONO_COOL needs MODE=COOL")

    temperature = max(MIN_TEMP, min(MAX_TEMP, int(temperature)))
    timer = (0b101 if on_timer is not None else 0) | (0b011 if off_timer is not None else 0)
    frame = [
        *HEADER,
        0x20 if power else 0x00,                                       # 5  POWER
        (0x40 if isee else 0x00) | mode << 3,                          # 6  ISEE, MODE
        temperature - MIN_TEMP,                                        # 7  TEMP
        wide_vane << 4 | MODE2[mode],                                  # 8  WIDE_VANE, MODE2
        0x40 | vane << 3 | fan,                                        # 9  1, VANE, FAN
        clock_units(clock if clock is not None else datetime.now().time()),  # 10 CLOCK
        clock_units(off_timer) if off_timer is not None else 0,        # 11 OFF_TIMER
        clock_units(on_timer) if on_timer is not None else 0,          # 12 ON_TIMER
        area << 6 | timer,                                             # 13 AREA, TIMER
        (0x20 if econo_cool else 0) | install_pos << 3 | (0x04 if clean else 0),  # 14
        0x40 if plasma else 0x00,                                      # 15 PLASMA
        0x00,                                                          # 16
    ]
    frame.append(sum(frame) % 256)                                     # 17 CHECKSUM
    return bytes(frame)


def modulate(frame: bytes, copies: int = 2) -> list[int]:
    """Return one transmission as alternating mark/space lengths in µs (§1).

    Each copy is HDR_MARK, HDR_SPACE, 144 bits (bit 0 of each byte first) and
    STOP_MARK. A GAP separates the copies. The list starts and ends with a mark.
    """
    pulses: list[int] = []
    for copy in range(copies):
        if copy:
            pulses.append(Timing.GAP)
        pulses += [Timing.HDR_MARK, Timing.HDR_SPACE]
        for byte in frame:
            for bit in range(8):
                one = byte >> bit & 1
                pulses += [Timing.BIT_MARK, Timing.ONE_SPACE if one else Timing.ZERO_SPACE]
        pulses.append(Timing.STOP_MARK)
    return pulses
