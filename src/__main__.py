import asyncio
import logging
import sys
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from src.ui.main_window import MainWindow
from src.utils.config import Config
from src.utils.logger import setup_logging
from src.utils.network_utils import request_firewall_permission

def main():
    # Setup logging first
    setup_logging()

    # Request firewall permissions if needed
    if not request_firewall_permission():
        logging.warning("Firewall permissions not granted - connections may fail")

    # Qt application setup
    app = QApplication(sys.argv)
    app.setApplicationName("BruvTorrent")
    app.setApplicationDisplayName("BruvTorrent")
    app.setOrganizationName("BruvTorrent")

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