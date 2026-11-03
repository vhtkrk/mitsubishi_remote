"""Mitsubishi MSZ-FD AC control through an existing Home Assistant remote or infrared entity.

This is a YAML `climate` platform:

    climate:
      - platform: mitsubishi_remote
        name: Bedroom AC
        remote_entity: remote.localtuya_ir
        retries: 3

The integration encodes Mitsubishi IR frames. It sends them through the
`remote.send_command` service of a LocalTuyaIR remote entity
(`remote_entity`), or through an `infrared` entity (`infrared_entity`, Home
Assistant 2026.5 or later). It adds a `climate` entity (mode, set
temperature, fan, airflow) and three switches. IR_PROTOCOL.md in the
repository root describes the frame.

It also registers a debug service:

    mitsubishi_remote.force_send
        hvac_mode: cool | heat | dry | auto | off
        temperature: 16..31
        fan_mode: auto | low | medium | high | super_high
        power: true | false

Note for maintainers: this file has no `async_setup_platform` and no
`async_setup`. For a YAML platform, Home Assistant imports `climate.py` and
calls the `async_setup_platform` in that module. A YAML platform creates no
config entry, so Home Assistant never uses this file for setup. A service
registration here would never run, so keep the entity setup and the service
registration in `climate.py`.
"""

from __future__ import annotations

__all__ = ["DOMAIN"]

from .const import DOMAIN
