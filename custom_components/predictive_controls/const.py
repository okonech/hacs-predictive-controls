DOMAIN = "predictive_controls"
NAME = "Predictive Controls"
VERSION = "0.1.9"
PANEL_FILENAME = "panel-v0.1.9.js"

CONF_ACTIONS_YAML = "actions_yaml"
CONF_EXPECTED_OCCUPANTS = "expected_occupants"
CONF_MAP_YAML = "map_yaml"
CONF_PREDICTION_THRESHOLD = "prediction_threshold"
CONF_TRANSITION_WINDOW = "transition_window_seconds"

DEFAULT_EXPECTED_OCCUPANTS = 0
DEFAULT_PREDICTION_THRESHOLD = 0.6
DEFAULT_TRANSITION_WINDOW = 30

DISPATCH_UPDATE = f"{DOMAIN}_update"
STATIC_PATH_REGISTERED = "_static_path_registered"
WEBSOCKET_REGISTERED = "_websocket_registered"
STORAGE_VERSION = 1
