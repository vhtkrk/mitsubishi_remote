"""Mitsubishi MSZ-FD25 AC control via an existing Home Assistant remote entity.

This is a YAML-configured `climate` platform (legacy platform style):

    climate:
      - platform: mitsubishi_remote
        name: Bedroom AC
        remote_entity: remote.localtuya_ir
        command_format: hex
        retries: 3

The integration encodes Mitsubishi IR frames and sends them through the
`remote.send_command` service of your LocalTuyaIR remote entity, exposing a
full `climate` entity (mode / setpoint / fan / swing).

A debug service is also registered:

    mitsubishi_remote.force_send
        hvac_mode: cool | heat | dry | auto | off
        temperature: 16..31
        fan_mode: auto | low | medium | high
        power: true | false

NOTE FOR MAINTAINERS
--------------------
There is deliberately no `async_setup_platform` here. For a legacy YAML
platform, Home Assistant imports only `climate.py` and calls the
`async_setup_platform` defined in that module; this package's `__init__.py` is
never used as a setup entry point (there is no `async_setup` either, because a
YAML platform does not create a config entry to set up).

An earlier version registered `force_send` from this file, which meant the
service never actually appeared in Home Assistant. Both the entity setup and
the service registration now live in `climate.py`. Keep it that way -- adding a
second registration here would silently do nothing (or, worse, look like it
works while `climate.py` is the code that really runs).
"""

from __future__ import annotations

__all__ = ["DOMAIN"]

from .const import DOMAIN
