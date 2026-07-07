"""JSON-backed persistent settings."""
import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger('config')

DEFAULTS: Dict[str, Any] = {
    'theme': 'dark',
    'download_dir': str(Path.home() / 'Downloads' / 'BruvTorrent'),
    'listen_port': 6881,
    'max_connections': 200,
    'start_minimized': False,
    'firewall_rule_created': False,
    'torrents': [],   # list of {"type": "file"|"magnet", "source": str, "paused": bool}
}


class Config:
    def __init__(self) -> None:
        self.config_path = self._get_config_path()
        self.data: Dict[str, Any] = dict(DEFAULTS)
        self.data.update(self._load())

    def _get_config_path(self) -> Path:
        base = Path.home() / '.config' / 'BruvTorrent'
        base.mkdir(parents=True, exist_ok=True)
        return base / 'settings.json'

    def _load(self) -> Dict[str, Any]:
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    return loaded
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("could not read config, using defaults: %s", exc)
        return {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self._save()

    def _save(self) -> None:
        try:
            tmp = self.config_path.with_suffix('.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            tmp.replace(self.config_path)
        except OSError as exc:
            logger.error("could not save config: %s", exc)
