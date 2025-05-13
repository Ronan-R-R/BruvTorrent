import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QProgressBar, QStatusBar,
                               QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)
from qasync import asyncSlot

from src.core.torrent import Torrent
from src.core.tracker import Tracker
from src.core.peer import PeerConnection
from src.core.piece_manager import PieceManager
from src.utils.config import Config
from src.utils.logger import setup_logging
from src.ui.settings import SettingsDialog
from src.ui.themes import apply_theme


class TorrentItem(QTreeWidgetItem):
    def __init__(self, torrent: Torrent, manager: PieceManager):
        super().__init__()
        self.torrent = torrent
        self.manager = manager
        self.update()

    def update(self):
        self.setText(0, self.torrent.output_file)
        self.setText(1, f"{self.manager.get_completion() * 100:.1f}%")
        self.setText(2, self._format_size(self.torrent.total_size))
        self.setText(3, self.torrent.announce)

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class MainWindow(QMainWindow):
    torrent_added = Signal(Torrent, PieceManager)
    torrent_removed = Signal(str)

    def __init__(self):
        super().__init__()
        self.config = Config()
        self.torrents: Dict[str, Tuple[Torrent, PieceManager]] = {}
        self.peer_connections: List[PeerConnection] = []
        self.setWindowTitle("BruvTorrent")
        self.setMinimumSize(QSize(800, 600))
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()
        setup_logging()
        apply_theme(self, self.config.get('theme', 'dark'))
        self._load_torrents_from_config()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Torrent list
        self.torrent_list = QTreeWidget()
        self.torrent_list.setHeaderLabels(["Name", "Progress", "Size", "Tracker"])
        self.torrent_list.setColumnCount(4)
        self.torrent_list.setSortingEnabled(True)
        layout.addWidget(self.torrent_list)

        # Progress bar
        self.global_progress = QProgressBar()
        self.global_progress.setRange(0, 100)
        layout.addWidget(self.global_progress)

        # Info panel
        self.info_panel = QLabel("No torrent selected")
        self.info_panel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.info_panel)

        # Signals
        self.torrent_list.itemClicked.connect(self._show_torrent_info)
        self.torrent_added.connect(self._add_torrent_item)
        self.torrent_removed.connect(self._remove_torrent_item)

        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._update_torrents)
        self.update_timer.start(1000)

    def _setup_menu(self):
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        add_action = QAction("&Add Torrent", self)
        add_action.triggered.connect(self._add_torrent)
        file_menu.addAction(add_action)

        remove_action = QAction("&Remove Torrent", self)
        remove_action.triggered.connect(self._remove_torrent)
        file_menu.addAction(remove_action)

        exit_action = QAction("&Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Settings menu
        settings_menu = menubar.addMenu("&Settings")

        preferences_action = QAction("&Preferences", self)
        preferences_action.triggered.connect(self._show_settings)
        settings_menu.addAction(preferences_action)

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setIconSize(QSize(32, 32))
        self.addToolBar(toolbar)

        add_action = QAction(QIcon.fromTheme("document-open"), "Add Torrent", self)
        add_action.triggered.connect(self._add_torrent)
        toolbar.addAction(add_action)

        remove_action = QAction(QIcon.fromTheme("edit-delete"), "Remove Torrent", self)
        remove_action.triggered.connect(self._remove_torrent)
        toolbar.addAction(remove_action)

        play_action = QAction(QIcon.fromTheme("media-playback-start"), "Start", self)
        play_action.triggered.connect(self._start_torrent)
        toolbar.addAction(play_action)

        pause_action = QAction(QIcon.fromTheme("media-playback-pause"), "Pause", self)
        pause_action.triggered.connect(self._pause_torrent)
        toolbar.addAction(pause_action)

    def _setup_statusbar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _load_torrents_from_config(self):
        saved_torrents = self.config.get('torrents', [])
        for path in saved_torrents:
            if os.path.exists(path):
                asyncio.create_task(self._load_torrent(path))

    @asyncSlot()
    async def _load_torrent(self, path: str):
        try:
            torrent = Torrent(path)
            piece_manager = PieceManager(torrent)
            self.torrents[path] = (torrent, piece_manager)
            self.torrent_added.emit(torrent, piece_manager)
            await self._start_download(torrent, piece_manager)
        except Exception as e:
            logging.error(f"Failed to load torrent {path}: {e}")

    @asyncSlot()
    async def _add_torrent(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Torrent File", "", "Torrent Files (*.torrent)")
        if path:
            await self._load_torrent(path)
            # Save to config
            torrents = self.config.get('torrents', [])
            if path not in torrents:
                torrents.append(path)
                self.config.set('torrents', torrents)

    def _remove_torrent(self):
        item = self.torrent_list.currentItem()
        if item and isinstance(item, TorrentItem):
            path = item.torrent.path
            if path in self.torrents:
                self.torrents[path][1].close()
                del self.torrents[path]
                self.torrent_removed.emit(path)
                # Remove from config
                torrents = self.config.get('torrents', [])
                if path in torrents:
                    torrents.remove(path)
                    self.config.set('torrents', torrents)

    async def _start_download(self, torrent: Torrent, piece_manager: PieceManager):
        tracker = Tracker(torrent)
        try:
            peers = await tracker.get_peers()
            for peer in peers:
                peer_conn = PeerConnection(
                    peer_id=tracker.peer_id,
                    info_hash=torrent.info_hash,
                    piece_manager=piece_manager,
                    peer=peer
                )
                if await peer_conn.connect():
                    self.peer_connections.append(peer_conn)
                    asyncio.create_task(peer_conn.receive_messages())
                    await peer_conn.send_unchoke()
                    await peer_conn.send_interested()
        except Exception as e:
            logging.error(f"Error starting download: {e}")

    def _start_torrent(self):
        item = self.torrent_list.currentItem()
        if item and isinstance(item, TorrentItem):
            logging.info(f"Starting torrent: {item.torrent.output_file}")

    def _pause_torrent(self):
        item = self.torrent_list.currentItem()
        if item and isinstance(item, TorrentItem):
            logging.info(f"Pausing torrent: {item.torrent.output_file}")

    def _show_torrent_info(self, item):
        if isinstance(item, TorrentItem):
            torrent = item.torrent
            info = (
                f"<b>Name:</b> {torrent.output_file}<br>"
                f"<b>Size:</b> {self._format_size(torrent.total_size)}<br>"
                f"<b>Pieces:</b> {len(torrent.pieces)}<br>"
                f"<b>Piece Size:</b> {self._format_size(torrent.piece_length)}<br>"
                f"<b>Tracker:</b> {torrent.announce}<br>"
                f"<b>Hash:</b> {torrent.info_hash.hex()}<br>"
            )
            if comment := torrent.get_comment():
                info += f"<b>Comment:</b> {comment}<br>"
            self.info_panel.setText(info)

    def _add_torrent_item(self, torrent: Torrent, piece_manager: PieceManager):
        item = TorrentItem(torrent, piece_manager)
        self.torrent_list.addTopLevelItem(item)

    def _remove_torrent_item(self, path: str):
        for i in range(self.torrent_list.topLevelItemCount()):
            item = self.torrent_list.topLevelItem(i)
            if isinstance(item, TorrentItem) and item.torrent.path == path:
                self.torrent_list.takeTopLevelItem(i)
                break

    def _update_torrents(self):
        total_progress = 0
        total_torrents = len(self.torrents)

        if total_torrents > 0:
            for i in range(self.torrent_list.topLevelItemCount()):
                item = self.torrent_list.topLevelItem(i)
                if isinstance(item, TorrentItem):
                    item.update()
                    total_progress += item.manager.get_completion()

            avg_progress = (total_progress / total_torrents) * 100
            self.global_progress.setValue(int(avg_progress))

    def _show_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            new_theme = dialog.get_selected_theme()
            apply_theme(self, new_theme)
            self.config.set('theme', new_theme)

    def closeEvent(self, event):
        for _, (_, manager) in self.torrents.items():
            manager.close()
        event.accept()

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"