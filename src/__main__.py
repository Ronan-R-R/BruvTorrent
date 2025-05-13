import asyncio
import logging
import platform  # Add this import
import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from qasync import QEventLoop

from src.ui.main_window import MainWindow
from src.utils.config import Config
from src.utils.logger import setup_logging
from src.utils.network_utils import request_firewall_permission, check_firewall_permissions

def show_firewall_prompt(parent=None) -> bool:
    """Show GUI prompt for firewall permissions"""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Warning)
    msg.setText("Firewall Permission Required")
    msg.setInformativeText(
        "BruvTorrent needs to add a firewall rule to allow incoming connections. "
        "This is required for proper peer-to-peer functionality."
    )
    msg.setWindowTitle("Firewall Configuration")
    msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    return msg.exec() == QMessageBox.Ok

def main():
    # Setup logging first
    setup_logging()

    # Qt application setup
    app = QApplication(sys.argv)
    app.setApplicationName("BruvTorrent")
    app.setApplicationDisplayName("BruvTorrent")
    app.setOrganizationName("BruvTorrent")

    # Check and request firewall permissions
    if platform.system() == 'Windows':
        if show_firewall_prompt():
            if not request_firewall_permission():
                logging.error("Failed to configure firewall rules")
        else:
            logging.warning("Firewall permissions not granted - connections may be limited")

    # Set up asyncio event loop integrated with Qt
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Create and show main window
    window = MainWindow()
    window.show()

    # Run the application
    with loop:
        sys.exit(loop.run_forever())

if __name__ == "__main__":
    main()