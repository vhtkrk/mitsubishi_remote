"""Switch entities for the Mitsubishi AC's independent on/off features.

The remote's i-see, clean and plasma settings are unrelated to each other and
to the climate entity's mode, so they are modelled as switches rather than as
`preset_mode` values (a single preset enum would make them mutually exclusive).

Each switch owns exactly one bit of the frame:

    i-see     byte 6,  bit 6   (0x40)  -- verified by the learned cool capture
    clean     byte 14, bit 2   (0x04)  -- fits both captures
    plasma    byte 15, bit 6   (0x40)  -- EXPERIMENTAL, see PlasmaMode

They are restored across restarts with their own `RestoreEntity` data, because
this integration is a blind one-way IR blaster: the switch must never be
reconstructed by guessing, and it must never transmit on startup.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DATA_SWITCHES
from .mitsubishi_protocol import CleanMode, ISeeMode, PlasmaMode

_LOGGER = logging.getLogger(__name__)

# key -> (byte, bit, human name, on-value, off-value, experimental)
#
# `off_value` is deliberately the *neutral* value, not a "feature is off" code:
# dropping the bit is what the unit's own captures show for these settings.
FEATURES: dict[str, dict[str, Any]] = {
    "isee": {
        "name": "I-See",
        "byte": 6,
        "icon": "mdi:motion-sensor",
        "on_value": ISeeMode.ON,
        "off_value": ISeeMode.OFF,
        "experimental": False,
    },
    "clean": {
        "name": "Clean",
        "byte": 14,
        "icon": "mdi:vacuum-outline",
        "on_value": CleanMode.ON,
        "off_value": CleanMode.OFF,
        "experimental": False,
    },
    "plasma": {
        "name": "Plasma",
        "byte": 15,
        "icon": "mdi:air-purifier",
        "on_value": PlasmaMode.ON,
        "off_value": PlasmaMode.OFF,
        "experimental": True,
    },
}


class MitsubishiFeatureSwitch(SwitchEntity, RestoreEntity):
    """One independent on/off bit of the Mitsubishi IR frame."""

    _attr_should_poll = False

    def __init__(self, climate, feature: str) -> None:
        """Attach a feature switch to the climate entity that owns the frame."""
        spec = FEATURES[feature]
        self._climate = climate
        self._feature = feature
        self._byte = spec["byte"]
        self._on_value = spec["on_value"]
        self._off_value = spec["off_value"]
        self._experimental = spec["experimental"]

        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_unique_id = f"{climate.unique_id}_{feature}"
        self._attr_is_on = bool(climate.feature_states.get(feature, False))

        if self._experimental:
            _LOGGER.warning(
                "Plasma switch created for %s: byte 15 bit 6 is unverified "
                "(the spec puts plasma on bit 2). It is exposed for "
                "experimentation and may do nothing, or toggle a different "
                "feature. See README 'Unverified bits'.",
                climate.entity_id or climate.name,
            )

    # -- state -------------------------------------------------------------

    def _apply_frame_bits(self, frame: bytearray) -> None:
        """Set (or clear) this feature's bit in an in-memory copy of a frame."""
        if self._attr_is_on:
            frame[self._byte] |= self._on_value
        else:
            frame[self._byte] &= ~self._on_value & 0xFF

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the feature on and transmit the resulting frame."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the feature off and transmit the resulting frame."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        if self._attr_is_on == value:
            self.async_write_ha_state()
            return
        self._attr_is_on = value
        self._climate.feature_states[self._feature] = value
        await self._climate.async_send_current_state()
        self.async_write_ha_state()

    # -- restoration -------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        """Restore the last known switch position without transmitting."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            # No history: inherit whatever the climate entity decided, so the
            # switch and the frames it will send agree from the first press.
            self._climate.feature_states.setdefault(
                self._feature, self._attr_is_on
            )
            return

        restored = last_state.state == "on"
        self._attr_is_on = restored
        self._climate.feature_states[self._feature] = restored
        _LOGGER.debug(
            "%s restored: %s (no IR sent)",
            self.entity_id,
            "on" if restored else "off",
        )


def feature_switches_for(climate) -> list[MitsubishiFeatureSwitch]:
    """Build one switch entity per configurable feature."""
    return [MitsubishiFeatureSwitch(climate, key) for key in FEATURES]


async def async_setup_platform(
    hass,
    config,
    async_add_entities,
    discovery_info=None,
) -> None:
    """Set up the feature switches passed over from the climate platform.

    There is no YAML entry for `switch:` -- the climate platform creates the
    entities (it owns the frame and the transport) and hands them over through
    `async_load_platform`.
    """
    if not discovery_info:
        _LOGGER.debug("switch platform loaded without discovery info; nothing to do")
        return

    climate = discovery_info.get("climate")
    if climate is None:
        _LOGGER.error("switch platform discovery info missing 'climate' entity")
        return

    entities = feature_switches_for(climate)
    store = hass.data.setdefault(DATA_SWITCHES, {})
    for entity in entities:
        store[entity.unique_id] = entity

    async_add_entities(entities, update_before_add=False)
