"""Checks for `infrared_entity`, the path through Home Assistant's infrared platform.

The script starts a real Home Assistant core with the infrared component and a
test emitter entity. It needs Home Assistant 2026.5 or later, plus the
infrared-protocols version that this Home Assistant version pins:

    uv run --python 3.14 --with 'homeassistant==2026.10.4' \
        --with 'infrared-protocols==10.1.0' python tests/verify_infrared.py

On an older Home Assistant it prints SKIP and exits with code 0.
"""

from __future__ import annotations

import asyncio
from importlib.util import find_spec
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if find_spec("homeassistant.components.infrared") is None:
    print("SKIP: this Home Assistant has no infrared platform (it needs 2026.5 or later)")
    raise SystemExit(0)

from homeassistant.components import infrared  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import (  # noqa: E402
    device_registry as dr,
    entity_registry as er,
    restore_state as rs,
)
from infrared_protocols.commands import Command  # noqa: E402

from custom_components.mitsubishi_remote import climate as climate_mod  # noqa: E402
from custom_components.mitsubishi_remote.mitsubishi_protocol import (  # noqa: E402
    Mode,
    build_frame,
    modulate,
)

RESULTS: list[tuple[bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((bool(condition), name))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -- {detail}" if detail and not condition else ""))


FRAME = build_frame(power=True, mode=Mode.COOL, temperature=24)

# Home Assistant 2026.5 calls the base class InfraredEntity. Later versions
# call it InfraredEmitterEntity and keep the old name as a deprecated alias.
EmitterBase = getattr(infrared, "InfraredEmitterEntity", None) or infrared.InfraredEntity


class TestEmitter(EmitterBase):
    """An emitter that records each command instead of sending IR."""

    _attr_name = "Test emitter"

    def __init__(self) -> None:
        self.commands: list = []

    async def async_send_command(self, command) -> None:
        self.commands.append(command)


async def run() -> None:
    added: list = []
    for config in ({}, {"remote_entity": "remote.x", "infrared_entity": "infrared.y"}):
        await climate_mod.async_setup_platform(None, config, added.extend)
    check("setup adds no entity without a transmitter or with two", added == [], str(added))

    with tempfile.TemporaryDirectory() as config_dir:
        hass = HomeAssistant(config_dir)
        dr.async_setup(hass)
        await dr.async_load(hass)
        await er.async_load(hass)
        await rs.async_load(hass)
        await infrared.async_setup(hass, {})
        emitter = TestEmitter()
        await hass.data[infrared.DATA_COMPONENT].async_add_entities([emitter])

        ent = climate_mod.MitsubishiRemoteClimate(
            infrared_entity=emitter.entity_id, name="AC", retries=2, repeat_gap=0.0
        )
        ent.hass = hass
        check("unique ID comes from the infrared entity",
              ent.unique_id == "mitsubishi_remote_" + emitter.entity_id.replace(".", "_"),
              ent.unique_id)

        await ent._send(FRAME)
        check("the emitter gets one command for each retry", len(emitter.commands) == 2,
              str(len(emitter.commands)))
        if not emitter.commands:
            return
        command = emitter.commands[0]
        timings = command.get_raw_timings()
        check("the command is an infrared_protocols Command", isinstance(command, Command))
        check("carrier 38 kHz, no repeat",
              command.modulation == 38_000 and command.repeat_count == 0,
              f"{command.modulation} {command.repeat_count}")
        check("timings are the modulate() list, marks positive and spaces negative",
              [abs(t) for t in timings] == modulate(FRAME)
              and all((t > 0) == (i % 2 == 0) for i, t in enumerate(timings)))
        state = hass.states.get(emitter.entity_id)
        check("the emitter state shows the time of the last send",
              state is not None and state.state not in ("unknown", ""),
              str(state))

        await hass.async_stop(force=True)


def main() -> int:
    asyncio.run(run())

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
