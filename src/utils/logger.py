import logging
import os
from pathlib import Path
from typing import Optional

def setup_logging(log_level: int = logging.INFO,
                 log_file: Optional[str] = None) -> None:
    """Configure logging for the application"""
    if log_file is None:
        log_dir = Path.home() / ".cache" / "BruvTorrent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = str(log_dir / "bruvtorrent.log")

    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Clear any existing handlers
    logging.basicConfig(level=log_level, handlers=[])

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # Add handlers
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Set log level for external libraries
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)