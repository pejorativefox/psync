import tomllib
from pathlib import Path
from platformdirs import user_config_dir

class Config:
    """Configuration object for Psync."""
    def __init__(self, settings_path=None):
        if settings_path is None:
            settings_path = Path(user_config_dir("psync")) / "settings.toml"
        self.settings = self._load_settings(settings_path)
        self.base_path = self._get_base_path()
        self.ignore_patterns = self.settings.get("core", {}).get("ignore", [])
        self.server_hostname = self.settings.get("core", {}).get("server_hostname", "127.0.0.1")
        self.server_port = self.settings.get("core", {}).get("server_port", 8000)

    def _load_settings(self, settings_path):
        """Internal function to load settings from the local TOML file."""
        path = Path(settings_path)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            default_config = (
                "[core]\n"
                'base_path = "."\n'
                'server_hostname = "127.0.0.1"\n'
                'server_port = 8000\n'
                'ignore = [".git/", "__pycache__/", "*.pyc", ".DS_Store"]\n'
            )
            path.write_text(default_config)
        with open(path, "rb") as f:
            return tomllib.load(f)

    def _get_base_path(self):
        """Resolves the base path from settings to an absolute string."""
        path_str = self.settings.get("core", {}).get("base_path", ".")
        return str(Path(path_str).expanduser().resolve())