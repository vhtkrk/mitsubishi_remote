"""Climate entity that drives a Mitsubishi AC through a Home Assistant remote entity."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import (
    CONF_COMMAND_FORMAT,
    CONF_HEX_PREFIX,
    CONF_INSTALL_POSITION,
    CONF_REMOTE_ENTITY,
    CONF_REPEAT_GAP,
    CONF_RETRIES,
    DEFAULT_COMMAND_FORMAT,
    DEFAULT_HEX_PREFIX,
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
    CleanMode,
    ClimateMode,
    FanMode,
    InstallPosition,
    ISeeMode,
    PlasmaMode,
    PowerMode,
    PowerfulMode,
    VanneHorizontalMode,
    VanneVerticalMode,
    build_frame,
    modulate,
)

_LOGGER = logging.getLogger(__name__)

# HA HVACMode -> protocol mode code
HVAC_TO_MODE = {
    HVACMode.AUTO: ClimateMode.AUTO,
    HVACMode.COOL: ClimateMode.COLD,
    HVACMode.DRY: ClimateMode.DRY,
    HVACMode.HEAT: ClimateMode.HOT,
}

# Fan / swing values are deliberately HA's own lowercase vocabulary.
#
# The frontend looks these up in homeassistant/components/climate/icons.json by
# exact string match (`getIconFromTranslations`), so a value that is not in that
# map renders as the `default` fallback -- an unlabelled `mdi:circle-medium`
# dot. The old labels ("Auto"/"Low"/"Med"/"High") matched nothing, which is
# why every fan speed lost its icon. Note there is no "med" key either: HA's
# map spells it "medium".
FAN_MODES = ["auto", "low", "medium", "high"]
FAN_TO_CODE = {
    "auto": FanMode.AUTO,
    "low": FanMode.SPEED1,
    "medium": FanMode.SPEED2,
    "high": FanMode.SPEED3,
}
CODE_TO_FAN = {code: label for label, code in FAN_TO_CODE.items()}

# Vertical vane: "off" parks it in Auto, "on" oscillates it (byte 9, bits 3-6).
# "on"/"off" are the keys HA's icon map defines (mdi:arrow-oscillating /
# mdi:arrow-oscillating-off); "swing" was not a key, hence the missing icon.
SWING_MODES = ["off", "on"]
SWING_TO_VANE = {
    "off": VanneVerticalMode.AUTO,
    "on": VanneVerticalMode.SWING,
}

# Horizontal ("wide") vane -- byte 8, bits 4-7. This is a *second*, independent
# swing axis, which is exactly what HA's swing_horizontal_mode is for. HA's
# icon map defines off/on for it, so we use the same two words.
SWING_HORIZONTAL_MODES = ["off", "on"]
SWING_HORIZONTAL_TO_VANE = {
    "off": VanneHorizontalMode.NOT_SET,
    "on": VanneHorizontalMode.SWING,
}

# Pre-0.2 values, still accepted so existing automations/scripts keep working.
_FAN_ALIASES = {
    "auto": "auto",
    "low": "low",
    "med": "medium",
    "medium": "medium",
    "mid": "medium",
    "high": "high",
}
_SWING_ALIASES = {
    "off": "off",
    "auto": "off",
    "on": "on",
    "swing": "on",
    "oscillate": "on",
    "vertical": "on",
}
_SWING_HORIZONTAL_ALIASES = {
    "off": "off",
    "auto": "off",
    "on": "on",
    "swing": "on",
    "oscillate": "on",
    "horizontal": "on",
}

# "left"/"middle"/"right" -> byte 15 bits 3-4.
_INSTALL_TO_CODE = {
    "left": InstallPosition.LEFT,
    "middle": InstallPosition.MIDDLE,
    "right": InstallPosition.RIGHT,
}


def normalise_fan_mode(value: Any) -> str | None:
    """Map any accepted fan label to its canonical value (or None)."""
    if value is None:
        return None
    return _FAN_ALIASES.get(str(value).strip().casefold())


def normalise_swing_mode(value: Any) -> str | None:
    """Map any accepted swing label to its canonical value (or None)."""
    if value is None:
        return None
    return _SWING_ALIASES.get(str(value).strip().casefold())


def normalise_swing_horizontal_mode(value: Any) -> str | None:
    """Map any accepted horizontal-swing label to its canonical value."""
    if value is None:
        return None
    return _SWING_HORIZONTAL_ALIASES.get(str(value).strip().casefold())


def normalise_install_position(value: Any) -> str | None:
    """Validate a configured install position (returns None if unset)."""
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in ("", "none", "unset", "default"):
        return None
    if text not in _INSTALL_TO_CODE:
        raise ValueError(
            f"install_position must be one of {INSTALL_POSITIONS} or unset, "
            f"got {value!r}"
        )
    return text


def _mode_value(mode: Any) -> str | None:
    """Return the plain string value of an HVACMode (or None)."""
    if mode is None:
        return None
    return mode.value if isinstance(mode, HVACMode) else str(mode)


class MitsubishiExtraStoredData(ExtraStoredData):
    """Extra state that climate attributes alone cannot carry across restarts.

    HA only persists `hvac_mode`, so `off` is all that survives a restart of the
    *mode*; the mode the unit is actually in (heat/cool/dry/auto) would be lost
    and power-on would have to guess. Keep it (plus the other settings) here so
    the entity comes back exactly as the user left it.
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
    ) -> None:
        self.active_mode = active_mode
        self.hvac_mode = hvac_mode
        self.target_temperature = target_temperature
        self.fan_mode = fan_mode
        self.swing_mode = swing_mode
        self.swing_horizontal_mode = swing_horizontal_mode

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the state."""
        return {
            "active_mode": self.active_mode,
            "hvac_mode": self.hvac_mode,
            "target_temperature": self.target_temperature,
            "fan_mode": self.fan_mode,
            "swing_mode": self.swing_mode,
            "swing_horizontal_mode": self.swing_horizontal_mode,
        }


class MitsubishiRemoteClimate(ClimateEntity, RestoreEntity):
    """A climate entity that encodes Mitsubishi frames and fires remote.send_command."""

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
    _attr_temperature_unit = None  # set in __init__

    def __init__(
        self,
        *,
        remote_entity: str,
        name: str,
        command_format: str,
        hex_prefix: bool,
        retries: int,
        repeat_gap: float,
        install_position: str | None = DEFAULT_INSTALL_POSITION,
    ) -> None:
        from homeassistant.const import UnitOfTemperature

        self._remote_entity = remote_entity
        self._attr_name = name
        self._attr_unique_id = f"mitsubishi_remote_{remote_entity.replace('.', '_')}"
        self._command_format = command_format
        self._hex_prefix = hex_prefix
        self._retries = max(1, int(retries))
        self._repeat_gap = max(0.0, float(repeat_gap))

        # One-time installer setting (byte 15 bits 3-4). None = leave byte 15
        # alone, which keeps the frame byte-identical to previous versions.
        self._install_position = normalise_install_position(install_position)

        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.SWING_HORIZONTAL_MODE
        )

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24
        self._attr_fan_mode = "auto"
        self._attr_swing_mode = "off"
        self._attr_swing_horizontal_mode = "off"
        self._power = False
        # Mode used to build the frame while the unit is off/powered back on.
        # Preserved across restarts so power-on returns to the real mode.
        self._active_mode: HVACMode = HVACMode.COOL

        # Independent on/off features (i-see / clean / plasma). The climate
        # entity owns them because it owns the frame and the transport; the
        # switch entities in switch.py just set a bit and ask us to transmit.
        # Defaults match the frame this integration has always sent.
        self.feature_states: dict[str, bool] = dict(FEATURE_DEFAULTS)

    # -- helpers ----------------------------------------------------------

    def _current_code(self) -> bytes:
        mode_code = HVAC_TO_MODE.get(self._active_mode, ClimateMode.COLD)
        fan_code = FAN_TO_CODE.get(normalise_fan_mode(self.fan_mode), FanMode.AUTO)
        vane = SWING_TO_VANE.get(
            normalise_swing_mode(self.swing_mode), VanneVerticalMode.AUTO
        )
        vane_h = SWING_HORIZONTAL_TO_VANE.get(
            normalise_swing_horizontal_mode(self.swing_horizontal_mode),
            VanneHorizontalMode.NOT_SET,
        )
        return build_frame(
            climate_mode=mode_code,
            temperature=self.target_temperature or 24,
            fan_mode=fan_code,
            vanne_vertical_mode=vane,
            vanne_horizontal_mode=vane_h,
            install_position=(
                _INSTALL_TO_CODE[self._install_position]
                if self._install_position
                else None
            ),
            powerful=PowerfulMode.OFF,
            isee_mode=self._isee_code(),
            clean_mode=self._clean_code(),
            plasma_mode=self._plasma_code(),
            power_mode=PowerMode.ON if self._power else PowerMode.OFF,
        )

    def _feature(self, key: str) -> bool:
        """Return a feature's current state, falling back to its default."""
        return bool(self.feature_states.get(key, FEATURE_DEFAULTS[key]))

    def _isee_code(self) -> int:
        return ISeeMode.ON if self._feature("isee") else ISeeMode.OFF

    def _clean_code(self) -> int:
        return CleanMode.ON if self._feature("clean") else CleanMode.OFF

    def _plasma_code(self) -> int:
        return PlasmaMode.ON if self._feature("plasma") else PlasmaMode.OFF

    async def async_send_current_state(self) -> None:
        """Re-transmit the current state (used by the feature switches).

        Like every other setter here this only transmits when the unit is on:
        the frame carries a power bit, so sending while "off" would both wake
        the unit and change its mode.
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
        """Encode and send an arbitrary command (used by the debug service)."""
        power = power and hvac_mode != HVACMode.OFF
        mode_code = HVAC_TO_MODE.get(hvac_mode, ClimateMode.COLD)
        fan_code = FAN_TO_CODE.get(normalise_fan_mode(fan_mode), FanMode.AUTO)
        frame = build_frame(
            climate_mode=mode_code,
            temperature=temperature,
            fan_mode=fan_code,
            vanne_vertical_mode=VanneVerticalMode.AUTO,
            vanne_horizontal_mode=VanneHorizontalMode.NOT_SET,
            install_position=(
                _INSTALL_TO_CODE[self._install_position]
                if self._install_position
                else None
            ),
            powerful=PowerfulMode.OFF,
            isee_mode=self._isee_code(),
            clean_mode=self._clean_code(),
            plasma_mode=self._plasma_code(),
            power_mode=PowerMode.ON if power else PowerMode.OFF,
        )
        await self._send(frame)

    async def _send(self, frame: bytes) -> None:
        # LocalTuyaIR's `remote.send_command` expects the code in one of its
        # documented formats (`raw:` timing list, protocol params, or `tuya:`
        # Base64). Mitsubishi is not one of the supported built-in protocols,
        # so send the pulse timings in the raw format.
        pulses = modulate(frame)
        payload = "raw:" + ",".join(str(p) for p in pulses)

        # LocalTuyaIR / Tuya IR blasters are known to drop packets, so we
        # resend a few times with a small gap.
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
            except Exception:  # noqa: BLE001 - surface and retry
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
            # The FD remote's power-off frame is just the current state with the
            # power bit (byte 5) cleared -- learned capture: 23CB2601 00 00 48 06
            # 00 69 53 ... is heat/22/fan-low still encoded. Sending a hardcoded
            # AUTO @ 21 wipes the mode byte and the unit's real settings.
            await self._send(self._current_code())
        else:
            self._power = True
            # Update the mode BEFORE encoding: _current_code() reads the mode,
            # so setting it afterwards sent a frame still tagged with the old
            # mode (cool -> heat transmitted as cool).
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
        # Accept legacy capitalised labels ("High"/"Med") from older
        # automations, but always store HA's canonical value so the icon map
        # resolves and the selector shows the right option highlighted.
        self._attr_fan_mode = normalise_fan_mode(fan_mode) or "auto"
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        self._attr_swing_mode = normalise_swing_mode(swing_mode) or "off"
        if self._power:
            await self._send(self._current_code())
        self.async_write_ha_state()

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Wide-vane control (byte 8, bits 4-7) -- an independent axis."""
        self._attr_swing_horizontal_mode = (
            normalise_swing_horizontal_mode(swing_horizontal_mode) or "off"
        )
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
        )

    async def async_added_to_hass(self) -> None:
        """Restore the last known state after a restart or reboot."""
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

        # Normalise rather than compare against FAN_MODES/SWING_MODES: state
        # persisted by an older version holds "High"/"swing", which must be
        # migrated instead of silently dropped back to the default.
        if fan := normalise_fan_mode(stored.get("fan_mode", attrs.get("fan_mode"))):
            self._attr_fan_mode = fan

        if swing := normalise_swing_mode(
            stored.get("swing_mode", attrs.get("swing_mode"))
        ):
            self._attr_swing_mode = swing

        if swing_h := normalise_swing_horizontal_mode(
            stored.get(
                "swing_horizontal_mode", attrs.get("swing_horizontal_mode")
            )
        ):
            self._attr_swing_horizontal_mode = swing_h

        # Deliberately no IR transmission here: the link is one-way (blind
        # blaster), so sending at startup would only blast the unit and undo
        # any change made with the wall remote while HA was down.
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
    """Register `mitsubishi_remote.force_send` exactly once.

    For a legacy YAML platform HA only calls the `async_setup_platform` in
    *this* file -- the one in `__init__.py` is never executed, which is why the
    service used to be missing despite being registered there and documented in
    services.yaml. Registering here, guarded by `has_service`, also survives
    YAML reloads without "service already registered" errors.
    """
    if hass.services.has_service(DOMAIN, SERVICE_FORCE_SEND):
        return

    async def async_force_send(call) -> None:
        data = dict(call.data)
        entity_ids = data.get(ATTR_ENTITY_ID)
        if isinstance(entity_ids, str):
            entity_ids = [entity_ids]

        # Reloading the YAML platform appends a new entity object without
        # evicting the old one, so keep only the newest per entity_id to avoid
        # blasting every command twice after each reload.
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

    from .const import CONF_NAME

    entity = MitsubishiRemoteClimate(
        remote_entity=config[CONF_REMOTE_ENTITY],
        name=config.get(CONF_NAME, DEFAULT_NAME),
        command_format=config.get(CONF_COMMAND_FORMAT, DEFAULT_COMMAND_FORMAT),
        hex_prefix=config.get(CONF_HEX_PREFIX, DEFAULT_HEX_PREFIX),
        retries=config.get(CONF_RETRIES, DEFAULT_RETRIES),
        repeat_gap=config.get(CONF_REPEAT_GAP, DEFAULT_REPEAT_GAP),
        install_position=config.get(
            CONF_INSTALL_POSITION, DEFAULT_INSTALL_POSITION
        ),
    )
    # Hand the feature switches over to the switch platform. They are created
    # here because this entity owns the frame and the transport; `switch:` has
    # no YAML entry of its own.
    hass.async_create_task(
        async_load_platform(hass, "switch", DOMAIN, {"climate": entity}, config)
    )

    # Keep a reference so the domain service can reach the entity/entities.
    #
    # No de-duplication here: at this point `entity.entity_id` is still
    # `unknown.unknown` (HA assigns the real id when the entity is added), so
    # filtering the list now would drop a legitimately-configured second AC.
    # Stale objects from a YAML reload are collapsed by entity_id at call time
    # in `_async_register_force_send` instead.
    hass.data.setdefault(DOMAIN, []).append(entity)
    async_add_entities([entity], update_before_add=False)   # callback, not coroutine

    await _async_register_force_send(hass)
