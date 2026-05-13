import tomllib
from pathlib import Path
from platformdirs import user_config_dir

class Config:
    """Configuration object for Psync."""
    def __init__(self, settings_path=None):
        if settings_path is None:
            settings_path = Path(user_config_dir("psync")) / "settings.toml"
        self.settings_path = settings_path
        self.is_new = False
        self.settings = self._load_settings(settings_path)
        self.base_path = self._get_base_path()
        self.ignore_patterns = self.settings.get("core", {}).get("ignore", [])
        self.server_hostname = self.settings.get("core", {}).get("server_hostname", "127.0.0.1")
        self.server_port = self.settings.get("core", {}).get("server_port", 8000)
        self.remote_sync_interval = self.settings.get("core", {}).get("remote_sync_interval", 60)

    def _load_settings(self, settings_path):
        """Internal function to load settings from the local TOML file."""
        path = Path(settings_path)
        if not path.exists():
            self.is_new = True
            path.parent.mkdir(parents=True, exist_ok=True)
            default_config = (
                "[core]\n"
                'base_path = "."\n'
                'server_hostname = "127.0.0.1"\n'
                'server_port = 8000\n'
                'ignore = [".git/", "__pycache__/", "*.pyc", ".DS_Store"]\n'
                'remote_sync_interval = 60\n'
            )
            path.write_text(default_config)
        with open(path, "rb") as f:
            return tomllib.load(f)

    def _get_base_path(self):
        """Resolves the base path from settings to an absolute string."""
        path_str = self.settings.get("core", {}).get("base_path", ".")
        return str(Path(path_str).expanduser().resolve())

    def save_settings(self, base_path, server_hostname, server_port, remote_sync_interval, ignore_patterns):
        """Updates and saves the configuration settings to disk."""
        self.settings.setdefault("core", {})
        self.settings["core"]["base_path"] = base_path
        self.settings["core"]["server_hostname"] = server_hostname
        self.settings["core"]["server_port"] = int(server_port)
        self.settings["core"]["remote_sync_interval"] = int(remote_sync_interval)
        self.settings["core"]["ignore"] = ignore_patterns

        # Update local attributes for immediate use
        self.base_path = str(Path(base_path).expanduser().resolve())
        self.server_hostname = server_hostname
        self.server_port = int(server_port)
        self.remote_sync_interval = int(remote_sync_interval)
        self.ignore_patterns = ignore_patterns

        lines = []
        for section, values in self.settings.items():
            lines.append(f"[{section}]")
            for k, v in values.items():
                if isinstance(v, list):
                    val = "[" + ", ".join(f'"{i}"' for i in v) + "]"
                elif isinstance(v, str):
                    val = f'"{v}"'
                else:
                    val = v
                lines.append(f'{k} = {val}')
            lines.append("") # Spacer
        
        self.settings_path.write_text("\n".join(lines))
        self.is_new = False