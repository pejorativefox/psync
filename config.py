import tomllib
from pathlib import Path

def _load_settings():
    """Internal function to load settings from the local TOML file."""
    settings_path = Path("settings.toml")
    if not settings_path.exists():
        return {}
    with open(settings_path, "rb") as f:
        return tomllib.load(f)

# The global settings object
SETTINGS = _load_settings()

def _get_base_path():
    """Resolves the base path from settings to an absolute string."""
    path_str = SETTINGS.get("core", {}).get("base_path", ".")
    return str(Path(path_str).expanduser().resolve())

BASE_PATH = _get_base_path()

def _get_data_path():
    """Resolves the data storage path from settings."""
    path_str = SETTINGS.get("core", {}).get("data_path", "data")
    return str(Path(path_str).expanduser().resolve())

DATA_PATH = _get_data_path()