"""Constants for the Mitsubishi IR remote custom integration."""

DOMAIN = "mitsubishi_remote"

# Configuration keys
CONF_NAME = "name"
CONF_REMOTE_ENTITY = "remote_entity"
CONF_RETRIES = "retries"                    # how many times to send a command
CONF_REPEAT_GAP = "repeat_gap"              # seconds between retries
CONF_INSTALL_POSITION = "install_position"  # slide switch in the remote (byte 14)

DEFAULT_NAME = "Mitsubishi AC"
DEFAULT_RETRIES = 2
DEFAULT_REPEAT_GAP = 0.35
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 31

# INSTALL_POS: where the indoor unit hangs on the wall (IR_PROTOCOL.md §3.10).
# It is a one-time installation setting, so it is a YAML option, not an entity.
DEFAULT_INSTALL_POSITION = "center"
INSTALL_POSITIONS = ["left", "center", "right"]

# Service names
SERVICE_FORCE_SEND = "force_send"

# Independent on/off features, exposed as switch entities. The defaults match
# the frames that earlier versions sent (all three bits on).
FEATURE_DEFAULTS = {
    "isee": True,
    "clean": True,
    "plasma": True,
}
FEATURE_KEYS = list(FEATURE_DEFAULTS)

# `hass.data[DOMAIN]` is already a *list* of climate entities (the force_send
# service iterates it), so the feature switches need their own key.
DATA_SWITCHES = f"{DOMAIN}_switches"
