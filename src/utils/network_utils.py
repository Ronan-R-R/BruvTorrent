import ctypes
import logging
import platform
import socket
import subprocess
from typing import Tuple, Optional


def is_firewall_blocking(host: str, port: int) -> Tuple[bool, Optional[str]]:
    """Check if connection is being blocked by firewall"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((host, port))
        return False, None
    except socket.timeout:
        return True, "Connection timed out"
    except ConnectionRefusedError:
        return False, "Connection refused"
    except OSError as e:
        if platform.system() == 'Windows' and e.winerror == 121:  # Semaphore timeout
            return True, "Windows Firewall may be blocking"
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"


def request_windows_firewall_rule(app_path: str, app_name: str = "BruvTorrent") -> bool:
    """Request Windows Firewall rule directly through Windows API"""
    if platform.system() != 'Windows':
        return False

    try:
        command = (
            f'netsh advfirewall firewall add rule '
            f'name="{app_name}" '
            f'dir=in action=allow '
            f'program="{app_path}" '
            f'enable=yes profile=any'
        )

        # Execute with admin privileges
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", "netsh", command, None, 0
        )
        return True
    except Exception as e:
        logging.error(f"Failed to create firewall rule: {e}")
        return False