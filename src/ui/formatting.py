"""Human-readable formatting helpers for the UI."""
from typing import Optional


def format_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f"{value:.1f} {unit}" if unit != 'B' else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} TB"


def format_speed(bytes_per_sec: float) -> str:
    if bytes_per_sec < 1:
        return "0 B/s"
    return f"{format_size(bytes_per_sec)}/s"


def format_eta(seconds: Optional[int]) -> str:
    if seconds is None:
        return "-"
    if seconds <= 0:
        return "done"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
