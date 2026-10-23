"""Constants for the Mitsubishi IR remote custom integration."""

DOMAIN = "mitsubishi_remote"

# Configuration keys
CONF_NAME = "name"
CONF_REMOTE_ENTITY = "remote_entity"
CONF_COMMAND_FORMAT = "command_format"      # "hex" or "name"
CONF_HEX_PREFIX = "hex_prefix"              # prepend "0x" to hex payload
CONF_RETRIES = "retries"                    # how many times to send a command
CONF_REPEAT_GAP = "repeat_gap"              # seconds between retries
CONF_SWING_MODE = "swing_mode"              # expose a swing selector
CONF_INSTALL_POSITION = "install_position"  # installer dip switch (byte 15)

DEFAULT_NAME = "Mitsubishi AC"
DEFAULT_COMMAND_FORMAT = "hex"
DEFAULT_HEX_PREFIX = False
DEFAULT_RETRIES = 2
DEFAULT_REPEAT_GAP = 0.35
DEFAULT_SWING_MODE = True
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 31
DEFAULT_TEMP_STEP = 1

# The installer "dip switch" for where the indoor unit is mounted. This is a
# one-time installation setting, not a daily control, so it is a YAML config
# option rather than an entity. `None` = leave byte 15 untouched (default,
# preserves the previous behaviour of always sending the 0x40 base).
DEFAULT_INSTALL_POSITION = None
INSTALL_POSITIONS = ["left", "middle", "right"]

# Service names
SERVICE_FORCE_SEND = "force_send"

# Independent on/off features exposed as switch entities.
#
# Defaults reproduce the frame this integration has always sent (all three
# bits set), so upgrading changes nothing on the wire until a switch is used.
# plasma is flagged experimental: byte 15 bit 6 is unverified.
FEATURE_DEFAULTS = {
    "isee": True,
    "clean": True,
    "plasma": True,
}
FEATURE_KEYS = list(FEATURE_DEFAULTS)
EXPERIMENTAL_FEATURES = ("plasma",)

# `hass.data[DOMAIN]` is already a *list* of climate entities (the force_send
# service iterates it), so the feature switches need their own key.
DATA_SWITCHES = f"{DOMAIN}_switches"
