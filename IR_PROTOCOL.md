# Mitsubishi MSZ-FD25VA infrared protocol

This document describes the infrared (IR) protocol of the wireless remote for the
Mitsubishi Electric MSZ-FD25VA and MSZ-FD35VA indoor units (also the `-S` variants).
The service manual names the remote model KM08A [S4 3]. [S5] decoded frames from KM09D
remotes of the same MSZ-FD series. Those frames agree with this document.

Every value in this document has an evidence level (§0.4) and a source (§8).
Read §0 before you use any table.

---

## 0. Read this first

### 0.1 Conventions

- A **frame** is 18 bytes, numbered byte 0 to byte 17.
- A **transmission** is one frame, sent two times (§1).
- The **remote** is the handheld IR remote. The **unit** is the indoor unit.
- Bit 0 is the least significant bit (`0x01`). Bit 7 is the most significant bit (`0x80`).
- Hex values are normal hex numbers. `0x40` means "bit 6 = 1".
- Binary values have the prefix `0b` and are written bit 7 first. `0b0100_0000` = `0x40`.
- A **field value** is the number that a field holds. A **byte contribution** is the
  field value shifted to its bit position. Example: VANE = 5 has the byte contribution
  `0x28`. Byte 9 bit 6 is always 1, so with FAN = AUTO byte 9 is `0x68`.
- The remote sends each byte with bit 0 first. This order matters only on the wire (§1).
  All tables use normal hex values.
- `FIELD=VALUE` names one value of one field. Always write the field name.
  `MODE=AUTO`, `FAN=AUTO`, `VANE=AUTO` and `AREA=AUTO` are four different settings.

### 0.2 Canonical names

This document uses only the names in the first column.

| Name | What it controls | Other names in other sources (do not use) |
|---|---|---|
| VANE | Up/down airflow. One horizontal louver. VANE button. | Mitsubishi manuals: "horizontal vane". Home Assistant attribute: `swing_mode`. Version 0.4.0 of this repo: "vertical vane" (`VanneVerticalMode`). AnalysIR: "VANNE". IRremoteESP8266: `Vane`, "SwingV". |
| WIDE_VANE | Left/right airflow. Vertical louvers. WIDE VANE button. | Mitsubishi manuals: "vertical vane". Home Assistant attribute: `swing_horizontal_mode` (together with AREA). Version 0.4.0 of this repo: "horizontal vane" (`VanneHorizontalMode`). AnalysIR: "WIDE VANNE". IRremoteESP8266: `WideVane`, "SwingH". |
| AREA | i-see area control: OFF, LEFT, AUTO, RIGHT. AREA button. | Version 0.4.0 of this repo: `AreaMode` (`FULL` = AUTO, `NOT_SET` = OFF). AnalysIR: "AREA SWING" for OFF (wrong). |
| ISEE | i-see sensor control, on or off. i-see button. | "I-SEE", "i-see". |
| INSTALL_POS | Slide switch inside the remote: where the unit hangs on the wall. | "INSTALL POSITION", "HVAC LEFT / MID / RIGHT". |
| MODE | Operation mode: HEAT, DRY, COOL, AUTO. | AnalysIR: "HVAC MODE". Version 0.4.0 of this repo: `ClimateMode` with `HOT` = HEAT and `COLD` = COOL. |
| MODE2 | Mode-dependent bits in byte 8. Not a separate setting. | AnalysIR: "HVAC MODE" (same name as byte 6). Python port: `Climate2`, `__Hot2`. |
| ON_TIMER | Time when the unit turns on. START button. | AnalysIR: "START TIME", "START CLOCK". |
| OFF_TIMER | Time when the unit turns off. STOP button. | AnalysIR: "END TIME", "END CLOCK". |

### 0.3 Protocol model

- Every frame carries the full state. The protocol has no button codes.
- The remote stores the state. It sends all of the state at each button press.
- A power-off frame also carries the full state (capture C, §5.3).
- To change one setting, send the full state with that one field changed.

### 0.4 Evidence levels

| Level | Meaning |
|---|---|
| **CONFIRMED** | A real frame from an MSZ-FD remote (capture A, B or C) shows the value. The documents agree. |
| **STRONG** | Two or more independent sources agree, and one of them is specific to the MSZ-FD. No capture shows the value. |
| **WEAK** | One source shows the value, or only sources of one lineage, or only sources for other models. |
| **UNKNOWN** | No source shows it. §6 lists the open questions. |

Source IDs ([S1] to [S6], [A], [B], [C]) are defined in §8. [S1], [S2] and [S6] are one
lineage: [S2] edits [S1], and [S6] derives from the project of [S1]. [S5] is independent.

### 0.5 Common errors

1. The AnalysIR PDF [S1] prints the column labels `0 1 2 3 4 5 6 7` above each byte.
   The bit strings below these labels start with bit 7. The leftmost column is bit 7,
   not bit 0 (§7.1).
2. VANE (up/down) and WIDE_VANE (left/right) have opposite names in different sources (§0.2).
3. "LEFT" means `0x1` in some sources and `0x2` in others for WIDE_VANE (§3.5).
4. [S1] has 11 known errors for this remote. [S2] corrects 7 of them (§7.1, §7.2).
5. Other Mitsubishi remotes use more bits in the same frame. The MSZ-FD remote never
   sets them (§7.4).

---

## 1. Physical layer

| Item | Nominal value | Measured on an original MSZ-FD25 remote [A] | Evidence |
|---|---|---|---|
| Carrier | 38 kHz | – | [S5] [S6] |
| HDR_MARK | 3400 µs | 3434 µs | CONFIRMED |
| HDR_SPACE | 1750 µs | 1764 µs | CONFIRMED |
| BIT_MARK | 450 µs | 362 µs | CONFIRMED |
| ONE_SPACE | 1300 µs | 1322 µs | CONFIRMED |
| ZERO_SPACE | 420 µs | 444 µs | CONFIRMED |
| STOP_MARK | 440 µs | – | [S1] ("RPT_MARK") |
| GAP | 17100 µs | 17088 µs | CONFIRMED |

The nominal values come from [S1]. An IR receiver module changes marks and spaces by
tens of µs. Other working encoders use 3500 / 1700 / 430 / 1250 / 390 µs and a gap of
15500 to 17500 µs [S5] [S6].

Structure of one transmission:

```
TRANSMISSION = FRAME  GAP  FRAME
FRAME        = HDR_MARK  HDR_SPACE  BIT x 144  STOP_MARK
BIT          = BIT_MARK  then  ONE_SPACE (bit = 1)  or  ZERO_SPACE (bit = 0)
GAP          = one space of 17100 us
Bit order    = byte 0 first, byte 17 last. Inside each byte: bit 0 first, bit 7 last.
```

- The two frames of one transmission are identical. CONFIRMED [A] (raw capture of both frames).
- Each frame ends with STOP_MARK. Without it, a receiver cannot measure the space of the
  last bit (byte 17, bit 7).
- Example: byte 0 = `0x23` = `0b0010_0011`. The wire order of its bits is `1 1 0 0 0 1 0 0`.

---

## 2. Frame map

### 2.1 Bit grid

Each row is one byte, bit 7 on the left. `0` and `1` are constant bits.

```
Byte | bit 7     bit 6     bit 5     bit 4     bit 3     bit 2     bit 1     bit 0
-----+--------------------------------------------------------------------------------
  0  | <------------------------- constant 0x23 ------------------------------------>
  1  | <------------------------- constant 0xCB ------------------------------------>
  2  | <------------------------- constant 0x26 ------------------------------------>
  3  | <------------------------- constant 0x01 ------------------------------------>
  4  | <------------------------- constant 0x00 ------------------------------------>
  5  | 0         0         POWER     0         0         0         0         0
  6  | 0         ISEE      MODE.2    MODE.1    MODE.0    0         0         0
  7  | 0         0         0         0         TEMP.3    TEMP.2    TEMP.1    TEMP.0
  8  | WIDE.3    WIDE.2    WIDE.1    WIDE.0    0         MODE2.2   MODE2.1   MODE2.0
  9  | 0         1         VANE.2    VANE.1    VANE.0    FAN.2     FAN.1     FAN.0
 10  | <------------------------- CLOCK (10-minute units) -------------------------->
 11  | <------------------------- OFF_TIMER (10-minute units) ---------------------->
 12  | <------------------------- ON_TIMER (10-minute units) ----------------------->
 13  | AREA.1    AREA.0    0         0         0         T_ON      T_OFF     T_ANY
 14  | 0         0         ECONO     INST.1    INST.0    CLEAN     0         0
 15  | 0         PLASMA    0         0         0         0         0         0
 16  | 0         0         0         0         0         0         0         0
 17  | <------------------------- CHECKSUM ------------------------------------------>
```

Legend: WIDE = WIDE_VANE, INST = INSTALL_POS, ECONO = ECONO_COOL.
T_ON, T_OFF and T_ANY are the three bits of the TIMER field (byte 13).

### 2.2 Field table

| Byte | Bits | Mask | Field | Values (field value) | Section |
|---|---|---|---|---|---|
| 0–4 | all | – | HEADER | `23 CB 26 01 00` | §3.1 |
| 5 | 5 | `0x20` | POWER | 1 = ON, 0 = OFF | §3.2 |
| 6 | 6 | `0x40` | ISEE | 1 = on | §3.3 |
| 6 | 5–3 | `0x38` | MODE | 1 HEAT, 2 DRY, 3 COOL, 4 AUTO | §3.3 |
| 7 | 3–0 | `0x0F` | TEMP | °C − 16 (0–15) | §3.4 |
| 8 | 7–4 | `0xF0` | WIDE_VANE | `0x0` NONE, `0x1` FAR_LEFT, `0x2` LEFT, `0x3` CENTER, `0x4` RIGHT, `0x5` FAR_RIGHT, `0xC` SWING | §3.5 |
| 8 | 2–0 | `0x07` | MODE2 | HEAT 0, DRY 2, COOL 6, AUTO 0 | §3.5 |
| 9 | 6 | `0x40` | – | always 1 | §3.6 |
| 9 | 5–3 | `0x38` | VANE | 0 AUTO, 1–5 POS1–POS5, 7 SWING | §3.6 |
| 9 | 2–0 | `0x07` | FAN | 0 AUTO, 1 LOW, 2 MED, 3 HIGH, 4 SUPER_HIGH | §3.6 |
| 10 | all | `0xFF` | CLOCK | hour × 6 + minute ÷ 10 | §3.7 |
| 11 | all | `0xFF` | OFF_TIMER | same unit as CLOCK; 0 = not set | §3.8 |
| 12 | all | `0xFF` | ON_TIMER | same unit as CLOCK; 0 = not set | §3.8 |
| 13 | 7–6 | `0xC0` | AREA | 0 OFF, 1 LEFT, 2 AUTO, 3 RIGHT | §3.9 |
| 13 | 2–0 | `0x07` | TIMER | `0b000` none, `0b101` ON, `0b011` OFF, `0b111` both | §3.9 |
| 14 | 5 | `0x20` | ECONO_COOL | 1 = on | §3.10 |
| 14 | 4–3 | `0x18` | INSTALL_POS | 1 LEFT, 2 CENTER, 3 RIGHT | §3.10 |
| 14 | 2 | `0x04` | CLEAN | 1 = on | §3.10 |
| 15 | 6 | `0x40` | PLASMA | 1 = on | §3.11 |
| 16 | all | `0xFF` | – | always `0x00` | §3.12 |
| 17 | all | `0xFF` | CHECKSUM | (byte 0 + … + byte 16) mod 256 | §3.13 |

All bits that this table does not list are 0.

---

## 3. Byte reference

### 3.1 Bytes 0–4: HEADER

| Byte | Value |
|---|---|
| 0 | `0x23` |
| 1 | `0xCB` |
| 2 | `0x26` |
| 3 | `0x01` |
| 4 | `0x00` |

- These bytes are the same in every frame. CONFIRMED [A] [B] [C].
- Do not change them.
- UNKNOWN: the service manual describes jumpers J1 and J2 on the remote circuit board
  [S4 8-2]. They let up to four units in one room each accept only their own remote. The
  frames of the four remote numbers must differ, but no source shows where. All known
  frames come from unmodified remotes (§6, U1).

### 3.2 Byte 5: POWER

```
bit:  7   6   5      4   3   2   1   0
      0   0   POWER  0   0   0   0   0
```

| POWER | Byte 5 | Evidence |
|---|---|---|
| 1 = ON | `0x20` | CONFIRMED [A] [B] |
| 0 = OFF | `0x00` | CONFIRMED [C] |

- A power-off frame carries the full state. The unit stores the last settings [S4 9].

### 3.3 Byte 6: ISEE and MODE

```
bit:  7   6     5        4        3        2   1   0
      0   ISEE  MODE.2   MODE.1   MODE.0   0   0   0
```

MODE:

| MODE | Field value (bits 5–3) | Byte contribution | Evidence |
|---|---|---|---|
| HEAT | `0b001` | `0x08` | CONFIRMED [C] |
| DRY | `0b010` | `0x10` | STRONG [S1] [S2] [S5] |
| COOL | `0b011` | `0x18` | CONFIRMED [A] [B] |
| AUTO | `0b100` | `0x20` | STRONG [S1] [S2] [S5] |

- The MSZ-FD has no FAN mode. Field value `0b111` (`0x38`) is FAN on other models [S5].
  Do not send it.
- In AUTO, the unit selects COOL or HEAT from the room temperature [S3 En-5] [S4 9-4].

ISEE:

| ISEE | Byte contribution | Evidence |
|---|---|---|
| 1 = on | `0x40` | CONFIRMED [A] [B] [C] |
| 0 = off | `0x00` | STRONG [S1] [S2] [S5] |

Byte 6 for all combinations:

| | HEAT | DRY | COOL | AUTO |
|---|---|---|---|---|
| ISEE = 0 | `0x08` | `0x10` | `0x18` | `0x20` |
| ISEE = 1 | `0x48` | `0x50` | `0x58` | `0x60` |

Behavior of ISEE:

- The i-see button changes ISEE only in COOL or HEAT [S4 9-6]. ([S3 En-4] names only COOL.)
- After a battery change or a RESET, the remote sets ISEE = 1 [S4 9-6].
- The remote keeps ISEE through power-off [S4 9-6].
- The first MSZ-FD25 decoder (2013) matched byte 6 = `0x60` for AUTO and `0x50` for DRY
  [S5]. So the remote also keeps ISEE = 1 in AUTO and DRY. WEAK.
- The unit uses i-see control only in COOL and HEAT [S4 9-6].
- AREA needs ISEE = 1 (rule R4).

### 3.4 Byte 7: TEMP

```
bit:  7   6   5   4   3        2        1        0
      0   0   0   0   TEMP.3   TEMP.2   TEMP.1   TEMP.0
```

- TEMP = set temperature in °C − 16. The range 16–31 °C gives `0x00`–`0x0F` [S1] [S4 9-1].
- CONFIRMED: 24 °C = `0x08` [A] [B]. 22 °C = `0x06` [C].
- The step is 1 °C. This model has no half degrees.
- DRY: the unit sets its own target from the room temperature [S4 9-2]. The remote
  cannot set a temperature in DRY [S3 En-5]. The value that the remote sends in DRY is
  UNKNOWN (§6, U2). Send the last set temperature.
- Other models use bit 4 for +0.5 °C [S6]. The MSZ-FD remote never sets bit 4.

### 3.5 Byte 8: WIDE_VANE and MODE2

```
bit:  7        6        5        4        3   2         1         0
      WIDE.3   WIDE.2   WIDE.1   WIDE.0   0   MODE2.2   MODE2.1   MODE2.0
```

WIDE_VANE (bits 7–4):

| Field value | Byte contribution | Name | Meaning | Evidence |
|---|---|---|---|---|
| `0x0` | `0x00` | NONE | AREA is active (byte 13). The unit aims the louvers. | CONFIRMED [A] [B] [C]; [S2] [S5] |
| `0x1` | `0x10` | FAR_LEFT | first position of the button cycle | STRONG [S1] [S2] [S5] |
| `0x2` | `0x20` | LEFT | | STRONG [S1] [S2] [S5] |
| `0x3` | `0x30` | CENTER | | STRONG [S1] [S2] [S5] |
| `0x4` | `0x40` | RIGHT | | STRONG [S1] [S2] [S5] |
| `0x5` | `0x50` | FAR_RIGHT | | STRONG [S1] [S2] [S5] |
| `0xC` | `0xC0` | SWING | the louvers swing left and right | STRONG [S2] [S5] |

- Button cycle: FAR_LEFT → LEFT → CENTER → RIGHT → FAR_RIGHT → SWING → FAR_LEFT [S3 En-6].
- LEFT and RIGHT follow the icons on the remote display [S3 En-6].
- SWING is `0xC`, not `0x8`. [S1] shows `0x8`. Two independent MSZ-FD sources show `0xC`:
  [S2] (2019) and [S5] (2013).
- Other models use `0x6` ("wide") and `0x8` ("auto") [S6]. The MSZ-FD remote never sends them.
- Name conflict: [S5] and version 0.4.0 of this repo call `0x1` "LEFT" and `0x2` "MIDDLE_LEFT".
  [S1] calls `0x1` "LEFT END". Use the field value, not the name.

MODE2 (bits 2–0):

| MODE (byte 6) | MODE2 | Evidence |
|---|---|---|
| HEAT | `0b000` | CONFIRMED [C] |
| DRY | `0b010` | WEAK [S1] [S2] [S6] |
| COOL | `0b110` | CONFIRMED [A] [B] |
| AUTO | `0b000` | WEAK [S1] [S2] [S6] |

- MODE2 depends only on MODE. Always derive it from MODE (rule R2).
- The meaning of these bits is UNKNOWN.
- The encoder of [S5] sends MODE2 = 0 in every mode. That library targets this unit.
  So the unit probably accepts MODE2 = 0. No test confirms this (§6, U5). Send the table values.

Byte 8 = WIDE_VANE contribution OR MODE2. Examples:

| State | Byte 8 |
|---|---|
| COOL, AREA active | `0x06` [A] [B] |
| HEAT, AREA active | `0x00` [C] |
| HEAT, WIDE_VANE = SWING | `0xC0` |
| COOL, WIDE_VANE = CENTER | `0x36` |
| DRY, WIDE_VANE = FAR_RIGHT | `0x52` |

### 3.6 Byte 9: VANE and FAN

```
bit:  7   6   5        4        3        2       1       0
      0   1   VANE.2   VANE.1   VANE.0   FAN.2   FAN.1   FAN.0
```

FAN (bits 2–0):

| Field value | Name | Remote display | Evidence |
|---|---|---|---|
| 0 | AUTO | AUTO | CONFIRMED [A] [B] |
| 1 | LOW | 1 bar | CONFIRMED [C] |
| 2 | MED | 2 bars | STRONG [S1] [S5] |
| 3 | HIGH | 3 bars | STRONG [S1] [S5] |
| 4 | SUPER_HIGH | 4 bars | STRONG [S1] [S5] |

- Button cycle: AUTO → LOW → MED → HIGH → SUPER_HIGH → AUTO [S3 En-6].
- The unit has four fan speeds and AUTO [S4 3: "Fan speed regulator 4"].
- Field value 5 is QUIET or SILENT on other remotes [S5] [S6]. The MSZ-FD remote never sends it.
- Bit 7 is 0 in every MSZ-FD frame. This includes FAN=AUTO. CONFIRMED [A] [B] [C].
  [S1] and [S2] show FAN=AUTO as bit 7 = 1 (`0x80`). That is the encoding of other
  remotes. The base layout of [S1] comes from an MSZ-GF60VE remote. Do not set bit 7.

VANE (bits 5–3):

| Field value | Byte contribution with bit 6 | Name | Evidence |
|---|---|---|---|
| 0 | `0x40` | AUTO | CONFIRMED [A] [B] |
| 1 | `0x48` | POS1 (highest, horizontal) | STRONG [S1] [S2] [S5] |
| 2 | `0x50` | POS2 | STRONG [S1] [S2] [S5] |
| 3 | `0x58` | POS3 | STRONG [S1] [S2] [S5] |
| 4 | `0x60` | POS4 | STRONG [S1] [S2] [S5] |
| 5 | `0x68` | POS5 (lowest) | CONFIRMED [C] |
| 7 | `0x78` | SWING | STRONG [S1] [S2] [S5] |

- Field value 6 (`0x70`) is not used.
- Button cycle: AUTO → POS1 → POS2 → POS3 → POS4 → POS5 → SWING → AUTO [S3 En-6].
- Bit 6 is 1 in every MSZ-FD frame. [S1] calls bits 6–3 together "VANNE SET".
- With VANE=AUTO, the unit uses POS1 in COOL and DRY, and POS4 in HEAT [S4 9-5].
- In COOL and DRY, the unit moves POS3–POS5 to POS2 after 0.5 to 1 hour to stop dew
  [S4 9-5]. The remote does not change VANE for this.

Byte 9 = `0x40` OR (VANE << 3) OR FAN. Examples:

| State | Byte 9 |
|---|---|
| VANE=AUTO, FAN=AUTO | `0x40` [A] [B] |
| VANE=POS5, FAN=LOW | `0x69` [C] |
| VANE=POS4, FAN=MED | `0x62` |
| VANE=SWING, FAN=HIGH | `0x7B` |
| VANE=POS1, FAN=SUPER_HIGH | `0x4C` |

### 3.7 Byte 10: CLOCK

- CLOCK = hour × 6 + minute ÷ 10 (integer division). The unit of CLOCK is 10 minutes.
- Range: `0x00` (00:00) to `0x8F` (23:50).
- Examples: 06:00 = `0x24` and 16:00 = `0x60` [S1]. 16:20 = `0x62` [A].
- The remote displays minutes, but it sends 10-minute steps.
- The unit needs CLOCK for the timers [S4 9-10]. Send the current local time in every frame.
- Evidence: STRONG. [S1] gives three examples in this unit. The MSZ-FD frame template
  of [S5] holds CLOCK = `0x61` next to its default time 16:10, and 16 × 6 + 1 = `0x61`.
  The captures hold valid values. The true capture times are unknown.
- The MSZ-FD code path of [S5] calculates (hour × 60 + minute) ÷ 6. That formula
  disagrees with its own template and with [S1]. Do not use it.

### 3.8 Bytes 11 and 12: OFF_TIMER and ON_TIMER

| Byte | Field | Button |
|---|---|---|
| 11 | OFF_TIMER: the unit turns off at this time | STOP |
| 12 | ON_TIMER: the unit turns on at this time | START |

- Note the order: byte 11 is OFF, byte 12 is ON.
- Both fields use the CLOCK unit (10 minutes since 00:00).
- A field that is not set holds `0x00`.
- Example: OFF_TIMER at 22:00 = `0x84` [S1].
- The remote sets timer times in 10-minute steps [S3 En-7].
- Both timers can be active together. The earlier time runs first [S4 9-10].
- Evidence: WEAK [S1] [S2] [S6]. No MSZ-FD capture has a timer (§6, U7).

### 3.9 Byte 13: AREA and TIMER

```
bit:  7        6        5   4   3   2      1       0
      AREA.1   AREA.0   0   0   0   T_ON   T_OFF   T_ANY
```

TIMER (bits 2–0):

| Field value | Byte contribution | Meaning |
|---|---|---|
| `0b000` | `0x00` | no timer |
| `0b101` | `0x05` | ON_TIMER only |
| `0b011` | `0x03` | OFF_TIMER only |
| `0b111` | `0x07` | ON_TIMER and OFF_TIMER |

- Bit 2 (T_ON) = ON_TIMER is active. Bit 1 (T_OFF) = OFF_TIMER is active.
  Bit 0 (T_ANY) = 1 when any timer is active.
- Evidence: WEAK [S1] [S2] [S6]. No MSZ-FD capture has a timer.
- Other models use bit 3 for a weekly timer [S6]. The MSZ-FD remote never sets it.

AREA (bits 7–6):

| Field value | Byte contribution | Name | Meaning | Evidence |
|---|---|---|---|---|
| `0b00` | `0x00` | OFF | AREA is not active. WIDE_VANE aims the louvers. | STRONG [S2] [S5] |
| `0b01` | `0x40` | LEFT | Mainly the left part of the room | CONFIRMED [B] |
| `0b10` | `0x80` | AUTO | The i-see sensor scans left, center and right. The unit aims the louvers. | CONFIRMED [A] [C] |
| `0b11` | `0xC0` | RIGHT | Mainly the right part of the room | STRONG [S1] [S2] [S5] |

- Button cycle: AUTO → LEFT → RIGHT → OFF ("Cancel") → AUTO [S3 En-4] [S4 9-7].
- A WIDE VANE press also sets AREA = OFF [S3 En-4] [S4 9-7].
- AREA needs ISEE = 1 [S3 En-4] [S4 9-7 NOTE1] (rule R4).
- AREA controls only the left/right direction. VANE (byte 9) still sets the up/down
  direction [S4 9-7].
- [S1] names `0b00` "AREA SWING". That name is wrong. [S2] corrects it to "AREA OFF".

### 3.10 Byte 14: ECONO_COOL, INSTALL_POS and CLEAN

```
bit:  7   6   5            4        3        2       1   0
      0   0   ECONO_COOL   INST.1   INST.0   CLEAN   0   0
```

INSTALL_POS (bits 4–3):

| Field value | Byte contribution | Slide switch | Evidence |
|---|---|---|---|
| `0b01` | `0x08` | LEFT: wall or object less than 50 cm on the left | STRONG [S2] [S5] (and [S1] in byte 15) |
| `0b10` | `0x10` | CENTER: more than 50 cm on both sides | CONFIRMED [A] [C] |
| `0b11` | `0x18` | RIGHT: wall or object less than 50 cm on the right | CONFIRMED [B] |

- The slide switch is inside the battery compartment of the remote [S3 En-4] [S4 8-4].
- The value is constant for one installation.
- The unit uses it to aim the i-see sensor and the AREA LEFT/RIGHT control [S4 9-6] [S4 9-7].
- Field value `0b00` does not occur. The switch has three positions.
- [S1] puts this field in byte 15. That is wrong (§7.1).

CLEAN (bit 2):

| CLEAN | Byte contribution | Evidence |
|---|---|---|
| 1 = on | `0x04` | [C] has 1. Meaning: [S1] [S2] [S5]. |
| 0 = off | `0x00` | [A] [B] have 0. |

- Evidence level: STRONG for the bit position. The captures have no independent labels for CLEAN.
- The unit runs CLEAN when it stops after COOL for 3 minutes or more, or after DRY for
  6 minutes or more [S3 En-7] [S4 9-9].
- CLEAN takes about 40 minutes. The fan stays off for the first 15 minutes [S4 9-9].
- The ON/OFF button does not clear CLEAN [S3 En-7]. The OFF frame must carry CLEAN = 1 (rule R8).

ECONO_COOL (bit 5):

| ECONO_COOL | Byte contribution | Evidence |
|---|---|---|
| 1 = on | `0x20` | STRONG. [S2] for the MSZ-FD. [S5] (model SH24H) and [S6] use the same bit for other models. No MSZ-FD capture. |

- ECONO_COOL works only in COOL [S3 En-7].
- A VANE press or a mode change cancels ECONO_COOL [S4 9-5].
- With ECONO_COOL, the unit swings VANE in cycles and raises the target by 2 °C [S3 En-7] [S4 9-5].
- UNKNOWN: whether the remote also changes TEMP or VANE in the same frame (§6, U3).

Byte 14 for common states:

| INSTALL_POS | plain | + CLEAN | + ECONO_COOL | + CLEAN + ECONO_COOL |
|---|---|---|---|---|
| LEFT | `0x08` | `0x0C` | `0x28` | `0x2C` |
| CENTER | `0x10` | `0x14` | `0x30` | `0x34` |
| RIGHT | `0x18` | `0x1C` | `0x38` | `0x3C` |

### 3.11 Byte 15: PLASMA

```
bit:  7   6        5   4   3   2   1   0
      0   PLASMA   0   0   0   0   0   0
```

| PLASMA | Byte 15 | Evidence |
|---|---|---|
| 1 = on | `0x40` | STRONG [S2] [S5]. [C] has `0x40`. The repo owner reports that `0x40` works on the unit. |
| 0 = off | `0x00` | CONFIRMED [A] [B] |

- [S1] puts PLASMA at bit 2 (`0x04`). That is wrong.
- Other models use more bits of this byte (§7.4). The MSZ-FD remote never sets them.

### 3.12 Byte 16

- Always `0x00`. CONFIRMED [A] [B].
- Other models use this byte (§7.4).

### 3.13 Byte 17: CHECKSUM

- CHECKSUM = (byte 0 + byte 1 + … + byte 16) mod 256.
- CONFIRMED [A] [B].
- Example [A]: the sum of bytes 0–16 is `0x2CD`. CHECKSUM = `0xCD`.

---

## 4. Interaction rules

Follow rules R1–R13 when you build a frame. They describe what the real remote does.
The reaction of the unit to a broken rule is UNKNOWN (§6, U6).

| ID | Rule | Evidence |
|---|---|---|
| R1 | Send the full state in every frame. The protocol has no button codes. | CONFIRMED [C] (power-off frame with all fields) |
| R2 | Derive MODE2 from MODE (§3.5). | CONFIRMED for COOL and HEAT |
| R3 | AREA and WIDE_VANE exclude each other. If AREA ≠ OFF, then WIDE_VANE = NONE. If WIDE_VANE ≠ NONE, then AREA = OFF. | [A] [B] [C]; [S3 En-4]; [S4 9-7 NOTE3] |
| R4 | AREA ≠ OFF needs ISEE = 1. When you set ISEE = 0, also set AREA = OFF and send a WIDE_VANE value. | [S3 En-4]; [S4 9-7 NOTE1] |
| R5 | After AREA changes to OFF, the remote sends the WIDE_VANE value from before AREA. | [S4 9-7 NOTE2] |
| R6 | ECONO_COOL = 1 needs MODE = COOL. Clear ECONO_COOL when MODE or VANE changes. | [S3 En-7]; [S4 9-5] |
| R7 | The TIMER bits must match bytes 11 and 12. T_OFF = 1 only with an OFF_TIMER time. T_ON = 1 only with an ON_TIMER time. T_ANY = T_ON OR T_OFF. | WEAK [S1] [S2] [S6] |
| R8 | The unit reads CLEAN when it stops. To get a CLEAN run, send CLEAN = 1 in the OFF frame (POWER = 0). | [S3 En-7]; [S4 9-9] |
| R9 | ISEE changes only in COOL or HEAT. The bit stays in frames of the other modes. The unit uses it only in COOL and HEAT. | [S4 9-6]; [S5] |
| R10 | INSTALL_POS is constant for one installation. Use LEFT, CENTER or RIGHT, never `0b00`. | [S4 8-4] |
| R11 | Keep all constant bits: header bytes, byte 9 bit 6 = 1, byte 16 = `0x00`, and 0 in every unlisted bit. | CONFIRMED [A] [B] [C] |
| R12 | In DRY, the unit ignores TEMP. Send a valid TEMP (`0x00`–`0x0F`) anyway. | [S4 9-2] |
| R13 | Send each frame two times, as in §1. Calculate CHECKSUM last. | CONFIRMED [A] |

Expected but not proven: the remote always has exactly one of AREA and WIDE_VANE
active. No source shows a frame with AREA = OFF and WIDE_VANE = NONE. Do not send it.

Dependency summary:

| Field | Depends on | Relation |
|---|---|---|
| MODE2 | MODE | derived (R2) |
| AREA | WIDE_VANE | exclusive (R3) |
| AREA | ISEE | needs ISEE = 1 (R4) |
| ECONO_COOL | MODE, VANE | needs COOL; a VANE change cancels it (R6) |
| TIMER | bytes 11, 12 | bits match the set times (R7) |
| CLEAN | POWER | takes effect at POWER = 0 (R8) |
| ISEE | MODE | takes effect only in COOL and HEAT (R9) |
| TEMP | MODE | ignored in DRY (R12) |

---

## 5. Examples

### 5.1 Capture A: COOL 24 °C, FAN AUTO, VANE AUTO, AREA AUTO

`23 CB 26 01 00 20 58 08 06 40 62 00 00 80 10 00 00 CD`

| Byte | Hex | Binary | Decode |
|---|---|---|---|
| 0–4 | `23 CB 26 01 00` | – | HEADER |
| 5 | `20` | `0b0010_0000` | POWER = ON |
| 6 | `58` | `0b0101_1000` | ISEE = 1, MODE = `0b011` COOL |
| 7 | `08` | `0b0000_1000` | TEMP = 8 → 24 °C |
| 8 | `06` | `0b0000_0110` | WIDE_VANE = NONE, MODE2 = `0b110` (COOL) |
| 9 | `40` | `0b0100_0000` | bit 6 = 1, VANE = 0 AUTO, FAN = 0 AUTO |
| 10 | `62` | `0b0110_0010` | CLOCK = 98 → 16:20 |
| 11 | `00` | `0b0000_0000` | OFF_TIMER not set |
| 12 | `00` | `0b0000_0000` | ON_TIMER not set |
| 13 | `80` | `0b1000_0000` | AREA = `0b10` AUTO, TIMER = none |
| 14 | `10` | `0b0001_0000` | ECONO_COOL = 0, INSTALL_POS = `0b10` CENTER, CLEAN = 0 |
| 15 | `00` | `0b0000_0000` | PLASMA = 0 |
| 16 | `00` | `0b0000_0000` | constant |
| 17 | `CD` | `0b1100_1101` | CHECKSUM: sum = `0x2CD` → `0xCD` |

### 5.2 Capture B: differences from capture A

`23 CB 26 01 00 20 58 08 06 40 37 00 00 40 18 00 00 6A`

| Byte | A | B | Meaning in B |
|---|---|---|---|
| 10 | `62` | `37` | CLOCK = 55 → 09:10 |
| 13 | `80` | `40` | AREA = `0b01` LEFT |
| 14 | `10` | `18` | INSTALL_POS = `0b11` RIGHT |
| 17 | `CD` | `6A` | CHECKSUM |

All other bytes are the same as in A.

### 5.3 Capture C: power-off frame, HEAT 22 °C

`23 CB 26 01 00 00 48 06 00 69 53 00 00 80 14 40` (the repo copy has only bytes 0–15)

| Byte | Hex | Binary | Decode |
|---|---|---|---|
| 5 | `00` | `0b0000_0000` | POWER = OFF |
| 6 | `48` | `0b0100_1000` | ISEE = 1, MODE = `0b001` HEAT |
| 7 | `06` | `0b0000_0110` | TEMP = 6 → 22 °C |
| 8 | `00` | `0b0000_0000` | WIDE_VANE = NONE, MODE2 = `0b000` (HEAT) |
| 9 | `69` | `0b0110_1001` | bit 6 = 1, VANE = `0b101` POS5, FAN = `0b001` LOW |
| 10 | `53` | `0b0101_0011` | CLOCK = 83 → 13:50 |
| 13 | `80` | `0b1000_0000` | AREA = AUTO, TIMER = none |
| 14 | `14` | `0b0001_0100` | INSTALL_POS = CENTER, CLEAN = 1 |
| 15 | `40` | `0b0100_0000` | PLASMA = 1 |
| 16 | missing | – | expected `0x00` |
| 17 | missing | – | expected `0xF3` (if byte 16 = `0x00`) |

This frame shows R1: the OFF frame keeps MODE, TEMP, FAN, VANE, AREA, CLEAN and PLASMA.

### 5.4 Built frames (not captured)

These frames follow every rule in §4. No real remote produced them.

E1: HEAT 21 °C, FAN MED, VANE POS4, WIDE_VANE SWING, AREA OFF, ISEE 1, INSTALL_POS CENTER,
PLASMA on, CLOCK 07:30.

`23 CB 26 01 00 20 48 05 C0 62 2D 00 00 00 10 40 00 21`

E2: COOL 25 °C, FAN AUTO, VANE AUTO, AREA AUTO, ISEE 1, INSTALL_POS CENTER, CLEAN on,
CLOCK 22:10, OFF_TIMER 23:00, ON_TIMER 06:30.

`23 CB 26 01 00 20 58 09 06 40 85 8A 27 87 14 00 00 AD`

| Byte | E2 | Decode |
|---|---|---|
| 10 | `85` | CLOCK = 133 → 22:10 |
| 11 | `8A` | OFF_TIMER = 138 → 23:00 |
| 12 | `27` | ON_TIMER = 39 → 06:30 |
| 13 | `87` | AREA = AUTO (`0x80`), TIMER = `0b111` (`0x07`) |
| 14 | `14` | INSTALL_POS = CENTER, CLEAN = 1 |

### 5.5 Reference encoder and decoder

This Python code implements §2 to §4. Its asserts pass for captures A, B and C and for E1 and E2.

```python
HEADER = bytes([0x23, 0xCB, 0x26, 0x01, 0x00])
MODE = {"HEAT": 0b001, "DRY": 0b010, "COOL": 0b011, "AUTO": 0b100}       # byte 6 bits 5-3
MODE2 = {"HEAT": 0b000, "DRY": 0b010, "COOL": 0b110, "AUTO": 0b000}      # byte 8 bits 2-0
WIDE_VANE = {"NONE": 0x0, "FAR_LEFT": 0x1, "LEFT": 0x2, "CENTER": 0x3,
             "RIGHT": 0x4, "FAR_RIGHT": 0x5, "SWING": 0xC}               # byte 8 bits 7-4
FAN = {"AUTO": 0, "LOW": 1, "MED": 2, "HIGH": 3, "SUPER_HIGH": 4}        # byte 9 bits 2-0
VANE = {"AUTO": 0, "POS1": 1, "POS2": 2, "POS3": 3, "POS4": 4,
        "POS5": 5, "SWING": 7}                                           # byte 9 bits 5-3
AREA = {"OFF": 0b00, "LEFT": 0b01, "AUTO": 0b10, "RIGHT": 0b11}          # byte 13 bits 7-6
INSTALL_POS = {"LEFT": 0b01, "CENTER": 0b10, "RIGHT": 0b11}              # byte 14 bits 4-3


def to_units(hhmm):  # "HH:MM" -> 10-minute units since 00:00; None -> 0
    if hhmm is None:
        return 0
    h, m = map(int, hhmm.split(":"))
    return h * 6 + m // 10


def encode(power, mode, temp_c, fan, vane, wide_vane, area, isee, install_pos,
           clean=False, econo_cool=False, plasma=False, clock="00:00",
           off_timer=None, on_timer=None):
    assert 16 <= temp_c <= 31
    assert (area == "OFF") != (wide_vane == "NONE"), "R3: exactly one of AREA / WIDE_VANE"
    assert area == "OFF" or isee, "R4: AREA needs ISEE"
    assert not econo_cool or mode == "COOL", "R6: ECONO_COOL needs COOL"
    timer = (0b101 if on_timer else 0) | (0b011 if off_timer else 0)
    f = list(HEADER) + [
        0x20 if power else 0x00,                                         # 5
        (0x40 if isee else 0) | MODE[mode] << 3,                         # 6
        temp_c - 16,                                                     # 7
        WIDE_VANE[wide_vane] << 4 | MODE2[mode],                         # 8
        0x40 | VANE[vane] << 3 | FAN[fan],                               # 9 (bit 6 = 1)
        to_units(clock), to_units(off_timer), to_units(on_timer),        # 10, 11, 12
        AREA[area] << 6 | timer,                                         # 13
        (0x20 if econo_cool else 0) | INSTALL_POS[install_pos] << 3
        | (0x04 if clean else 0),                                        # 14
        0x40 if plasma else 0x00,                                        # 15
        0x00,                                                            # 16
    ]
    f.append(sum(f) % 256)                                               # 17
    return bytes(f)


def decode(f):
    name = lambda table, v: next(k for k, x in table.items() if x == v)
    hhmm = lambda v: f"{v // 6:02d}:{v % 6 * 10:02d}"
    assert f[:5] == HEADER and f[17] == sum(f[:17]) % 256
    mode = name(MODE, f[6] >> 3 & 0b111)
    return {
        "power": bool(f[5] & 0x20), "mode": mode, "isee": bool(f[6] & 0x40),
        "temp_c": (f[7] & 0x0F) + 16, "mode2_ok": f[8] & 0b111 == MODE2[mode],
        "wide_vane": name(WIDE_VANE, f[8] >> 4), "fan": name(FAN, f[9] & 0b111),
        "vane": name(VANE, f[9] >> 3 & 0b111),
        "clock": hhmm(f[10]),
        "off_timer": hhmm(f[11]) if f[13] & 0b010 else None,
        "on_timer": hhmm(f[12]) if f[13] & 0b100 else None,
        "area": name(AREA, f[13] >> 6), "clean": bool(f[14] & 0x04),
        "install_pos": name(INSTALL_POS, f[14] >> 3 & 0b11),
        "econo_cool": bool(f[14] & 0x20), "plasma": bool(f[15] & 0x40),
    }


if __name__ == "__main__":
    A = bytes.fromhex("23CB260100205808064062000080100000CD")
    B = bytes.fromhex("23CB2601002058080640370000401800006A")
    C = bytes.fromhex("23CB260100004806006953000080144000F3")  # bytes 16-17 completed
    assert encode(True, "COOL", 24, "AUTO", "AUTO", "NONE", "AUTO", True, "CENTER",
                  clock="16:20") == A
    assert encode(True, "COOL", 24, "AUTO", "AUTO", "NONE", "LEFT", True, "RIGHT",
                  clock="09:10") == B
    assert encode(False, "HEAT", 22, "LOW", "POS5", "NONE", "AUTO", True, "CENTER",
                  clean=True, plasma=True, clock="13:50") == C
    E1 = encode(True, "HEAT", 21, "MED", "POS4", "SWING", "OFF", True, "CENTER",
                plasma=True, clock="07:30")
    E2 = encode(True, "COOL", 25, "AUTO", "AUTO", "NONE", "AUTO", True, "CENTER",
                clean=True, clock="22:10", off_timer="23:00", on_timer="06:30")
    assert E1 == bytes.fromhex("23 CB 26 01 00 20 48 05 C0 62 2D 00 00 00 10 40 00 21")
    assert E2 == bytes.fromhex("23 CB 26 01 00 20 58 09 06 40 85 8A 27 87 14 00 00 AD")
    for f in (A, B, C, E1, E2):
        print(f.hex(" ").upper(), decode(f))
```

---

## 6. Open questions

| ID | Question | What is known |
|---|---|---|
| U1 | Where does the frame carry the remote number (jumpers J1 and J2)? | [S4 8-2] describes four remote numbers. The first remote that a unit receives after power-on becomes its remote. All known frames come from unmodified remotes. |
| U2 | What TEMP does the remote send in DRY? | The unit ignores it [S4 9-2]. No DRY capture exists. |
| U3 | Does the remote change TEMP or VANE when ECONO_COOL = 1? | The unit adds 2 °C and swings VANE [S4 9-5]. No ECONO_COOL capture exists. |
| U4 | How is the "no direct airflow" function encoded? A VANE press of 2 seconds or more moves VANE to horizontal and stops the compressor for 3 minutes. | [S4 9-5 (9)] describes it. No source shows the frame. VANE code 6 is unused, but nothing links it to this function. |
| U5 | What do the MODE2 bits mean? Does the unit accept MODE2 = 0 in COOL and DRY? | [S5] sends MODE2 = 0 in every mode and targets this unit. Not tested. |
| U6 | How does the unit react to frames that break §4 (AREA with ISEE = 0, AREA together with WIDE_VANE, FAN bit 7 = 1)? | Not tested. |
| U7 | Which POWER value does the remote send with an ON_TIMER? Does it clear byte 11 or 12 after a timer runs? | [S4 9-5] says the unit waits with VANE closed while an ON_TIMER is pending. No timer capture exists. |
| U8 | Which AREA and WIDE_VANE values does the remote send after a battery change or RESET? | ISEE = 1 after a reset [S4 9-6]. The rest is unknown. |

---

## 7. Errors in other sources

### 7.1 AnalysIR PDF v1.1 [S1]

| # | [S1] says | Correct for the MSZ-FD remote | Fixed in [S2] |
|---|---|---|---|
| 1 | Column labels `0 1 2 3 4 5 6 7` above each byte | The bit strings start with bit 7. The leftmost column is bit 7. Example: the header row shows `0x23` as `0 0 1 0 0 0 1 1`. | No |
| 2 | Byte 8 mode rows show the high nibble `0011` | The high nibble is WIDE_VANE. `0011` (CENTER) came from the example frame. | Yes |
| 3 | WIDE VANNE SWING = `1000` (`0x80`) | `1100` (`0xC0`) | Yes |
| 4 | No WIDE_VANE value for "AREA active" | `0000` (`0x00`) | Yes |
| 5 | AREA `00` = "AREA SWING" | AREA `00` = OFF (WIDE_VANE is active) | Yes |
| 6 | PLASMA = byte 15 bit 2 (`0x04`) | byte 15 bit 6 (`0x40`) | Yes |
| 7 | INSTALL POSITION in byte 15, "Default: 00 ?" | byte 14, bits 4–3. Never `00`. | Yes |
| 8 | No ECONO COOL field | byte 14 bit 5 (`0x20`) | Yes |
| 9 | FAN AUTO = bit 7 set (`0x80`) | FAN = `0b000` with bit 7 = 0 | No |
| 10 | Bytes 14, 15 and 16 are labeled "CONSTANT 0x00" | Bytes 14 and 15 hold fields. | No |
| 11 | Byte 6 AUTO row shows bit 6 = 0 | That is an example value. The remote also sends ISEE = 1 in AUTO. | No |

The example frame in the hex row of [S1] (`… 05 30 45 54 …`) probably comes from the
MSZ-GF60VE remote. Its byte 9 = `0x45` uses FAN code 5, which the MSZ-FD remote never sends.

### 7.2 XLSX update by kpbojan, 2019 [S2]

- The red cells are the corrections. A cell-by-cell comparison with the original
  `Debug/Mitsubishi_IR_Code3.xlsm` of HVAC-IR-Control confirms them.
- [S2] fixes items 2–8 of §7.1.
- [S2] keeps items 1, 9, 10 and 11 of §7.1.

### 7.3 This repo's integration before version 0.5.0

Version 0.4.0 of the integration (commit `f00b91c`) had these errors. Version 0.5.0
fixes all of them. The list stays here because copies of the old code may still exist.

| Location in 0.4.0 | Problem | Correct value |
|---|---|---|
| `mitsubishi_protocol.py` `CleanMode.BASE = 0x10` | `0x10` is INSTALL_POS = CENTER, not a CLEAN base. | CLEAN is only bit 2. |
| `InstallPosition` and `build_frame()` | INSTALL_POS is written to byte 15 bits 4–3. Byte 14 keeps CENTER. | Byte 14 bits 4–3. |
| `PowerfulMode` (byte 15 bit 3) | POWERFUL comes from an MSZ-FE12NA port. The MSZ-FD has no POWERFUL function. | Do not set byte 15 bit 3. |
| `PlasmaMode.SPEC = 0x04` | Copy of error 6 in §7.1. | `PlasmaMode.ON = 0x40` is correct. |
| `VanneHorizontalMode.SWING = 0x80` | Copy of error 3 in §7.1. | `0xC0` |
| `build_frame()` default `area_mode=AreaMode.FULL` | AREA = AUTO is always sent. This breaks R3 when WIDE_VANE ≠ NONE and R4 when ISEE = 0. AREA LEFT and RIGHT are not available. | Follow R3–R5. |
| `FanMode` | No SUPER_HIGH. | FAN = 4 |
| `modulate()` | The pulse list ends without STOP_MARK after the second frame. | Add a 440 µs mark at the end. |
| Class names | `VanneVerticalMode` is VANE (up/down). `VanneHorizontalMode` is WIDE_VANE (left/right). | §0.2 |
| README §3, §4, §6b, §7 and `tests/` | They repeat the problems above (for example "clean base 0x10" and install position in byte 15). | This document |

The "cool @ 24 °C" capture in the 0.4.0 README and in the tests (now
`tests/verify_protocol.py`) is identical to the frame in IRremoteESP8266 issue #1825,
including the CLOCK byte. It is probably that capture, not a capture from this repo's unit.

### 7.4 Bits that only other Mitsubishi remotes use

The MSZ-FD remote never sets these bits. Generic libraries and other model documents use them.

| Byte and bits | Meaning on other models | Source |
|---|---|---|
| 6, bits 5–3 = `0b111` | FAN mode | [S5] (FE, MSY) |
| 7, bit 4 | +0.5 °C | [S6] |
| 7 = `0x00` with 15 bit 5 | 10 °C maintenance heat (i-Save) | [S5] (FE, KJ), [S6] |
| 8, bits 7–4 = `0x6` or `0x8` | WIDE_VANE "wide" or "auto" | [S6] |
| 9, bit 7 | FAN AUTO flag | [S1], [S6], Python port |
| 9, FAN = 5 | QUIET or SILENT | [S5], [S6] |
| 13, bit 3 | Weekly timer | [S6] |
| 15, bit 3 | POWERFUL | Python port (MSZ-FE12NA) |
| 15, bits 2–0 | Direct/indirect airflow, absence detection | [S6] |
| 16 | 1-flow, natural flow, left VANE | [S5] (KJ), [S6] |

Other pitfalls in generic code:

- IRremoteESP8266 `setMode()` rewrites all of byte 8. This sets WIDE_VANE to CENTER.
- IRremoteESP8266 documents CLOCK with "4pm = 48". The correct value is 96 (`0x60`).
- The encoder of [S5] sends ISEE = 0, AREA = OFF and MODE2 = 0 for this model.

---

## 8. Sources

| ID | Source | Use in this document |
|---|---|---|
| S1 | `Mitsubishi_IR_Packet_Data_v1.1-FULL.pdf` in this repo. Vincent Cruvellier / AnalysIR, v1.1, April 2015. Also in [r45635/HVAC-IR-Control](https://github.com/r45635/HVAC-IR-Control) `Protocol/`. | Timings. Base layout from an MSZ-GF60VE remote. The green fields are for the MSZ-FD25. Errors: §7.1. |
| S2 | `Mitsubishi_IR_Code3.update.xlsx` in this repo. kpbojan, 2019-02-06. Posted in [HVAC-IR-Control issue #29](https://github.com/r45635/HVAC-IR-Control/issues/29), "some corections for MSZ-FD25VA". | MSZ-FD corrections (red cells). |
| S3 | `Mitsubishi_Electric_MSZ-FD25VA.pdf` in this repo (operating instructions). "En-N" is the printed page number. | Button cycles, feature behavior. |
| S4 | `mszfd25va_service_manual.pdf` in this repo. Numbers are section numbers. Section 3 names the remote KM08A. | Feature behavior, rules. |
| S5 | ToniA: [arduino-heatpumpir](https://github.com/ToniA/arduino-heatpumpir) `MitsubishiHeatpumpIR.cpp/.h` ("MSZ FD-25, remote control P/N KM09D 0052376") and [Raw-IR-decoder-for-Arduino](https://github.com/ToniA/Raw-IR-decoder-for-Arduino) `rawirdecode/MitsubishiElectric.cpp`. Decoder history: 2013 commits `5ced7e7`, `9f89454` (MSZ-FD25 with remote KM09D 0052376: ISEE, PLASMA, VANE, WIDE_VANE with SWING `0xC0`, FAN AUTO = 0). 2020 commit `353eb9f` (MSZ-FD50VF, remote KM09D/0096695: CLEAN, AREA, INSTALL_POS, WIDE_VANE NONE). 2026 commit `c74c528` (model SH24H: ECONO_COOL). | Independent check of [S1] and [S2]. The 2013 and 2020 parts come from MSZ-FD remotes. |
| S6 | [IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266) `src/ir_Mitsubishi.h` and `.cpp` (`IRMitsubishiAC`, `Mitsubishi144Protocol`). | Generic library for many models. Used only for timings, units and §7.4. |
| A | Capture of an original MSZ-FD25 remote, [IRremoteESP8266 issue #1825](https://github.com/crankyoldgit/IRremoteESP8266/issues/1825) (2022). Raw output of the [S5] decoder, both frames, with measured timings. The same bytes are in `tests/verify_protocol.py`. | CONFIRMED values |
| B | Second capture of the same remote in the same issue (Tasmota receiver). Checksum valid. | CONFIRMED values |
| C | `CAP_C16` in `tests/verify_protocol.py` (`CAP_OFF` in the 0.4.0 tests). The repo describes it as a learned capture from this repo's unit. Only bytes 0–15. | CONFIRMED values |

Other inputs:

- The Python port `python/hvac_ircontrol/mitsubishi.py` of HVAC-IR-Control ("Tested on
  Mitsubishi Model MSZ-FE12NA") is the origin of `PowerfulMode`, FAN AUTO = `0x80`, and
  the byte 14 = `0x10` template in version 0.4.0 of this repo. It describes another model.
- The repo owner reports that PLASMA = byte 15 `0x40` works on the unit.
