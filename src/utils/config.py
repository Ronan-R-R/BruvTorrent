import json
import os
from pathlib import Path
from typing import Any, Dict

class Config:
    def __init__(self):
        self.config_path = self._get_config_path()
        self.data = self._load_config()

    def _get_config_path(self) -> Path:
        config_dir = Path.home() / ".config" / "BruvTorrent"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "settings.json"

    def _load_config(self) -> Dict[str, Any]:
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
        return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self._save_config()

    def _save_config(self) -> None:
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.data, f, indent=4)
        except IOError:
            pass

    def remove(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self._save_config()