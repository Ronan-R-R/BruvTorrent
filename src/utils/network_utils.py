import ctypes
import logging
import platform  # Add this import
import socket
import sys
from typing import Optional


def check_firewall_permissions(host: str, port: int) -> bool:
    """Check if firewall might be blocking connections"""
    try:
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.settimeout(2)
        test_socket.connect((host, port))
        test_socket.close()
        return True
    except socket.error as e:
        logging.warning(f"Firewall may be blocking connections to {host}:{port}: {e}")
        return False


def request_firewall_permission(app_name: str = "BruvTorrent") -> bool:
    """Request firewall permissions (Windows only)"""
    if platform.system() == 'Windows':  # Now using the imported platform module
        try:
            # Create a proper firewall rule with elevated privileges
            command = (
                f'netsh advfirewall firewall add rule '
                f'name="{app_name}" '
                f'dir=in action=allow '
                f'program="{sys.executable}" '
                f'enable=yes'
            )

            # Run with proper UAC elevation
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "netsh", command, None, 1
            )
            return True
        except Exception as e:
            logging.error(f"Failed to request firewall permission: {e}")
            return False
    return True