# mitsubishi_remote

A Home Assistant integration for the Mitsubishi Electric MSZ-FD25VA and MSZ-FD35VA air conditioners. It adds one `climate` entity and three switches, and sends IR commands through a transmitter that Home Assistant already controls:

- A LocalTuyaIR (`localtuya_rc`) `remote` entity, for example a Nedis WIFIRC10CBK blaster. The blaster keeps its firmware.
- An `infrared` entity (Home Assistant 2026.5 or later). In Home Assistant 2026.10, the Broadlink, ESPHome, MQTT, SMLIGHT and ZHA integrations provide these entities.

[IR_PROTOCOL.md](IR_PROTOCOL.md) describes the IR frame byte by byte, with the sources and an evidence level for each value. The encoder in `mitsubishi_protocol.py` follows that document.

## Install

The integration needs Home Assistant 2024.12 or later. The `infrared_entity` option needs Home Assistant 2026.5 or later.

### With HACS

The repository has the layout that HACS expects, so you can add it as a custom repository:

1. In HACS, open ⋮ (top right), then **Custom repositories**.
2. Enter `https://github.com/vhtkrk/mitsubishi_remote` and select the category **Integration**.
3. Install the integration, then restart Home Assistant.

From Home Assistant 2026.11, HACS is built in as the Marketplace (Settings → Marketplace), and the separate HACS integration cannot be installed. Add the same custom repository in the Marketplace.

### Manually

Copy `custom_components/mitsubishi_remote` into the `config/custom_components/` directory of Home Assistant, then restart Home Assistant.

## Configure

Add a `climate` platform entry to `configuration.yaml`. The integration creates the switches itself, so `switch:` needs no entry.

```yaml
climate:
  - platform: mitsubishi_remote
    name: Bedroom AC
    remote_entity: remote.localtuya_ir   # your LocalTuyaIR remote entity, or:
    # infrared_entity: infrared.ir_blaster   # your infrared entity
    retries: 3                            # send each command 3 times
    repeat_gap: 0.35                      # seconds between the sends
    install_position: center              # left | center | right
```

Set exactly one of `remote_entity` and `infrared_entity`.

| Key | Default | Meaning |
| --- | --- | --- |
| `remote_entity` | none | The entity ID of a LocalTuyaIR remote. |
| `infrared_entity` | none | The entity ID of an `infrared` entity. Needs Home Assistant 2026.5 or later. |
| `name` | `Mitsubishi AC` | The name of the climate entity. |
| `retries` | `2` | How many times to send each command. Tuya blasters sometimes drop one. |
| `repeat_gap` | `0.35` | Seconds between the sends. |
| `install_position` | `center` | Where the indoor unit hangs on the wall: `left`, `center` or `right`. Use the position of the slide switch in the original remote. `middle` also works. |

A LocalTuyaIR blaster gets the same pulses through both options. The unique ID of the climate entity comes from the transmitter entity ID. If you change the transmitter, Home Assistant creates a new climate entity. Remove the old entity in Settings → Devices & services → Entities.

## Entities

### Climate

| Attribute | Controls | Values |
| --- | --- | --- |
| `hvac_mode` | Power and mode | `off`, `auto`, `cool`, `heat`, `dry` |
| `temperature` | Set temperature | 16 to 31 °C in steps of 1 °C. The unit ignores it in `dry`. |
| `fan_mode` | Fan speed | `auto`, `low`, `medium`, `high`, `super_high` |
| `swing_mode` | Up/down airflow (VANE button) | `auto`, `pos1` (highest) to `pos5` (lowest), `swing` |
| `swing_horizontal_mode` | Left/right airflow (AREA and WIDE VANE buttons) | `area_auto`, `area_left`, `area_right`, `far_left`, `left`, `center`, `right`, `far_right`, `swing` |

The `area_*` values let the i-see sensor aim the airflow, like the AREA button of the remote. The other values are the positions of the WIDE VANE button. The unit accepts only one of the two at a time, so one list holds both. An `area_*` value needs the I-See switch on. When you turn I-See off, the left/right airflow returns to the last WIDE VANE value (`center` by default).

The integration has its own icon and label for each value (`icons.json` and `translations/en.json`).

When you turn the entity off, it sends the full state with the power bit cleared, as the original remote does.

### Switches

The integration adds three switches: I-See, Clean and Plasma. All three are on by default.

A switch change goes out at once when the unit is on. When the unit is off, the integration keeps the change and sends it with the next frame. The unit starts the clean cycle when it stops after COOL or DRY, so turn Clean on before you turn the unit off.

## Debug service

`mitsubishi_remote.force_send` sends one frame and does not change the entity state. Use it to test a setting before you rely on the UI. In Home Assistant it is under Developer tools → Actions.

```yaml
action: mitsubishi_remote.force_send
target:
  entity_id: climate.bedroom_ac      # optional; all entities if omitted
data:
  hvac_mode: cool
  temperature: 24
  fan_mode: auto                     # auto | low | medium | high | super_high
  power: true
```

The frame has VANE set to `auto`. All other settings come from the current state of the entity.

## After a restart

The climate entity restores its mode, set temperature, fan and airflow settings. It also stores the mode that power-on returns to, so an `off` entity still knows that it was in `heat`. The switches restore their own state.

A restore sends no IR. The link is one-way, and a frame at startup could undo a change made with the handheld remote while Home Assistant was down. Press any control to send the state again. The log shows a line like this after a restore:

```
climate.bedroom_ac restored: mode=heat temp=23 fan=high swing=auto swing_h=area_auto (no IR sent)
```

## Upgrade from 0.4

Version 0.5.0 changes the swing values. Restored state converts the old values: `swing_mode` `off` becomes `auto` and `on` becomes `swing`, and `swing_horizontal_mode` `off` becomes `area_auto` and `on` becomes `swing`. Home Assistant rejects unknown values in its climate actions, so change automations that send the old values.

The `command_format` and `hex_prefix` options are gone, because the integration always sends raw timings. Home Assistant ignores the two keys if they stay in `configuration.yaml`.

## Limitations

- The IR link is one-way. The entity shows the state that Home Assistant sent, and it does not see changes made with the handheld remote.
- `remote_entity` works only with LocalTuyaIR. The integration sends each frame as a `raw:` timing list through `remote.send_command`, and that string format belongs to LocalTuyaIR. Other `remote` integrations expect their own formats (for example, Broadlink expects base64 packets). For other transmitters, use `infrared_entity`.
- Nobody has tried `infrared_entity` with a real transmitter yet. The tests send frames through the `infrared` component of Home Assistant to a test emitter.
- The integration does not expose the timers or ECONO COOL. Section 6 of IR_PROTOCOL.md lists what is still unknown about the protocol.

## Development

| File | Role |
| --- | --- |
| `mitsubishi_protocol.py` | Builds the 18-byte frame and the raw timing list. |
| `climate.py` | The entry point of the YAML platform. It creates the climate entity, sends the frames, registers `force_send` and passes the switches to the switch platform. |
| `switch.py` | The I-See, Clean and Plasma switches. |

For a YAML platform, Home Assistant calls `async_setup_platform` in `climate.py` and never uses `__init__.py` for setup. Keep the setup code in `climate.py`.

[tests/README.md](tests/README.md) explains how to run the tests.

## License

MIT, see [LICENSE](LICENSE). The PDF and XLSX files in the repository root are third-party reference documents. The license does not cover them.
