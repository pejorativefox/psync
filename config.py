import tomllib
from pathlib import Path

class Config:
    """Configuration object for Psync."""
    def __init__(self, settings_path="settings.toml"):
        self.settings = self._load_settings(settings_path)
        self.base_path = self._get_base_path()
        self.data_path = self._get_data_path()
        self.server_hostname = self.settings.get("core", {}).get("server_hostname", "127.0.0.1")
        self.server_port = self.settings.get("core", {}).get("server_port", 8000)
        self.ignore_patterns = self.settings.get("core", {}).get("ignore", [])

    def _load_settings(self, settings_path):
        """Internal function to load settings from the local TOML file."""
        path = Path(settings_path)
        if not path.exists():
            return {}
        with open(path, "rb") as f:
            return tomllib.load(f)

    def _get_base_path(self):
        """Resolves the base path from settings to an absolute string."""
        path_str = self.settings.get("core", {}).get("base_path", ".")
        return str(Path(path_str).expanduser().resolve())

    def _get_data_path(self):
        """Resolves the data storage path from settings."""
        path_str = self.settings.get("core", {}).get("data_path", "data")
        return str(Path(path_str).expanduser().resolve())