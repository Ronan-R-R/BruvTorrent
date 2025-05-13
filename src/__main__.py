import asyncio
import sys
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from src.ui.main_window import MainWindow
from src.utils.config import Config
from src.utils.logger import setup_logging

def main():
    # Setup logging
    setup_logging()

    # Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("BruvTorrent")
    app.setApplicationDisplayName("BruvTorrent")
    app.setOrganizationName("BruvTorrent")

    # Set up asyncio event loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # Main window
    window = MainWindow()
    window.show()

    # Run the application
    with loop:
        loop.run_forever()

if __name__ == "__main__":
    main()