"""Engine: owns the shared peer id / listen port, all torrent sessions, and
the incoming-connection listener used for seeding."""
import asyncio
import logging
import os
import random
from typing import Callable, Dict, List, Optional

from src.core.peer import (HANDSHAKE_LEN, PeerConnection, build_handshake,
                           parse_handshake)
from src.core.session import TorrentSession
from src.core.torrent import MagnetLink, Torrent

logger = logging.getLogger('engine')

CLIENT_PREFIX = b'-BV0100-'  # BruvTorrent 1.0.0 in Azureus style


class Engine:
    def __init__(self, save_dir: str, port: int = 6881):
        self.save_dir = save_dir
        self.preferred_port = port
        self.port = port
        self.peer_id = self._generate_peer_id()
        self.sessions: Dict[bytes, TorrentSession] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._change_cb: Optional[Callable[[TorrentSession], None]] = None

    @staticmethod
    def _generate_peer_id() -> bytes:
        suffix = bytes(random.randint(0, 255) for _ in range(12))
        return CLIENT_PREFIX + suffix

    def set_change_callback(self, cb: Callable[[TorrentSession], None]) -> None:
        self._change_cb = cb

    def notify_changed(self, session: TorrentSession) -> None:
        if self._change_cb:
            self._change_cb(session)

    # ------------------------------------------------------------------
    async def start_listener(self) -> None:
        for candidate in [self.preferred_port] + list(range(6882, 6892)):
            try:
                self._server = await asyncio.start_server(
                    self._handle_incoming, host='0.0.0.0', port=candidate)
                self.port = candidate
                logger.info("listening for peers on port %d", candidate)
                return
            except OSError:
                continue
        logger.warning("could not bind a listen port; running leech-only")

    async def _handle_incoming(self, reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter) -> None:
        try:
            data = await asyncio.wait_for(
                reader.readexactly(HANDSHAKE_LEN), timeout=10)
            reserved, info_hash, _ = parse_handshake(data)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError,
                ConnectionError, OSError):
            writer.close()
            return

        session = self.sessions.get(info_hash)
        if session is None:
            writer.close()
            return

        writer.write(build_handshake(info_hash, self.peer_id))
        try:
            await writer.drain()
        except OSError:
            writer.close()
            return

        address = writer.get_extra_info('peername') or ('?', 0)
        peer = PeerConnection(session, (address[0], address[1]))
        if not session.adopt_incoming(peer):
            writer.close()
            return
        await peer.run_incoming(reader, writer, reserved)

    # ------------------------------------------------------------------
    async def add_torrent_file(self, path: str) -> TorrentSession:
        torrent = Torrent.from_file(path)
        return await self._add(TorrentSession(self, torrent, None, self.save_dir))

    async def add_magnet(self, uri: str) -> TorrentSession:
        magnet = MagnetLink.parse(uri)
        return await self._add(TorrentSession(self, None, magnet, self.save_dir))

    async def _add(self, session: TorrentSession) -> TorrentSession:
        if session.torrent_hash in self.sessions:
            return self.sessions[session.torrent_hash]
        self.sessions[session.torrent_hash] = session
        await session.start()
        return session

    async def remove(self, info_hash: bytes, delete_data: bool = False) -> None:
        session = self.sessions.pop(info_hash, None)
        if session is None:
            return
        await session.stop()
        if delete_data and session.torrent:
            self._delete_files(session)

    @staticmethod
    def _delete_files(session: TorrentSession) -> None:
        if not session.torrent:
            return
        for tfile in session.torrent.files:
            full = os.path.join(session.save_dir, tfile.path)
            try:
                if os.path.exists(full):
                    os.remove(full)
            except OSError as exc:
                logger.warning("could not delete %s: %s", full, exc)

    async def shutdown(self) -> None:
        await asyncio.gather(
            *(s.stop() for s in self.sessions.values()), return_exceptions=True)
        self.sessions.clear()
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except OSError:
                pass

    def list_sessions(self) -> List[TorrentSession]:
        return list(self.sessions.values())
