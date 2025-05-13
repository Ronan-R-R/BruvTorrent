import asyncio
import logging
import platform
import sys
from PySide6.QtWidgets import QApplication
from qasync import QEventLoop


def main():
    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Initialize Qt
    app = QApplication(sys.argv)

    # Automatically request firewall permissions if needed on Windows
    if platform.system() == 'Windows':
        from src.utils.network_utils import request_windows_firewall_rule
        request_windows_firewall_rule(sys.executable)

    # Setup event loop and main window
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    from src.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    with loop:
        sys.exit(loop.run_forever())


if __name__ == "__main__":
    main()