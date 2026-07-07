"""Application logging setup."""
import logging
from pathlib import Path
from typing import Optional


def setup_logging(log_level: int = logging.INFO,
                  log_file: Optional[str] = None) -> None:
    if log_file is None:
        log_dir = Path.home() / ".cache" / "BruvTorrent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / "bruvtorrent.log")

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    root = logging.getLogger()
    root.setLevel(log_level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
