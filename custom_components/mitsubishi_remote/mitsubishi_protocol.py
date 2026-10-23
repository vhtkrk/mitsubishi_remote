"""Mitsubishi HVAC IR protocol encoder (MSZ-FD25VA / MSZ-FE12NA family).

Port of the working implementation (HVAC-IR-Control, Eric Masse / r45635) which
was verified against a real unit. Encodes the 18-byte packet used by the
Mitsubishi remote, including the checksum and the two-frame transmission timing.

Frame layout (index per the reference implementation):
    0-4  Header bytes (constant)
    5    Power (bit 5)
    6    Climate mode | I-See
    7    Temperature (value = temp - 16)
    8    Climate2 | horizontal vane (wide vane)
    9    Fan | vertical vane
    10   Clock = hour*6 + minute//10
    11   End time
    12   Start time
    13   Time control | area mode
    14   Clean mode
    15   Plasma | powerful | install position
    16   Constant (0x00)
    17   Checksum = sum(bytes 0..16) % 256

Byte 9 field layout (the part that used to be wrong)
----------------------------------------------------
Byte 9 packs two *disjoint* fields::

    bits 0-2  fan speed   0 = auto, 1/2/3 = low/medium/high
    bits 3-6  vertical vane
    bit  7    unused

The previous constants put the fan base at 0x68 and hopelessly overlapped the
two fields, so OR-ing them corrupted both. That was not cosmetic: 0x68 decodes
as ``vane = BOTTOM, fan = auto``, so every command pinned the vane to the
bottom, and ``SWING = 0x80`` only ever set the dead bit 7 instead of moving the
vane to its swing code. Verified against two learned captures from the target
unit:

    cool @ 24 C, fan auto, vane auto  -> byte 9 = 0x40 = vane auto  | fan 0
    heat @ 22 C, fan low,  vane bottom -> byte 9 = 0x69 = vane bottom| fan 1
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional


# ---------------------------------------------------------------------------
# Enum-like constants (mirror mitsubishi.py)
# ---------------------------------------------------------------------------
class PowerMode:
    OFF = 0x00
    ON = 0x20


class ClimateMode:
    HOT = 0x08
    COLD = 0x18
    DRY = 0x10
    AUTO = 0x20


# Second climate value OR'd into byte 8 (ClimateAndHorizontalVanne).
_CLIMATE2 = {
    ClimateMode.HOT: 0x00,
    ClimateMode.COLD: 0x06,
    ClimateMode.DRY: 0x02,
    ClimateMode.AUTO: 0x00,
}


class ISeeMode:
    # Byte 6, bit 6. Verified: learned cool capture has 0x18 | 0x40 = 0x58.
    OFF = 0x00
    ON = 0x40


class PowerfulMode:
    # Byte 15. Note the learnt template already carries a 0x40 base bit, which
    # `build_frame` applies separately; Powerful is an additional bit.
    OFF = 0x00
    ON = 0x08


class VanneHorizontalMode:
    """Wide (horizontal) vane -- byte 8, bits 4-7.

    Values follow the reference implementation, which was verified against a
    real MSZ-FE12NA, and line up with the spec's WIDE VANNE table (the spec
    names the positions LEFT END / LEFT / MIDDLE / RIGHT / RIGHT END, i.e. this
    enum's LEFT / MIDDLE_LEFT / MIDDLE / MIDDLE_RIGHT / RIGHT).

    ``SWING`` is taken from the spec table (bit 7 = 0x80). It is the one value
    here that no learned capture covers, so treat it as unverified.
    """

    NOT_SET = 0x00
    LEFT = 0x10
    MIDDLE_LEFT = 0x20
    MIDDLE = 0x30
    MIDDLE_RIGHT = 0x40
    RIGHT = 0x50
    SWING = 0x80


class FanMode:
    """Fan speed -- byte 9, bits 0-2. 0 means auto (verified by capture)."""

    AUTO = 0x00
    SPEED1 = 0x01
    SPEED2 = 0x02
    SPEED3 = 0x03


class VanneVerticalMode:
    """Vertical vane -- byte 9, bits 3-6.

    AUTO / TOP / ... / BOTTOM are the fixed positions; SWING (0x78) is the
    oscillating code. Bit 7 must stay clear: the old 0x80 swing value set an
    unused bit and left the vane parked, which is why "swing on" never moved
    the louvre.
    """

    AUTO = 0x40
    TOP = 0x48
    MIDDLE_TOP = 0x50
    MIDDLE = 0x58
    MIDDLE_BOTTOM = 0x60
    BOTTOM = 0x68
    SWING = 0x78


class CleanMode:
    """Byte 14, bit 2, on top of the 0x10 base seen in learned captures."""

    BASE = 0x10
    OFF = 0x00
    ON = 0x04


class PlasmaMode:
    """Plasma -- byte 15. **The least certain field in the frame.**

    There are two competing answers and they disagree:

    * the spec's PLASMA table puts it on bit 2 (``SPEC = 0x04``);
    * the target unit's power-off capture carries byte 15 = 0x40, and this
      integration has always sent 0x40, which points at bit 6 (``ON``).

    Bit 6 is *unassigned* in the spec, so neither source explains the other.
    ``ON`` is kept as the default because it reproduces the frame this
    integration has always transmitted (changing it would alter the bytes the
    AC has been accepting for months), but treat an ON/OFF that does nothing
    as the expected failure mode until it is confirmed on the real unit.
    """

    OFF = 0x00
    ON = 0x40        # what the unit's capture shows / we have always sent
    SPEC = 0x04      # what the spec's PLASMA table says; try this if ON is inert


class InstallPosition:
    """Byte 15, bits 3-4 -- the installer "dip switch" for unit placement.

    The spec's INSTALL POSITION table notes its own default as "00 ?" and the
    two variants disagree on bit order, so this is the least certain field in
    the frame. It is opt-in: ``None`` leaves byte 15 untouched.
    """

    LEFT = 0x08
    MIDDLE = 0x10
    RIGHT = 0x18


class TimeControlMode:
    NO_TIME = 0x00
    START = 0x05
    END = 0x03
    BOTH = 0x07


class AreaMode:
    NOT_SET = 0x00
    LEFT = 0x40
    RIGHT = 0xC0
    FULL = 0x80


class Timing:
    """Pulse timings (microseconds) from the protocol spec (AnalysIR)."""

    FREQUENCY = 38000
    HDR_MARK = 3400
    HDR_SPACE = 1750
    BIT_MARK = 450
    ONE_SPACE = 1300
    ZERO_SPACE = 420
    RPT_MARK = 440
    RPT_SPACE = 17100
    NB_PACKETS = 2  # each command is sent twice


MIN_TEMP = 16
MAX_TEMP = 31

# Valid initial frame; only the variable bytes are overwritten.
_FRAME_TEMPLATE = [
    0x23, 0xCB, 0x26, 0x01, 0x00,  # header
    0x20,                            # power on
    0x08,                            # climate mode (heat)
    0x06,                            # temperature
    0x30,                            # climate2 | horizontal vane
    0x45,                            # fan | vertical vane
    0x67,                            # clock
    0x00,                            # end time
    0x00,                            # start time
    0x00,                            # time control | area
    0x14,                            # clean mode (0x10 base | clean on)
    0x00,                            # plasma | powerful | install position
    0x00,                            # constant
    0x1F,                            # checksum (recomputed)
]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _time_to_clock(value: Optional[time]) -> int:
    """Encode a wall-clock time in 1/6-hour units (e.g. 17:10 -> 103)."""
    if value is None:
        return 0
    return (value.hour * 6) + (value.minute // 10)


def build_frame(
    climate_mode: int = ClimateMode.AUTO,
    temperature: int = 21,
    fan_mode: int = FanMode.AUTO,
    vanne_vertical_mode: int = VanneVerticalMode.AUTO,
    vanne_horizontal_mode: int = VanneHorizontalMode.NOT_SET,
    isee_mode: int = ISeeMode.ON,
    area_mode: int = AreaMode.FULL,
    start_time: Optional[time] = None,
    end_time: Optional[time] = None,
    powerful: int = PowerfulMode.OFF,
    clean_mode: int = CleanMode.ON,
    plasma_mode: int = PlasmaMode.ON,
    install_position: Optional[int] = None,
    power_mode: int = PowerMode.ON,
    clock: Optional[int] = None,
) -> bytes:
    """Build the 18-byte IR frame for the given settings.

    ``clean_mode`` / ``plasma_mode`` default to ON because the frame this
    integration has always sent carries those bits; pass the OFF constant to
    clear them. ``install_position`` defaults to ``None`` so byte 15 is left
    exactly as it was unless an installer position is configured.
    """
    data = list(_FRAME_TEMPLATE)

    data[5] = power_mode

    data[6] = climate_mode | isee_mode

    data[7] = _clamp(int(temperature), MIN_TEMP, MAX_TEMP) - 16

    data[8] = _CLIMATE2.get(climate_mode, 0x00) | vanne_horizontal_mode

    # Byte 9 = two disjoint fields. The masks below are asserted by
    # `validate_byte9_fields()` so a future edit cannot silently re-introduce
    # the overlap that pinned the vane to the bottom.
    data[9] = (fan_mode & 0x07) | (vanne_vertical_mode & 0x78)

    if clock is None:
        now = datetime.now()
        data[10] = (now.hour * 6) + (now.minute // 10)
    else:
        data[10] = clock

    data[11] = _time_to_clock(end_time)
    data[12] = _time_to_clock(start_time)

    if end_time is not None and start_time is not None:
        time_control = TimeControlMode.BOTH
    elif end_time is not None:
        time_control = TimeControlMode.END
    elif start_time is not None:
        time_control = TimeControlMode.START
    else:
        time_control = TimeControlMode.NO_TIME
    data[13] = time_control | area_mode

    data[14] = CleanMode.BASE | clean_mode

    data[15] = plasma_mode | powerful
    if install_position is not None:
        # Bits 3-4. Bit 3 is shared with PowerfulMode.ON, so an install
        # position of LEFT/RIGHT cannot coexist with Powerful; that is
        # asserted below rather than silently emitting an ambiguous byte.
        if powerful & install_position & 0x18:
            raise ValueError(
                "powerful and install_position collide on byte 15 bit 3 "
                f"(powerful={powerful:#04x}, install={install_position:#04x})"
            )
        data[15] |= install_position & 0x18

    # Checksum: sum of the first 17 bytes, modulo 256.
    data[17] = sum(data[:-1]) % 256

    return bytes(data)


def validate_byte15_fields() -> None:
    """Assert that byte 15's three occupants stay in their own bits.

    Byte 15 carries plasma, powerful and the install position. The install
    position legitimately occupies bits 3-4, and ``PowerfulMode.ON`` is bit 3,
    so those two overlap by design of the protocol -- they can never be used
    together. Everything else must stay disjoint.
    """
    plasma_bits = PlasmaMode.ON & PlasmaMode.SPEC
    if plasma_bits:
        raise ValueError(
            "plasma ON (bit 6) and SPEC (bit 2) must not both be set; "
            f"overlap {plasma_bits:#04x}"
        )

    install_mask = InstallPosition.LEFT | InstallPosition.MIDDLE | InstallPosition.RIGHT
    if install_mask & ~0x18:
        raise ValueError(
            f"install position codes exceed bits 3-4 ({install_mask:#04x})"
        )

    if PowerfulMode.ON & ~0x08:
        raise ValueError("powerful exceeds bit 3")

    # Documented, deliberate overlap: powerful cannot be combined with an
    # install position of LEFT or RIGHT (build_frame raises if both are set).
    if not (PowerfulMode.ON & install_mask):
        raise ValueError(
            "expected powerful (bit 3) to overlap the install-position field; "
            "if that changed, revisit build_frame's collision check"
        )


def validate_byte9_fields() -> None:
    """Assert that the fan and vertical-vane fields in byte 9 stay disjoint.

    Raises ``AssertionError`` (so a test suite catches it cheaply) or
    ``ValueError`` if a fan or vane code ever strays into the other's bits.
    """
    fan_values = {
        "auto": FanMode.AUTO,
        "speed1": FanMode.SPEED1,
        "speed2": FanMode.SPEED2,
        "speed3": FanMode.SPEED3,
    }
    vane_values = {
        "auto": VanneVerticalMode.AUTO,
        "top": VanneVerticalMode.TOP,
        "middle_top": VanneVerticalMode.MIDDLE_TOP,
        "middle": VanneVerticalMode.MIDDLE,
        "middle_bottom": VanneVerticalMode.MIDDLE_BOTTOM,
        "bottom": VanneVerticalMode.BOTTOM,
        "swing": VanneVerticalMode.SWING,
    }

    for name, value in fan_values.items():
        if value & ~0x07:
            raise ValueError(f"fan code {name}={value:#04x} exceeds bits 0-2")

    for name, value in vane_values.items():
        if value & ~0x78:
            raise ValueError(
                f"vane code {name}={value:#04x} exceeds bits 3-6 "
                "(bit 7 is unused; a swing code of 0x80 never moved the vane)"
            )


def to_hex(frame: bytes, prefix: bool = False) -> str:
    """Render a frame as a hex string for `remote.send_command`."""
    value = frame.hex().upper()
    return f"0x{value}" if prefix else value


def modulate(frame: bytes, nb_packets: int = Timing.NB_PACKETS) -> list[int]:
    """Return the raw pulse durations (microseconds, alternating mark/space).

    This mirrors the timing spec: header, then one bit per byte (LSB first,
    as transmitted by the Mitsubishi FD remote), then a repeat mark/space,
    then the whole frame again.
    """
    pulses: list[int] = [Timing.HDR_MARK, Timing.HDR_SPACE]

    for byte in frame:
        for bit in range(0, 8):  # LSB first, as the FD remote transmits
            pulses.append(Timing.BIT_MARK)
            pulses.append(Timing.ONE_SPACE if (byte >> bit) & 1 else Timing.ZERO_SPACE)

    for _ in range(nb_packets - 1):
        pulses.append(Timing.RPT_MARK)
        pulses.append(Timing.RPT_SPACE)
        pulses.append(Timing.HDR_MARK)
        pulses.append(Timing.HDR_SPACE)
        for byte in frame:
            for bit in range(0, 8):  # LSB first
                pulses.append(Timing.BIT_MARK)
                pulses.append(
                    Timing.ONE_SPACE if (byte >> bit) & 1 else Timing.ZERO_SPACE
                )

    return pulses
