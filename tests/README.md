# Regression tests

Plain Python scripts (no pytest needed, no HA install in the component). They
import the component directly and run against a real `homeassistant` wheel, so
they exercise the actual `ClimateEntity` / `RestoreEntity` base classes and
HA's real `RestoredExtraData`.

Run all four:

```sh
uv run --with 'homeassistant==2025.1.4' python tests/verify_restore.py
uv run --with 'homeassistant==2025.1.4' python tests/verify_fan_swing.py
uv run --with 'homeassistant==2025.1.4' python tests/verify_vane.py
uv run --with 'homeassistant==2025.1.4' python tests/verify_features.py
```

Or all of them at once:

```sh
for t in tests/verify_*.py; do uv run --with 'homeassistant==2025.1.4' python "$t"; done
```

Each prints `PASS`/`FAIL` per check and exits non-zero on failure.

| Script | Covers |
| --- | --- |
| `verify_restore.py` | `RestoreEntity` behaviour: full restore, `off` retaining `active_mode`, legacy `last_state` fallback, sanitising garbage, storage round-trip, power-off frame, mode-switch ordering |
| `verify_fan_swing.py` | fan/swing values resolving to real MDI icons, legacy-label normalisation, protocol fan/vane bytes, setters canonicalising, restore migration, `force_send` registration + dispatch + reload safety |
| `verify_vane.py` | **byte-9 fix**: fan-auto/vane-auto must be `0x40` and fan-low/vane-bottom `0x69` (both learned captures), full-frame diff against the capture, swing = `0x78` with bit 7 clear, all 28 fan×vane combos unique, field-disjointness guard, wide-vane byte 8 independence, `install_position` bits + validation, checksums, icon keys for all three attributes, and the `swing_horizontal_mode` entity path |
| `verify_features.py` | **i-see / clean / plasma switches**: each bit position, one-byte-per-toggle independence, byte-15 collision guard, the climate entity owning `feature_states`, switch construction + unique ids + icons, transmit/no-op/no-transmit-while-off behaviour, restoration writing through without transmitting, the `async_load_platform` hand-off (and that switches land under `DATA_SWITCHES`, not `hass.data[DOMAIN]`, which is a list), and that `force_send` carries the feature bits |

The two learned captures in `verify_vane.py` are the ground truth for byte 9:
`23CB26010020580806406200008010000 0CD` (cool @ 24 °C, fan auto) and
`23CB2601000048060069530000801440` (power off @ heat 22 °C, fan low).

`verify_fan_swing.py` reads `tests/climate_icons.json` — a copy of
`homeassistant/components/climate/icons.json` (taken from core 2025.1.4) — so
the icon assertions do not depend on network access. Re-copy it when bumping
the HA baseline if HA changes its climate icon map.

Note the icon checks replicate the frontend's lookup rule exactly: exact match
on `state_attributes.<attr>.state[value]`, else `.default`. If a value ever
falls back to `.default` (`mdi:circle-medium`), the card shows a blank dot —
that is the bug these tests guard against.
