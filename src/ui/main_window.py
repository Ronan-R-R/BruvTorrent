"""Main application window."""
import asyncio
import logging
from typing import Dict

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHeaderView,
                               QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSplitter, QStyle,
                               QStyledItemDelegate, QStyleOptionProgressBar,
                               QTabWidget, QToolBar, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)
from qasync import asyncSlot

from src.core.engine import Engine
from src.core.session import TorrentSession
from src.ui.formatting import format_eta, format_size, format_speed
from src.ui.settings import SettingsDialog
from src.ui.themes import apply_theme, colors_for

logger = logging.getLogger('ui')

COL_NAME, COL_SIZE, COL_PROGRESS, COL_STATUS = 0, 1, 2, 3
COL_DOWN, COL_UP, COL_PEERS, COL_SEEDS, COL_ETA = 4, 5, 6, 7, 8
HEADERS = ["Name", "Size", "Progress", "Status",
           "Down", "Up", "Peers", "Seeds", "ETA"]
PROGRESS_ROLE = Qt.UserRole + 1


class ProgressDelegate(QStyledItemDelegate):
    """Renders a progress bar inside the Progress column."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)

    def paint(self, painter, option, index):
        progress = index.data(PROGRESS_ROLE)
        if progress is None:
            super().paint(painter, option, index)
            return
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        bar = QStyleOptionProgressBar()
        bar.rect = QRect(option.rect).adjusted(4, 4, -4, -4)
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = int(progress * 100)
        bar.text = f"{progress * 100:.1f}%"
        bar.textVisible = True
        QApplication.style().drawControl(QStyle.CE_ProgressBar, bar, painter)


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.engine = Engine(
            save_dir=config.get('download_dir'),
            port=int(config.get('listen_port')))
        self.engine.set_change_callback(self._on_session_changed)
        self._rows: Dict[bytes, QTreeWidgetItem] = {}

        self.setWindowTitle("BruvTorrent")
        self.setMinimumSize(QSize(960, 600))
        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        apply_theme(self, config.get('theme'))

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh)
        self.timer.start(1000)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Vertical)

        self.table = QTreeWidget()
        self.table.setHeaderLabels(HEADERS)
        self.table.setColumnCount(len(HEADERS))
        self.table.setRootIsDecorated(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._update_detail)
        self.table.setItemDelegateForColumn(
            COL_PROGRESS, ProgressDelegate(colors_for(self.config.get('theme'))['accent']))

        header = self.table.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in range(1, len(HEADERS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        self.detail = self._build_detail()

        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.status = self.statusBar()
        self.status_label = QLabel("Ready")
        self.status.addWidget(self.status_label)

    def _build_detail(self) -> QTabWidget:
        tabs = QTabWidget()
        self.general_label = QLabel("No torrent selected")
        self.general_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.general_label.setWordWrap(True)
        self.general_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.general_label.setContentsMargins(12, 12, 12, 12)

        self.trackers_tree = QTreeWidget()
        self.trackers_tree.setHeaderLabels(["Tracker", "Tier"])
        self.trackers_tree.setRootIsDecorated(False)

        self.peers_tree = QTreeWidget()
        self.peers_tree.setHeaderLabels(["Address", "Client", "Down", "Up", "Pieces"])
        self.peers_tree.setRootIsDecorated(False)

        tabs.addTab(self.general_label, "General")
        tabs.addTab(self.trackers_tree, "Trackers")
        tabs.addTab(self.peers_tree, "Peers")
        return tabs

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._action("Add &Torrent File...", self._add_file,
                                         QKeySequence.Open))
        file_menu.addAction(self._action("Add &Magnet Link...", self._add_magnet))
        file_menu.addSeparator()
        file_menu.addAction(self._action("E&xit", self.close, QKeySequence.Quit))

        settings_menu = self.menuBar().addMenu("&Settings")
        settings_menu.addAction(self._action("&Preferences...", self._open_settings))

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        style = self.style()
        toolbar.addAction(self._action(
            "Add Torrent", self._add_file,
            icon=style.standardIcon(QStyle.SP_DialogOpenButton)))
        toolbar.addAction(self._action(
            "Add Magnet", self._add_magnet,
            icon=style.standardIcon(QStyle.SP_FileLinkIcon)))
        toolbar.addSeparator()
        self.resume_action = self._action(
            "Resume", self._resume_selected,
            icon=style.standardIcon(QStyle.SP_MediaPlay))
        self.pause_action = self._action(
            "Pause", self._pause_selected,
            icon=style.standardIcon(QStyle.SP_MediaPause))
        self.remove_action = self._action(
            "Remove", self._remove_selected,
            icon=style.standardIcon(QStyle.SP_TrashIcon))
        toolbar.addAction(self.resume_action)
        toolbar.addAction(self.pause_action)
        toolbar.addAction(self.remove_action)

    def _action(self, text, slot, shortcut=None, icon=None) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(icon)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        return action

    # ------------------------------------------------------------------
    # Engine lifecycle
    async def init_engine(self) -> None:
        await self.engine.start_listener()
        for entry in self.config.get('torrents', []):
            await self._restore_entry(entry)

    async def _restore_entry(self, entry: dict) -> None:
        try:
            if entry.get('type') == 'magnet':
                session = await self.engine.add_magnet(entry['source'])
            else:
                session = await self.engine.add_torrent_file(entry['source'])
            self._ensure_row(session)
            if entry.get('paused'):
                await session.pause()
        except (OSError, ValueError) as exc:
            logger.warning("could not restore %s: %s", entry.get('source'), exc)

    def _persist_torrents(self) -> None:
        entries = []
        for session in self.engine.list_sessions():
            if session.magnet and not session.torrent:
                entries.append({'type': 'magnet',
                                'source': f"magnet:?xt=urn:btih:{session.torrent_hash.hex()}",
                                'paused': session.paused})
            elif session.torrent and session.torrent.source_path:
                entries.append({'type': 'file',
                                'source': session.torrent.source_path,
                                'paused': session.paused})
        self.config.set('torrents', entries)

    # ------------------------------------------------------------------
    # Actions
    @asyncSlot()
    async def _add_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add torrent", "", "Torrent files (*.torrent)")
        for path in paths:
            try:
                session = await self.engine.add_torrent_file(path)
                self._ensure_row(session)
            except (OSError, ValueError) as exc:
                self._error(f"Could not load torrent:\n{exc}")
        self._persist_torrents()

    @asyncSlot()
    async def _add_magnet(self) -> None:
        uri, ok = QInputDialog.getText(self, "Add magnet", "Magnet link:")
        if not ok or not uri.strip():
            return
        try:
            session = await self.engine.add_magnet(uri.strip())
            self._ensure_row(session)
            self._persist_torrents()
        except ValueError as exc:
            self._error(f"Invalid magnet link:\n{exc}")

    @asyncSlot()
    async def _resume_selected(self) -> None:
        for session in self._selected_sessions():
            await session.resume()
        self._persist_torrents()

    @asyncSlot()
    async def _pause_selected(self) -> None:
        for session in self._selected_sessions():
            await session.pause()
        self._persist_torrents()

    @asyncSlot()
    async def _remove_selected(self) -> None:
        sessions = self._selected_sessions()
        if not sessions:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Remove torrent")
        box.setText(f"Remove {len(sessions)} torrent(s)?")
        keep = box.addButton("Remove (keep files)", QMessageBox.AcceptRole)
        delete = box.addButton("Remove and delete files", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (keep, delete):
            return
        for session in sessions:
            await self.engine.remove(session.torrent_hash, delete_data=clicked is delete)
            item = self._rows.pop(session.torrent_hash, None)
            if item:
                idx = self.table.indexOfTopLevelItem(item)
                self.table.takeTopLevelItem(idx)
        self._persist_torrents()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            apply_theme(self, dialog.selected_theme)
            self.table.setItemDelegateForColumn(
                COL_PROGRESS,
                ProgressDelegate(colors_for(dialog.selected_theme)['accent']))

    # ------------------------------------------------------------------
    # Table sync
    def _ensure_row(self, session: TorrentSession) -> QTreeWidgetItem:
        item = self._rows.get(session.torrent_hash)
        if item is None:
            item = QTreeWidgetItem()
            item.setData(0, Qt.UserRole, session.torrent_hash)
            self.table.addTopLevelItem(item)
            self._rows[session.torrent_hash] = item
        self._update_row(item, session)
        return item

    def _on_session_changed(self, session: TorrentSession) -> None:
        item = self._rows.get(session.torrent_hash)
        if item:
            self._update_row(item, session)

    def _update_row(self, item: QTreeWidgetItem, session: TorrentSession) -> None:
        item.setText(COL_NAME, session.display_name)
        item.setText(COL_SIZE, format_size(session.total_size) if session.total_size else "-")
        item.setData(COL_PROGRESS, PROGRESS_ROLE, session.progress)
        item.setText(COL_STATUS, session.state.value if not session.paused else "paused")
        item.setText(COL_DOWN, format_speed(session.download_speed) if not session.paused else "-")
        item.setText(COL_UP, format_speed(session.upload_speed) if not session.paused else "-")
        item.setText(COL_PEERS, str(session.num_peers))
        item.setText(COL_SEEDS, str(session.seeders))
        item.setText(COL_ETA, format_eta(session.eta_seconds))

    def _refresh(self) -> None:
        total_down = total_up = 0
        for session in self.engine.list_sessions():
            item = self._rows.get(session.torrent_hash)
            if item:
                self._update_row(item, session)
            if not session.paused:
                total_down += session.download_speed
                total_up += session.upload_speed
        self.table.viewport().update()
        self.status_label.setText(
            f"{len(self.engine.sessions)} torrents   "
            f"down {format_speed(total_down)}   up {format_speed(total_up)}   "
            f"port {self.engine.port}")
        self._update_detail()

    # ------------------------------------------------------------------
    # Detail panel
    def _selected_sessions(self):
        sessions = []
        for item in self.table.selectedItems():
            if item.columnCount() and self.table.indexOfTopLevelItem(item) >= 0:
                info_hash = item.data(0, Qt.UserRole)
                session = self.engine.sessions.get(info_hash)
                if session and session not in sessions:
                    sessions.append(session)
        return sessions

    def _update_detail(self) -> None:
        sessions = self._selected_sessions()
        if not sessions:
            self.general_label.setText("No torrent selected")
            self.trackers_tree.clear()
            self.peers_tree.clear()
            return
        session = sessions[0]
        self._fill_general(session)
        self._fill_trackers(session)
        self._fill_peers(session)

    def _fill_general(self, session: TorrentSession) -> None:
        lines = [f"<b>Name:</b> {session.display_name}",
                 f"<b>Info hash:</b> {session.torrent_hash.hex()}",
                 f"<b>State:</b> {session.state.value}"]
        torrent = session.torrent
        if torrent:
            lines += [
                f"<b>Size:</b> {format_size(torrent.total_size)}",
                f"<b>Pieces:</b> {torrent.num_pieces} x {format_size(torrent.piece_length)}",
                f"<b>Files:</b> {len(torrent.files)}",
                f"<b>Save folder:</b> {session.save_dir}",
                f"<b>Downloaded:</b> {format_size(session.piece_manager.bytes_complete) if session.piece_manager else '0 B'}",
                f"<b>Uploaded:</b> {format_size(session.uploaded)}",
            ]
            if torrent.comment:
                lines.append(f"<b>Comment:</b> {torrent.comment}")
            if torrent.created_by:
                lines.append(f"<b>Created by:</b> {torrent.created_by}")
        else:
            lines.append("<i>Fetching metadata from peers...</i>")
        self.general_label.setText("<br>".join(lines))

    def _fill_trackers(self, session: TorrentSession) -> None:
        self.trackers_tree.clear()
        tiers = session.torrent.trackers if session.torrent else (
            [[t] for t in session.magnet.trackers] if session.magnet else [])
        for tier_index, tier in enumerate(tiers):
            for url in tier:
                QTreeWidgetItem(self.trackers_tree, [url, str(tier_index)])

    def _fill_peers(self, session: TorrentSession) -> None:
        self.peers_tree.clear()
        for peer in list(session.peers.values()):
            QTreeWidgetItem(self.peers_tree, [
                f"{peer.address[0]}:{peer.address[1]}",
                peer.client_name or "-",
                format_size(peer.downloaded),
                format_size(peer.uploaded),
                str(len(peer.peer_pieces)),
            ])

    def _show_context_menu(self, pos) -> None:
        if not self.table.itemAt(pos):
            return
        menu = QMenu(self)
        menu.addAction(self.resume_action)
        menu.addAction(self.pause_action)
        menu.addSeparator()
        copy_magnet = menu.addAction("Copy magnet link")
        menu.addSeparator()
        menu.addAction(self.remove_action)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is copy_magnet:
            self._copy_magnet()

    def _copy_magnet(self) -> None:
        sessions = self._selected_sessions()
        if not sessions:
            return
        session = sessions[0]
        magnet = (session.torrent.magnet_link() if session.torrent
                  else f"magnet:?xt=urn:btih:{session.torrent_hash.hex()}")
        QApplication.clipboard().setText(magnet)
        self.status_label.setText("Magnet link copied to clipboard")

    # ------------------------------------------------------------------
    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "BruvTorrent", message)

    async def _shutdown_and_quit(self) -> None:
        await self.engine.shutdown()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        # qasync keeps the event loop running after the window closes, so the
        # process would linger headless. Shut the engine down, then quit.
        self.timer.stop()
        self._persist_torrents()
        asyncio.ensure_future(self._shutdown_and_quit())
        event.accept()
