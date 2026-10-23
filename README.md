# mitsubishi_remote (custom component)

Control a **Mitsubishi MSZ-FD25** (or any MSZ-FD series) air conditioner from
Home Assistant **without flashing your IR blaster**. This integration sits on
top of your existing **LocalTuyaIR (`localtuya_rc`) `remote` entity** and
exposes a proper `climate` entity.

```
Nedis WIFIRC10CBK (Tuya IR)
        │  localtuya_rc → remote.localtuya_ir
        ▼
┌─────────────────────────────────────┐
│  mitsubishi_remote (this component) │  − encodes MSZ-FD IR frames
│  climate entity                      │  − calls remote.send_command
└─────────────────────────────────────┘
```

The encoder is a faithful port of the working implementation you provided
(HVAC-IR-Control, HVAC Masse / r45635), which was verified against a real Mitsubishi
unit and matches the AnalysIR reverse-engineering spec for the MSZ-FD25VA.

## 1. Install

### With HACS

This repo is laid out the way HACS expects, so it can be added as a custom
repository:

1. HACS → ⋮ (top right) → **Custom repositories**
2. URL: `https://github.com/vhtkrk/mitsubishi_remote`
3. Category: **Integration**
4. Install, then restart Home Assistant.

> **Note:** from Home Assistant 2026.11 HACS becomes the built-in
> **Marketplace** and the HACS custom integration is blocked. The same
> `hacs.json` in this repo is honoured by the Marketplace, so nothing here
> needs changing — install the same way from Settings → Devices & Services.

### Manually

Copy the `custom_components/mitsubishi_remote` folder into your Home Assistant
`config/custom_components/` directory, then restart Home Assistant.

```
config/
└── custom_components/
    └── mitsubishi_remote/
        ├── __init__.py
        ├── climate.py
        ├── const.py
        ├── manifest.json
        ├── mitsubishi_protocol.py
        ├── services.yaml
        └── switch.py
```

Required repo layout (HACS only looks inside `custom_components/`):

```
mitsubishi_remote/
├── hacs.json                 # HACS / Marketplace metadata
├── README.md
├── custom_components/
│   └── mitsubishi_remote/     # <- the integration itself
├── tests/
└── .github/workflows/validate.yml
```

## 2. Configure

Add a `climate` platform entry to `configuration.yaml`. The three feature
switches (§6b) are created automatically -- there is no `switch:` entry:

```yaml
climate:
  - platform: mitsubishi_remote
    name: Bedroom AC
    remote_entity: remote.localtuya_ir   # your LocalTuyaIR remote entity
    command_format: hex                   # hex | name
    hex_prefix: false                     # prepend "0x" to the payload
    retries: 3                            # resend count (Tuya blasters drop frames)
    repeat_gap: 0.35                      # seconds between resends
    install_position: middle              # optional: left | middle | right
```

| Key | Default | Meaning |
| --- | --- | --- |
| `remote_entity` | – (required) | entity_id of your LocalTuyaIR remote |
| `command_format` | `hex` | `hex` sends the frame as a hex string; `name` sends it as a named command (you then manage the payload mapping on the remote side) |
| `hex_prefix` | `false` | prepend `0x` to the payload |
| `retries` | `2` | number of times each frame is sent |
| `repeat_gap` | `0.35` | seconds between resends |
| `install_position` | unset | installer "dip switch" for where the unit is mounted: `left`, `middle`, `right`. Unset leaves byte 15 untouched (see §7) |

### Install position (the installer dip switch)

```yaml
climate:
  - platform: mitsubishi_remote
    name: Bedroom AC
    remote_entity: remote.localtuya_ir
    install_position: middle      # left | middle | right, or omit
```

This is a one-time installation setting (where the indoor unit sits on the
wall), not a daily control, so it is a config option rather than an entity.
Omit it and byte 15 is left exactly as before. It only ever writes bits 3–4 of
byte 15, so the plasma/powerful bits are unaffected.

## 3. Verify before using

Use the debug service to confirm the AC reacts before you trust the UI:

```yaml
service: mitsubishi_remote.force_send
target:
  entity_id: climate.bedroom_ac      # optional; all instances if omitted
data:
  hvac_mode: cool
  temperature: 24
  fan_mode: auto                     # auto | low | medium | high
  power: true
```

The service is registered from `climate.py` (see §7) and is available in
*Developer tools → Actions* as **Mitsubishi MSZ-FD AC (IR remote): Force send
IR command**. It does not change the entity's state.

You can also compare against a frame you have *learned* with
`remote.learn_command`. A captured MSZ-FD25 "cool @ 24 °C, fan auto" frame is:

```
23 CB 26 01 00 20 58 08 06 40 62 00 00 80 10 00 00 CD
```

The encoder's frame for the same state (with the clock byte zeroed for the
example — in practice the clock byte reflects the current time) is:

```
23 CB 26 01 00 20 58 08 06 40 00 00 00 80 14 40 00 AF
```

Byte 9 is now `0x40` (fan auto | vane auto), matching the capture, where older
versions emitted `0x68` (which is vane *bottom*). The only remaining
differences from the captured frame are the clock/timer bytes (byte 10 = the
time it was captured) and the two deliberate bits covered in §7: byte 14's
clean bit (`0x10`→`0x14`) and byte 15's plasma bit (`0x00`→`0x40`).

## 4. Protocol notes (from your spec)

- 144-bit (18 byte) frame, **sent twice** back-to-back, 38 kHz carrier.
- Timings (µs): header mark 3400, header space 1750, bit mark 450,
  one-space 1300, zero-space 420, repeat mark 440, repeat space 17100.
- Checksum byte 17 = `(byte0 + … + byte16) mod 256`.
- Byte 5: power (`0x20` = ON, `0x00` = OFF).
- Byte 6: mode (`0x08` heat, `0x18` cool, `0x10` dry, `0x20` auto) | I-See.
- Byte 7: `temperature − 16` (16–31 °C).
- Byte 8: secondary mode bits | **wide (horizontal) vane** in bits 4–7
  (`0x10` left … `0x50` right, `0x80` swing).
- Bits are transmitted **LSB-first** per byte (as the FD remote sends them).
- Byte 9: **two disjoint fields** — fan speed in bits 0–2 (`0` = auto, 1/2/3 =
  low/medium/high) and the **vertical vane** in bits 3–6 (`0x40` auto, `0x48`
  top … `0x68` bottom, `0x78` swing). Bit 7 is unused and must stay clear.
  Verified against the two learned captures below.
- Bytes 10–13: clock, end time, start time, time-control|area (area default
  FULL = `0x80`).
- Byte 14: clean mode — base `0x10` seen in captures, bit 2 (`0x04`) = clean on
  (hence the `0x14` this integration historically sent).
- Byte 15: plasma (`0x40` hypothesis) | powerful (`0x08`) | install position
  (bits 3–4).

### Byte 9 — the field overlap that was fixed in 0.3

Earlier versions treated byte 9 as `fan_base | vane` with a fan base of `0x68`.
Those fields **overlap**, and `0x68` is not a fan code at all — it decodes as
`vane = BOTTOM, fan = auto`. The consequences were real, not cosmetic:

- every command pinned the vertical vane to the bottom (blowing straight down),
  because `fan | vane` OR-ed `0x68` into the vane bits;
- "swing on" only set bit 7 (`0x80`), which is unused in byte 9, so the louvre
  never oscillated;
- fan *speeds* happened to survive, which is why the bug was easy to miss.

The reference implementation and the spec's own bit table both describe the fan
as bits 0–2 and the vane as bits 3–6, and that split reproduces both captures
exactly:

```
fan auto (0x00) | vane auto   (0x40) = 0x40   ✓ cool capture
fan low  (0x01) | vane bottom (0x68) = 0x69   ✓ power-off capture
```

`validate_byte9_fields()` in `mitsubishi_protocol.py` now asserts the two fields
stay disjoint, so a future edit cannot silently re-introduce the overlap.

## 5. State after a restart or reboot

The entity restores its last state on startup (HA `RestoreEntity`): HVAC mode,
setpoint, fan and swing come back exactly as you left them, so a reboot no
longer drops the card back to *Off / 24 °C / Auto*.

Two details worth knowing:

- **Restoring never transmits IR.** The link is one-way, so blasting a frame at
  startup would fight any change made with the wall remote while HA was down.
  The entity restores the *displayed* state only; press a button to re-sync the
  unit if needed.
- **The active mode survives an off state.** HA only persists `hvac_mode`, so an
  `off` entity would otherwise forget it was in *heat*; the active mode is
  stored in extra restore data (`active_mode`). Powering back on therefore
  returns to the previous real mode instead of a silent AUTO.

Look for this log line at startup to confirm it worked:

```
mitsubishi_remote.climate.restored: climate.bedroom_ac restored: mode=heat temp=23 fan=high swing=off (no IR sent)
```

## 6. Fan and swing values (icons)

Fan and swing use Home Assistant's own climate vocabulary, because the
frontend resolves each value's icon by **exact string** against
`homeassistant/components/climate/icons.json`. A value that is not a key in
that map renders as an unlabelled `mdi:circle-medium` dot.

| Attribute | Controls | Values | Icons |
| --- | --- | --- | --- |
| `fan_mode` | fan speed (byte 9 bits 0–2) | `auto`, `low`, `medium`, `high` | `mdi:fan-auto`, `mdi:speedometer-slow`, `mdi:speedometer-medium`, `mdi:speedometer` |
| `swing_mode` | **vertical** vane (byte 9 bits 3–6) | `off`, `on` | `mdi:arrow-oscillating-off`, `mdi:arrow-oscillating` |
| `swing_horizontal_mode` | **wide / horizontal** vane (byte 8 bits 4–7) | `off`, `on` | `mdi:arrow-oscillating-off`, `mdi:arrow-expand-horizontal` |

`swing_mode` and `swing_horizontal_mode` are two **independent axes**, which is
exactly what HA models with `SWING_MODE` + `SWING_HORIZONTAL_MODE`. Both
oscillate their own louvre, so "both" is simply both set to `on`. (HA's
`swing_mode: both` key is deliberately not used: a single enum cannot express
two independently-swinging vanes.)

Older spellings are still accepted in service calls, YAML automations and
restored state, and are mapped on the way in:

| Accepted | Canonical |
| --- | --- |
| `Auto`, `Low`, `Med`, `Medium`, `Mid`, `High` | `auto`, `low`, `medium`, `medium`, `medium`, `high` |
| `swing`, `on`, `vertical`, `oscillate` | `on` |
| `off`, `auto` (swing) | `off` |

So 0.1-era automations calling `fan_mode: High` keep working — they are stored
as `high`, which both the protocol encoder and the icon map understand. Note
that `med` is **not** a key in HA's icon map; `medium` is.

Horizontal-swing aliases (`swing`, `oscillate`, `horizontal` → `on`) work
the same way. Note that the old capitalised `Med` mapped to byte `0x6A` under
the pre-0.3 (broken) encoding; it now correctly encodes as `0x42`
(vane auto `0x40` | fan medium `0x02`).

## 6b. Feature switches (i-see, clean, plasma)

Three `switch` entities are created automatically for each climate entity:

| Entity | Frame bit | Status |
| --- | --- | --- |
| `switch.<name>_i_see` | byte 6, bit 6 (`0x40`) | verified by the learned cool capture |
| `switch.<name>_clean` | byte 14, bit 2 (`0x04`) | consistent with both captures |
| `switch.<name>_plasma` | byte 15, bit 6 (`0x40`) | **experimental** — see below |

They are independent on/off settings, not climate modes, which is why they are
switches rather than `preset_mode` values (a preset enum would make them
mutually exclusive). All three default to **on**, which reproduces the frame
this integration has always sent — upgrading changes nothing on the wire until
you touch a switch.

Each switch owns exactly one bit, so toggling one changes one byte (plus the
checksum) and leaves everything else alone. A no-op toggle sends nothing, and
while the AC is off a toggle updates the entity without transmitting — the
frame carries a power bit, so sending while "off" would wake the unit.

### Plasma is unverified

The spec's PLASMA table puts plasma on **bit 2** (`0x04`); the unit's own
power-off capture carries **bit 6** (`0x40`), which is what this integration
has always sent. Bit 6 is unassigned in the spec, so the two sources do not
reconcile. `ON = 0x40` is the default because it reproduces the bytes your AC
has been accepting.

If the Plasma switch appears to do nothing, try the spec's bit instead:

```python
# custom_components/mitsubishi_remote/mitsubishi_protocol.py
class PlasmaMode:
    ON = 0x04    # was 0x40 -- the spec's PLASMA bit
```

`PlasmaMode.SPEC = 0x04` is already defined for this. A warning naming plasma
as experimental is logged at startup for that reason.

## 7. Known limitations

- **No status feedback:** the IR link is one-way; the entity state is
  *desired* state, not unit state. If the AC is changed with the wall remote,
  HA will not know. State restoration preserves HA's own last-known state; it
  cannot detect a change made while HA was off.
- **Unverified bits** (the honest list):
  - *Plasma* (byte 15 bit 6) is a **hypothesis**: the two learned captures differ
    in byte 15 (`0x00` vs `0x40`), and this integration has always sent `0x40`.
    It reproduces the power-off capture but not the cool one, so the bit is
    either plasma, retained state, or something else.
  - *Wide-vane swing* (`0x80` in byte 8) comes from the spec's WIDE VANNE table;
    no capture covers it.
  - *Install position* (byte 15 bits 3–4) is the least certain field: the spec
    annotates its own default as "00 ?" and the two unit variants disagree on
    bit order. It is opt-in for that reason — if the AC misbehaves after setting
    it, remove the option and byte 15 returns to the previous behaviour.
  - *Clean* (byte 14 bit 2) matches "this integration has always sent `0x14`"
    and one of the two capture-byte differences, but not the other.
- **The regression tests are not in the repo.** They live outside the
  component (pure-Python, run against a real `homeassistant` wheel) because a
  custom component cannot ship its own test runner.
- **Power-off keeps your settings:** the power-off frame is the current state
  with only the power bit (byte 5) cleared, matching the learned remote capture.
  It no longer forces AUTO @ 21 °C. Note this means the mode/temperature bytes
  are still present in an off frame — the unit ignores them while powered off.
- LocalTuyaIR is not actively maintained; if the `remote.send_command` payload
  format for your device differs from a plain hex string, adjust
  `command_format` / `hex_prefix`, or map payloads to pre-registered button
  IDs (`command_format: name`).

## 8. Where the code lives

`climate.py` is the only entry point for a YAML platform: Home Assistant calls
the `async_setup_platform` defined **there**, and `__init__.py` is never used as
a setup hook (there is no config entry to set up). Earlier versions registered
`force_send` in `__init__.py`, so the service silently never existed. Both the
entity and the service are now set up in `climate.py`; see the note at the top
of `__init__.py` before moving anything back.
