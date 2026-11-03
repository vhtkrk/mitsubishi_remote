"""Switch entities for the Mitsubishi AC's independent on/off features.

i-see, clean and plasma are independent of each other and of the climate
mode, so they are switches and not `preset_mode` values (a preset list would
make them exclude each other). Their bits (IR_PROTOCOL.md):

    i-see     byte 6,  bit 6  (0x40)  §3.3
    clean     byte 14, bit 2  (0x04)  §3.10
    plasma    byte 15, bit 6  (0x40)  §3.11

The climate entity owns the frame. A switch only changes a feature and asks
the climate entity to transmit. Each switch restores its own state after a
restart and never transmits on startup, because the IR link is one-way.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DATA_SWITCHES

_LOGGER = logging.getLogger(__name__)

FEATURES: dict[str, dict[str, str]] = {
    "isee": {"name": "I-See", "icon": "mdi:motion-sensor"},
    "clean": {"name": "Clean", "icon": "mdi:vacuum-outline"},
    "plasma": {"name": "Plasma", "icon": "mdi:air-purifier"},
}


class MitsubishiFeatureSwitch(SwitchEntity, RestoreEntity):
    """One independent on/off feature of the Mitsubishi IR frame."""

    _attr_should_poll = False

    def __init__(self, climate, feature: str) -> None:
        """Attach a feature switch to the climate entity that owns the frame."""
        spec = FEATURES[feature]
        self._climate = climate
        self._feature = feature
        self._attr_name = spec["name"]
        self._attr_icon = spec["icon"]
        self._attr_unique_id = f"{climate.unique_id}_{feature}"
        self._attr_is_on = bool(climate.feature_states.get(feature, False))

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
        await self._climate.async_set_feature(self._feature, value)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known switch position without transmitting."""
        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()
        if last_state is None:
            # No history: keep the climate entity's value, so the switch and
            # the frames agree from the first press.
            self._climate.feature_states.setdefault(self._feature, self._attr_is_on)
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
    """Build one switch entity per feature."""
    return [MitsubishiFeatureSwitch(climate, key) for key in FEATURES]


async def async_setup_platform(
    hass,
    config,
    async_add_entities,
    discovery_info=None,
) -> None:
    """Set up the feature switches that the climate platform hands over.

    `switch:` has no YAML entry. The climate platform creates the entities
    (it owns the frame and the transport) and passes them through
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
