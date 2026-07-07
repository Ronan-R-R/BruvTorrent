import asyncio
import os
import platform
import sys

from PySide6.QtWidgets import QApplication
from qasync import QEventLoop

from src.utils.config import Config
from src.utils.logger import setup_logging


def main() -> None:
    setup_logging()
    config = Config()
    os.makedirs(config.get('download_dir'), exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName("BruvTorrent")

    if platform.system() == 'Windows':
        from src.utils.network_utils import ensure_firewall_rule
        ensure_firewall_rule(sys.executable, config)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    from src.ui.main_window import MainWindow
    window = MainWindow(config)
    if config.get('start_minimized'):
        window.showMinimized()
    else:
        window.show()

    asyncio.ensure_future(window.init_engine())

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
