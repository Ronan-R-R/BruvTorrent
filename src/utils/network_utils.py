# src/utils/network_utils.py
import ctypes
import logging
import platform
import socket
import sys

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
    if platform.system() == 'Windows':
        try:
            # Request firewall permission (will show UAC prompt)
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "netsh",
                f"advfirewall firewall add rule name=\"{app_name}\" "
                "dir=in action=allow program=\"\" "
                "enable=yes", None, 0
            )
            return True
        except Exception as e:
            logging.warning(f"Failed to request firewall permission: {e}")
            return False
    return True