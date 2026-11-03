# Tests

The tests are plain Python scripts and need no pytest. They import the component and run against a real `homeassistant` package, so they use the real `ClimateEntity`, `RestoreEntity` and `RestoredExtraData` classes.

Run one script:

```sh
uv run --python 3.13 --with 'homeassistant==2025.1.4' python tests/verify_protocol.py
```

Run all of them, as CI does:

```sh
for t in tests/verify_*.py; do uv run --python 3.13 --with 'homeassistant==2025.1.4' python "$t"; done
```

Home Assistant 2025.1.4 needs Python 3.12 or 3.13. On Python 3.14, uv cannot install its dependencies.

Each script prints PASS or FAIL for each check and exits with a non-zero code when a check fails.

| Script | What it checks |
| --- | --- |
| `verify_protocol.py` | The encoder against IR_PROTOCOL.md. It rebuilds the real captures A, B and C and the examples E1 and E2 byte for byte, checks every field value, rejects frames that break rules R3, R4 and R6, and checks the raw timing list. It also checks the left/right airflow of the climate entity (AREA and WIDE VANE) and the `install_position` option. |
| `verify_features.py` | The I-See, Clean and Plasma switches: their bits, how the climate platform creates them, when they transmit, restore without IR, and that I-See off cancels an AREA choice. |
| `verify_fan_swing.py` | Every fan and swing value has an icon and a label. Old values map to the new ones, each value gives the right frame, and the `force_send` service works. |
| `verify_restore.py` | Restore after a restart: defaults, a full restore, an `off` entity that keeps its mode, old state formats, bad stored values, a storage round trip, and the power-off frame. |

`verify_fan_swing.py` reads `tests/climate_icons.json`, a copy of `homeassistant/components/climate/icons.json` from Home Assistant 2025.1.4, so the icon checks need no network. Copy the file again when you change the Home Assistant version of the tests. The icon check follows the rule of the frontend: the integration's own `icons.json` first, then the map of Home Assistant, else a blank default dot.
