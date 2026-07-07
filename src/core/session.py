"""Per-torrent session: tracker loop, peer pool, piece manager, metadata."""
import asyncio
import logging
import time
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from src.core.peer import PeerConnection
from src.core.piece_manager import PieceManager
from src.core.torrent import MagnetLink, Torrent
from src.core.tracker import TrackerError, TrackerPool

logger = logging.getLogger('session')

MAX_PEERS = 40
MAX_UPLOAD_SLOTS = 6
RECONNECT_DELAY = 30
SPEED_WINDOW = 5.0  # seconds for the rolling speed average


class State(str, Enum):
    METADATA = 'downloading metadata'
    CHECKING = 'checking'
    DOWNLOADING = 'downloading'
    SEEDING = 'seeding'
    PAUSED = 'paused'
    STOPPED = 'stopped'
    ERROR = 'error'


class TorrentSession:
    """Owns one torrent's lifecycle. Drives the tracker announce loop and a
    pool of peer connections. Works for both .torrent files and magnet links
    (metadata is fetched from peers first)."""

    def __init__(self, engine, torrent: Optional[Torrent],
                 magnet: Optional[MagnetLink], save_dir: str):
        if torrent is None and magnet is None:
            raise ValueError("session needs a torrent or a magnet")
        self.engine = engine
        self.torrent = torrent
        self.magnet = magnet
        self.save_dir = save_dir
        self.torrent_hash = torrent.info_hash if torrent else magnet.info_hash
        self.engine_peer_id = engine.peer_id

        self.piece_manager: Optional[PieceManager] = None
        self.peers: Dict[Tuple[str, int], PeerConnection] = {}
        self.known_addresses: Set[Tuple[str, int]] = set()
        self.paused = False
        self.state = State.METADATA if torrent is None else State.CHECKING
        self.error: Optional[str] = None

        self.uploaded = 0
        self.downloaded = 0
        self._down_samples: List[Tuple[float, int]] = []
        self._up_samples: List[Tuple[float, int]] = []
        self.download_speed = 0.0
        self.upload_speed = 0.0
        self.seeders = 0
        self.leechers = 0

        self._tasks: Set[asyncio.Task] = set()
        self._stopping = False
        self._tracker: Optional[TrackerPool] = None

    # ------------------------------------------------------------------
    @property
    def display_name(self) -> str:
        if self.torrent:
            return self.torrent.name
        if self.magnet and self.magnet.display_name:
            return self.magnet.display_name
        return self.torrent_hash.hex()

    @property
    def needs_metadata(self) -> bool:
        return self.torrent is None

    @property
    def total_size(self) -> int:
        return self.torrent.total_size if self.torrent else 0

    @property
    def progress(self) -> float:
        return self.piece_manager.progress if self.piece_manager else 0.0

    @property
    def num_peers(self) -> int:
        return len(self.peers)

    @property
    def eta_seconds(self) -> Optional[int]:
        if not self.piece_manager or self.download_speed <= 0 or self.paused:
            return None
        left = self.piece_manager.bytes_left
        if left <= 0:
            return 0
        return int(left / self.download_speed)

    # ------------------------------------------------------------------
    async def start(self) -> None:
        self._stopping = False
        self.paused = False
        if self.torrent is not None and self.piece_manager is None:
            await self._prepare_piece_manager()
        self._spawn(self._tracker_loop())
        self._spawn(self._peer_maintenance_loop())
        self._spawn(self._stats_loop())

    async def pause(self) -> None:
        self.paused = True
        self.state = State.PAUSED
        await self._announce_safe('stopped')
        await self._disconnect_all()
        self._cancel_tasks()

    async def resume(self) -> None:
        if not self.paused and self._tasks:
            return
        await self.start()

    async def stop(self) -> None:
        self._stopping = True
        await self._announce_safe('stopped')
        await self._disconnect_all()
        self._cancel_tasks()
        if self.piece_manager:
            self.piece_manager.close()
        self.state = State.STOPPED

    # ------------------------------------------------------------------
    async def _prepare_piece_manager(self) -> None:
        assert self.torrent is not None
        self.piece_manager = PieceManager(self.torrent, self.save_dir)
        self.state = State.CHECKING
        await self.piece_manager.verify_existing()
        self._tracker = TrackerPool(
            self.torrent.trackers, self.torrent_hash,
            self.engine_peer_id, self.engine.port)
        self.state = State.SEEDING if self.piece_manager.is_complete else State.DOWNLOADING

    async def on_metadata_received(self, raw_info: bytes) -> None:
        if self.torrent is not None:
            return
        try:
            trackers = self.magnet.trackers if self.magnet else []
            self.torrent = Torrent.from_metadata(raw_info, trackers, self.torrent_hash)
        except ValueError as exc:
            logger.warning("rejected metadata for %s: %s", self.torrent_hash.hex(), exc)
            return
        logger.info("metadata complete for %s", self.torrent.name)
        await self._prepare_piece_manager()
        self.engine.notify_changed(self)
        # Re-handshake bitfield-less peers already advertise pieces via HAVE.

    # ------------------------------------------------------------------
    # Tracker
    async def _tracker_loop(self) -> None:
        while not self._stopping and not self.paused:
            interval = await self._announce_safe('started' if not self.peers else '')
            await asyncio.sleep(max(60, min(interval, 1800)))

    async def _announce_safe(self, event: str) -> int:
        if self._tracker is None:
            return RECONNECT_DELAY
        manager = self.piece_manager
        left = manager.bytes_left if manager else self.total_size
        try:
            result = await self._tracker.announce(
                self.uploaded, self.downloaded, left, event)
        except TrackerError as exc:
            logger.debug("announce failed for %s: %s", self.display_name, exc)
            return RECONNECT_DELAY
        self.seeders = result.seeders
        self.leechers = result.leechers
        for address in result.peers:
            self.known_addresses.add(address)
        return result.interval

    # ------------------------------------------------------------------
    # Peers
    async def _peer_maintenance_loop(self) -> None:
        while not self._stopping and not self.paused:
            candidates = [a for a in self.known_addresses if a not in self.peers]
            for address in candidates:
                if len(self.peers) >= MAX_PEERS:
                    break
                self._spawn(self._connect_peer(address))
            self._recompute_state()
            await asyncio.sleep(3)

    async def _connect_peer(self, address: Tuple[str, int]) -> None:
        if address in self.peers or len(self.peers) >= MAX_PEERS:
            return
        peer = PeerConnection(self, address)
        self.peers[address] = peer  # reserve the slot before awaiting
        await peer.run_outgoing()

    def adopt_incoming(self, peer: PeerConnection) -> bool:
        if len(self.peers) >= MAX_PEERS or peer.address in self.peers:
            return False
        self.peers[peer.address] = peer
        return True

    def on_peer_connected(self, peer: PeerConnection) -> None:
        logger.debug("connected to %s (%s)", peer.address, peer.client_name)

    def on_peer_disconnected(self, peer: PeerConnection) -> None:
        self.downloaded += peer.downloaded
        if self.peers.get(peer.address) is peer:
            del self.peers[peer.address]

    async def on_piece_complete(self, piece: int) -> None:
        for peer in list(self.peers.values()):
            try:
                await peer.send_have(piece)
            except OSError:
                pass
        if self.piece_manager and self.piece_manager.is_complete:
            self.state = State.SEEDING
            await self._announce_safe('completed')
            self.engine.notify_changed(self)

    def may_unchoke(self, peer: PeerConnection) -> bool:
        active = sum(1 for p in self.peers.values() if not p.am_choking)
        return active < MAX_UPLOAD_SLOTS

    def on_bytes_uploaded(self, count: int) -> None:
        self.uploaded += count

    # ------------------------------------------------------------------
    # Stats
    async def _stats_loop(self) -> None:
        while not self._stopping and not self.paused:
            now = time.monotonic()
            down = self.downloaded + sum(p.downloaded for p in self.peers.values())
            up = self.uploaded
            self._down_samples.append((now, down))
            self._up_samples.append((now, up))
            self.download_speed = self._speed(self._down_samples, now)
            self.upload_speed = self._speed(self._up_samples, now)
            await asyncio.sleep(1)

    @staticmethod
    def _speed(samples: List[Tuple[float, int]], now: float) -> float:
        while len(samples) > 1 and now - samples[0][0] > SPEED_WINDOW:
            samples.pop(0)
        if len(samples) < 2:
            return 0.0
        dt = samples[-1][0] - samples[0][0]
        db = samples[-1][1] - samples[0][1]
        return db / dt if dt > 0 else 0.0

    def _recompute_state(self) -> None:
        if self.paused or self._stopping:
            return
        if self.needs_metadata:
            self.state = State.METADATA
        elif self.piece_manager and self.piece_manager.is_complete:
            self.state = State.SEEDING
        else:
            self.state = State.DOWNLOADING

    # ------------------------------------------------------------------
    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _cancel_tasks(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()

    async def _disconnect_all(self) -> None:
        peers = list(self.peers.values())
        await asyncio.gather(*(p.close() for p in peers), return_exceptions=True)
        self.peers.clear()
