"""Climate entity that drives a Mitsubishi MSZ-FD AC through a Home Assistant remote entity.

IR_PROTOCOL.md in the repository root specifies the frame. The rules R1-R13
that this module follows are in §4 of that document.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    CONF_INSTALL_POSITION,
    CONF_NAME,
    CONF_REMOTE_ENTITY,
    CONF_REPEAT_GAP,
    CONF_RETRIES,
    DEFAULT_INSTALL_POSITION,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_REPEAT_GAP,
    DEFAULT_RETRIES,
    DOMAIN,
    FEATURE_DEFAULTS,
    INSTALL_POSITIONS,
    SERVICE_FORCE_SEND,
)
from .mitsubishi_protocol import (
    Area,
    Fan,
    InstallPos,
    Mode,
    Vane,
    WideVane,
    build_frame,
    modulate,
)

_LOGGER = logging.getLogger(__name__)

HVAC_TO_MODE = {
    HVACMode.AUTO: Mode.AUTO,
    HVACMode.COOL: Mode.COOL,
    HVACMode.DRY: Mode.DRY,
    HVACMode.HEAT: Mode.HEAT,
}

# Option values. The frontend finds an icon and a label for each value through
# the entity's translation_key in icons.json and translations/en.json. Fan
# values reuse Home Assistant's own words where they exist.
FAN_TO_CODE = {
    "auto": Fan.AUTO,
    "low": Fan.LOW,
    "medium": Fan.MED,
    "high": Fan.HIGH,
    "super_high": Fan.SUPER_HIGH,
}
FAN_MODES = list(FAN_TO_CODE)

# swing_mode is VANE: the up/down airflow.
SWING_TO_VANE = {
    "auto": Vane.AUTO,
    "pos1": Vane.POS1,
    "pos2": Vane.POS2,
    "pos3": Vane.POS3,
    "pos4": Vane.POS4,
    "pos5": Vane.POS5,
    "swing": Vane.SWING,
}
SWING_MODES = list(SWING_TO_VANE)

# swing_horizontal_mode is the left/right airflow. The remote controls it with
# two buttons, AREA and WIDE VANE, but only one of them is active at a time
# (rule R3). One option list therefore holds both.
SWING_HORIZONTAL_TO_CODE: dict[str, tuple[Area, WideVane]] = {
    "area_auto": (Area.AUTO, WideVane.NONE),
    "area_left": (Area.LEFT, WideVane.NONE),
    "area_right": (Area.RIGHT, WideVane.NONE),
    "far_left": (Area.OFF, WideVane.FAR_LEFT),
    "left": (Area.OFF, WideVane.LEFT),
    "center": (Area.OFF, WideVane.CENTER),
    "right": (Area.OFF, WideVane.RIGHT),
    "far_right": (Area.OFF, WideVane.FAR_RIGHT),
    "swing": (Area.OFF, WideVane.SWING),
}
SWING_HORIZONTAL_MODES = list(SWING_HORIZONTAL_TO_CODE)
AREA_CHOICES = ("area_auto", "area_left", "area_right")
DEFAULT_WIDE_VANE = "center"

INSTALL_TO_CODE = {
    "left": InstallPos.LEFT,
    "center": InstallPos.CENTER,
    "right": InstallPos.RIGHT,
}

# Values from earlier versions. Home Assistant rejects unknown values in its
# climate services, so these matter for restored state and force_send only.
_FAN_ALIASES = {"med": "medium", "mid": "medium"}
_SWING_ALIASES = {"off": "auto", "on": "swing", "oscillate": "swing", "vertical": "swing"}
_SWING_HORIZONTAL_ALIASES = {
    # "off" sent AREA=AUTO with WIDE_VANE=NONE, the same frame as "area_auto".
    "off": "area_auto",
    "auto": "area_auto",
    "on": "swing",
    "oscillate": "swing",
    "horizontal": "swing",
}
_INSTALL_ALIASES = {"middle": "center"}


def _normalise(value: Any, valid: dict, aliases: dict[str, str]) -> str | None:
    """Return the canonical option for a value, or None if it is unknown."""
    if value is None:
        return None
    text = str(value).strip().casefold()
    text = aliases.get(text, text)
    return text if text in valid else None


def normalise_fan_mode(value: Any) -> str | None:
    """Map a fan label (current or legacy) to its canonical value."""
    return _normalise(value, FAN_TO_CODE, _FAN_ALIASES)


def normalise_swing_mode(value: Any) -> str | None:
    """Map a swing label (current or legacy) to its canonical value."""
    return _normalise(value, SWING_TO_VANE, _SWING_ALIASES)


def normalise_swing_horizontal_mode(value: Any) -> str | None:
    """Map a horizontal-swing label (current or legacy) to its canonical value."""
    return _normalise(value, SWING_HORIZONTAL_TO_CODE, _SWING_HORIZONTAL_ALIASES)


def normalise_install_position(value: Any) -> str:
    """Return left, center or right. An empty value means the default (center)."""
    if value is None or str(value).strip() == "":
        return DEFAULT_INSTALL_POSITION
    position = _normalise(value, INSTALL_TO_CODE, _INSTALL_ALIASES)
    if position is None:
        raise ValueError(
            f"install_position must be one of {INSTALL_POSITIONS}, got {value!r}"
        )
    return position


def _mode_value(mode: Any) -> str | None:
    """Return the plain string value of an HVACMode (or None)."""
    if mode is None:
        return None
    return mode.value if isinstance(mode, HVACMode) else str(mode)


class MitsubishiExtraStoredData(ExtraStoredData):
    """State that the climate attributes alone cannot carry across restarts.

    Home Assistant only stores `hvac_mode`, so an `off` entity would forget the
    mode that it returns to (heat/cool/dry/auto). It would also forget the
    WIDE_VANE position that an AREA choice hides.
    """

    def __init__(
        self,
        *,
        active_mode: str | None,
        hvac_mode: str | None,
        target_temperature: int | None,
        fan_mode: str | None,
        swing_mode: str | None,
        swing_horizontal_mode: str | None = None,
        last_wide_vane: str | None = None,
    ) -> None:
        self.active_mode = active_mode
        self.hvac_mode = hvac_mode
        self.target_temperature = target_temperature
        self.fan_mode = fan_mode
        self.swing_mode = swing_mode
        self.swing_horizontal_mode = swing_horizontal_mode
        self.last_wide_vane = last_wide_vane

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the state."""
        return {
            "active_mode": self.active_mode,
            "hvac_mode": self.hvac_mode,
            "target_temperature": self.target_temperature,
            "fan_mode": self.fan_mode,
            "swing_mode": self.swing_mode,
            "swing_horizontal_mode": self.swing_horizontal_mode,
            "last_wide_vane": self.last_wide_vane,
        }


class MitsubishiRemoteClimate(ClimateEntity, RestoreEntity):
    """A climate entity that encodes Mitsubishi frames and calls remote.send_command."""

    _attr_hvac_modes = [
        HVACMode.OFF,
        HVACMode.AUTO,
        HVACMode.COOL,
        HVACMode.HEAT,
        HVACMode.DRY,
    ]
    _attr_fan_modes = FAN_MODES
    _attr_swing_modes = SWING_MODES
    _attr_swing_horizontal_modes = SWING_HORIZONTAL_MODES
    _attr_min_temp = DEFAULT_MIN_TEMP
    _attr_max_temp = DEFAULT_MAX_TEMP
    _attr_target_temperature_step = 1
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_translation_key = "mitsubishi_ac"
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.SWING_HORIZONTAL_MODE
    )

    def __init__(
        self,
        *,
        remote_entity: str,
        name: str,
        retries: int,
        repeat_gap: float,
        install_position: str | None = DEFAULT_INSTALL_POSITION,
    ) -> None:
        self._remote_entity = remote_entity
        self._attr_name = name
        self._attr_unique_id = f"mitsubishi_remote_{remote_entity.replace('.', '_')}"
        self._retries = max(1, int(retries))
        self._repeat_gap = max(0.0, float(repeat_gap))
        self._install_position = normalise_install_position(install_position)

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24
        self._attr_fan_mode = "auto"
        self._attr_swing_mode = "auto"
        self._attr_swing_horizontal_mode = "area_auto"
        # The WIDE_VANE position to use when no AREA choice is active (rule R5).
        self._last_wide_vane = DEFAULT_WIDE_VANE
        self._power = False
        # The mode that power-on returns to. It is stored across restarts.
        self._active_mode: HVACMode = HVACMode.COOL

        # i-see / clean / plasma. This entity owns them because it owns the
        # frame and the transport. The switches in switch.py call
        # `async_set_feature`.
        self.feature_states: dict[str, bool] = dict(FEATURE_DEFAULTS)

    # -- helpers ----------------------------------------------------------

    @property
    def swing_horizontal_mode(self) -> str:
        """Return the left/right airflow choice.

        Rule R4: AREA needs i-see. Without i-see, the stored WIDE_VANE
        position applies instead of an AREA choice.
        """
        choice = self._attr_swing_horizontal_mode
        if choice in AREA_CHOICES and not self._feature("isee"):
            return self._last_wide_vane
        return choice

    def _feature(self, key: str) -> bool:
        """Return a feature's current state, falling back to its default."""
        return bool(self.feature_states.get(key, FEATURE_DEFAULTS[key]))

    def _current_code(self, **overrides: Any) -> bytes:
        """Encode the current state. `overrides` replace build_frame fields."""
        area, wide_vane = SWING_HORIZONTAL_TO_CODE[self.swing_horizontal_mode]
        fields: dict[str, Any] = {
            "power": self._power,
            "mode": HVAC_TO_MODE.get(self._active_mode, Mode.COOL),
            "temperature": self.target_temperature or 24,
            "fan": FAN_TO_CODE.get(normalise_fan_mode(self.fan_mode), Fan.AUTO),
            "vane": SWING_TO_VANE.get(normalise_swing_mode(self.swing_mode), Vane.AUTO),
            "wide_vane": wide_vane,
            "area": area,
            "isee": self._feature("isee"),
            "install_pos": INSTALL_TO_CODE[self._install_position],
            "clean": self._feature("clean"),
            "plasma": self._feature("plasma"),
        }
        fields.update(overrides)
        return build_frame(**fields)

    async def async_set_feature(self, key: str, value: bool) -> None:
        """Set i-see, clean or plasma, then transmit if the unit is on.

        Rules R4 and R5: when i-see turns off, an AREA choice changes to the
        stored WIDE_VANE position.
        """
        self.feature_states[key] = value
        if (
            key == "isee"
            and not value
            and self._attr_swing_horizontal_mode in AREA_CHOICES
        ):
            self._attr_swing_horizontal_mode = self._last_wide_vane
        await self.async_send_current_state()

    async def async_send_current_state(self) -> None:
        """Transmit the current state if the unit is on, then update the UI.

        The frame carries the power bit, so a transmission while the unit is
        off would turn it on.
        """
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_send_command(
        self,
        *,
        hvac_mode: str,
        temperature: int,
        fan_mode: str,
        power: bool = True,
    ) -> None:
        """Encode and send a frame for the debug service.

        VANE is AUTO. The other fields keep the entity's current state.
        """
        power = power and hvac_mode != HVACMode.OFF
        mode = HVAC_TO_MODE.get(hvac_mode, HVAC_TO_MODE.get(self._active_mode, Mode.COOL))
        frame = self._current_code(
            power=power,
            mode=mode,
            temperature=temperature,
            fan=FAN_TO_CODE.get(normalise_fan_mode(fan_mode), Fan.AUTO),
            vane=Vane.AUTO,
        )
        await self._send(frame)

    async def _send(self, frame: bytes) -> None:
        # LocalTuyaIR's `remote.send_command` has no built-in Mitsubishi
        # protocol, so the frame goes out as a raw timing list.
        payload = "raw:" + ",".join(str(p) for p in modulate(frame))

        # Tuya IR blasters sometimes drop a transmission, so send it again
        # after a short gap.
        for attempt in range(self._retries):
            try:
                await self.hass.services.async_call(
                    "remote",
                    "send_command",
                    {
                        "entity_id": self._remote_entity,
                        "command": payload,
                    },
                    blocking=True,
                )
            except Exception:  # noqa: BLE001 - log and retry
                _LOGGER.exception(
                    "Failed to send IR command (attempt %d/%d)",
                    attempt + 1,
                    self._retries,
                )
            if attempt < self._retries - 1:
                await asyncio.sleep(self._repeat_gap)

    # -- climate callbacks --------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: str) -> None:
        if hvac_mode == HVACMode.OFF:
            self._power = False
            self._attr_hvac_mode = HVACMode.OFF
            # Rule R1: the power-off frame is the full state with POWER = 0.
            # It also carries CLEAN, which the unit reads when it stops (R8).
            await self._send(self._current_code())
        else:
            self._power = True
            # Set the mode before encoding: _current_code() reads it.
            self._active_mode = HVACMode(hvac_mode)
            self._attr_hvac_mode = HVACMode(hvac_mode)
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        if ATTR_TEMPERATURE in kwargs:
            self._attr_target_temperature = int(round(kwargs[ATTR_TEMPERATURE]))
            if self._power:
                await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        self._attr_fan_mode = normalise_fan_mode(fan_mode) or "auto"
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set VANE (up/down airflow)."""
        self._attr_swing_mode = normalise_swing_mode(swing_mode) or "auto"
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set AREA or WIDE_VANE (left/right airflow)."""
        choice = (
            normalise_swing_horizontal_mode(swing_horizontal_mode)
            or self.swing_horizontal_mode
        )
        if choice in AREA_CHOICES and not self._feature("isee"):
            raise ServiceValidationError(
                f"{choice} needs i-see. Turn on the I-See switch first."
            )
        if choice not in AREA_CHOICES:
            self._last_wide_vane = choice
        self._attr_swing_horizontal_mode = choice
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    # -- state restoration -------------------------------------------------

    @property
    def extra_restore_state_data(self) -> MitsubishiExtraStoredData:
        """Return the state that the climate attributes cannot express."""
        return MitsubishiExtraStoredData(
            active_mode=_mode_value(self._active_mode),
            hvac_mode=_mode_value(self._attr_hvac_mode),
            target_temperature=self._attr_target_temperature,
            fan_mode=self._attr_fan_mode,
            swing_mode=self._attr_swing_mode,
            swing_horizontal_mode=self._attr_swing_horizontal_mode,
            last_wide_vane=self._last_wide_vane,
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last known state after a restart. Send no IR."""
        await super().async_added_to_hass()

        extra = await self.async_get_last_extra_data()
        last_state = await self.async_get_last_state()

        if extra is None and last_state is None:
            _LOGGER.debug("%s: no previous state, keeping defaults", self.entity_id)
            return

        stored = extra.as_dict() if extra is not None else {}
        attrs = last_state.attributes if last_state is not None else {}
        prev_state = last_state.state if last_state is not None else None

        if (active := stored.get("active_mode")) in HVAC_TO_MODE:
            self._active_mode = HVACMode(active)

        mode = stored.get("hvac_mode", prev_state)
        if mode in self._attr_hvac_modes:
            self._attr_hvac_mode = HVACMode(mode)
            self._power = self._attr_hvac_mode != HVACMode.OFF

        temp = stored.get("target_temperature", attrs.get(ATTR_TEMPERATURE))
        if temp is not None:
            try:
                temp = int(round(float(temp)))
            except (TypeError, ValueError):
                pass
            else:
                self._attr_target_temperature = max(
                    DEFAULT_MIN_TEMP, min(DEFAULT_MAX_TEMP, temp)
                )

        # Normalise instead of comparing with the option lists: older versions
        # stored values such as "High", "on" and "off".
        if fan := normalise_fan_mode(stored.get("fan_mode", attrs.get("fan_mode"))):
            self._attr_fan_mode = fan

        if swing := normalise_swing_mode(
            stored.get("swing_mode", attrs.get("swing_mode"))
        ):
            self._attr_swing_mode = swing

        if swing_h := normalise_swing_horizontal_mode(
            stored.get("swing_horizontal_mode", attrs.get("swing_horizontal_mode"))
        ):
            self._attr_swing_horizontal_mode = swing_h

        last_wide = normalise_swing_horizontal_mode(stored.get("last_wide_vane"))
        if last_wide and last_wide not in AREA_CHOICES:
            self._last_wide_vane = last_wide
        elif swing_h and swing_h not in AREA_CHOICES:
            self._last_wide_vane = swing_h

        # No IR here. The link is one-way, so a transmission at startup would
        # undo any change made with the handheld remote while HA was down.
        _LOGGER.info(
            "%s restored: mode=%s temp=%s fan=%s swing=%s swing_h=%s (no IR sent)",
            self.entity_id,
            self._attr_hvac_mode,
            self._attr_target_temperature,
            self._attr_fan_mode,
            self._attr_swing_mode,
            self._attr_swing_horizontal_mode,
        )


async def _async_register_force_send(hass) -> None:
    """Register `mitsubishi_remote.force_send` once.

    Home Assistant calls `async_setup_platform` in this file for a YAML
    platform, so the service is registered here. The `has_service` guard
    keeps a YAML reload from registering it twice.
    """
    if hass.services.has_service(DOMAIN, SERVICE_FORCE_SEND):
        return

    async def async_force_send(call) -> None:
        data = dict(call.data)
        entity_ids = data.get(ATTR_ENTITY_ID)
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # A YAML reload appends a new entity object without removing the old
        # one. Keep only the newest object per entity_id, so that each call
        # sends one command.
        newest: dict[str, Any] = {}
        for entity in hass.data.get(DOMAIN, []):
            newest[entity.entity_id] = entity

        targets = [
            entity
            for entity_id, entity in newest.items()
            if entity_id and (not entity_ids or entity_id in entity_ids)
        ]
        if not targets:
            _LOGGER.warning(
                "%s: no matching mitsubishi_remote climate entity for %s",
                SERVICE_FORCE_SEND,
                entity_ids or "(any)",
            )
            return

        for entity in targets:
            await entity.async_send_command(
                hvac_mode=data.get("hvac_mode", "cool"),
                temperature=int(data.get("temperature", 24)),
                fan_mode=data.get("fan_mode", "auto"),
                power=bool(data.get("power", True)),
            )

    hass.services.async_register(DOMAIN, SERVICE_FORCE_SEND, async_force_send)
    _LOGGER.debug("Registered service %s.%s", DOMAIN, SERVICE_FORCE_SEND)


async def async_setup_platform(
    hass,
    config,
    async_add_entities,
    discovery_info=None,
) -> None:
    """Set up the Mitsubishi climate platform from a YAML `climate:` block."""
    from homeassistant.helpers.discovery import async_load_platform

    entity = MitsubishiRemoteClimate(
        remote_entity=config[CONF_REMOTE_ENTITY],
        name=config.get(CONF_NAME, DEFAULT_NAME),
        retries=config.get(CONF_RETRIES, DEFAULT_RETRIES),
        repeat_gap=config.get(CONF_REPEAT_GAP, DEFAULT_REPEAT_GAP),
        install_position=config.get(CONF_INSTALL_POSITION, DEFAULT_INSTALL_POSITION),
    )
    # The feature switches belong to this entity, so this platform creates
    # them. `switch:` has no YAML entry of its own.
    hass.async_create_task(
        async_load_platform(hass, "switch", DOMAIN, {"climate": entity}, config)
    )

    # Keep a reference for the domain service. Do not de-duplicate here: the
    # entity_id is still `unknown.unknown` at this point. The service removes
    # stale objects by entity_id when it runs.
    hass.data.setdefault(DOMAIN, []).append(entity)
    async_add_entities([entity], update_before_add=False)

    await _async_register_force_send(hass)
