"""BitTorrent peer wire protocol (BEP 3) with extension protocol (BEP 10)
and metadata exchange (BEP 9)."""
import asyncio
import hashlib
import logging
import math
import struct
import time
from typing import TYPE_CHECKING, Dict, Optional, Set, Tuple

from src.core import bencode

if TYPE_CHECKING:
    from src.core.session import TorrentSession

logger = logging.getLogger('peer')

PROTOCOL = b'BitTorrent protocol'
HANDSHAKE_LEN = 68
EXTENSION_BIT_RESERVED = bytes([0, 0, 0, 0, 0, 0x10, 0, 0])

CHOKE, UNCHOKE, INTERESTED, NOT_INTERESTED = 0, 1, 2, 3
HAVE, BITFIELD, REQUEST, PIECE, CANCEL = 4, 5, 6, 7, 8
EXTENDED = 20
EXT_HANDSHAKE_ID = 0
OUR_UT_METADATA_ID = 3

METADATA_PIECE_SIZE = 16384
MAX_MESSAGE_SIZE = 4 * 1024 * 1024
PIPELINE_SIZE = 48
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 240
KEEPALIVE_INTERVAL = 100


def build_handshake(info_hash: bytes, peer_id: bytes) -> bytes:
    return (bytes([len(PROTOCOL)]) + PROTOCOL + EXTENSION_BIT_RESERVED
            + info_hash + peer_id)


def parse_handshake(data: bytes) -> Tuple[bytes, bytes, bytes]:
    """Returns (reserved, info_hash, peer_id). Raises on malformed data."""
    if len(data) != HANDSHAKE_LEN or data[0] != len(PROTOCOL) \
            or data[1:20] != PROTOCOL:
        raise ConnectionError("malformed handshake")
    return data[20:28], data[28:48], data[48:68]


class PeerConnection:
    def __init__(self, session: 'TorrentSession', address: Tuple[str, int]):
        self.session = session
        self.address = address
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False

        self.peer_pieces: Set[int] = set()
        self.in_flight: Set[Tuple[int, int]] = set()
        self.supports_extensions = False
        self.peer_ut_metadata_id = 0
        self.peer_metadata_size = 0
        self.client_name = ''

        self.downloaded = 0
        self.uploaded = 0
        self.connected_at = 0.0
        self.closed = False
        self._send_lock = asyncio.Lock()
        self._metadata_buffer: Dict[int, bytes] = {}
        self._last_keepalive = 0.0

    # ------------------------------------------------------------------
    # Connection setup
    async def run_outgoing(self) -> None:
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(*self.address), timeout=CONNECT_TIMEOUT)
            self.writer.write(build_handshake(
                self.session.torrent_hash, self.session.engine_peer_id))
            await self.writer.drain()
            response = await asyncio.wait_for(
                self.reader.readexactly(HANDSHAKE_LEN), timeout=CONNECT_TIMEOUT)
            reserved, info_hash, _ = parse_handshake(response)
            if info_hash != self.session.torrent_hash:
                raise ConnectionError("info hash mismatch")
            self.supports_extensions = bool(reserved[5] & 0x10)
            await self._after_handshake()
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionError) as exc:
            logger.debug("outgoing %s failed: %s", self.address, exc)
        finally:
            await self.close()

    async def run_incoming(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           peer_reserved: bytes) -> None:
        """Adopt a connection whose handshake the listener already consumed
        and answered."""
        self.reader, self.writer = reader, writer
        self.supports_extensions = bool(peer_reserved[5] & 0x10)
        try:
            await self._after_handshake()
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                ConnectionError) as exc:
            logger.debug("incoming %s dropped: %s", self.address, exc)
        finally:
            await self.close()

    async def _after_handshake(self) -> None:
        self.connected_at = time.monotonic()
        self._last_keepalive = time.monotonic()
        if self.supports_extensions:
            await self._send_extension_handshake()
        manager = self.session.piece_manager
        if manager and manager.have:
            await self._send_message(BITFIELD, manager.bitfield)
        self.session.on_peer_connected(self)
        await self._pump()

    # ------------------------------------------------------------------
    # Message pump
    async def _pump(self) -> None:
        while not self.closed:
            header = await asyncio.wait_for(
                self.reader.readexactly(4), timeout=READ_TIMEOUT)
            length = struct.unpack('!I', header)[0]
            if length == 0:
                await self._maybe_keepalive()
                continue
            if length > MAX_MESSAGE_SIZE:
                raise ConnectionError(f"oversized message: {length}")
            payload = await asyncio.wait_for(
                self.reader.readexactly(length), timeout=READ_TIMEOUT)
            await self._handle_message(payload[0], payload[1:])
            await self._maybe_keepalive()

    async def _handle_message(self, message_id: int, payload: bytes) -> None:
        if message_id == CHOKE:
            self.peer_choking = True
            self._return_in_flight()
        elif message_id == UNCHOKE:
            self.peer_choking = False
            await self._fill_pipeline()
        elif message_id == INTERESTED:
            self.peer_interested = True
            if self.session.may_unchoke(self):
                await self._set_choking(False)
        elif message_id == NOT_INTERESTED:
            self.peer_interested = False
        elif message_id == HAVE:
            (piece,) = struct.unpack('!I', payload)
            self.peer_pieces.add(piece)
            await self._update_interest()
            await self._fill_pipeline()
        elif message_id == BITFIELD:
            self._parse_bitfield(payload)
            await self._update_interest()
        elif message_id == REQUEST:
            await self._serve_request(payload)
        elif message_id == PIECE:
            await self._on_piece(payload)
        elif message_id == CANCEL:
            pass  # uploads are served immediately; nothing queued to cancel
        elif message_id == EXTENDED:
            await self._on_extended(payload)
        # unknown message ids are ignored per spec

    def _parse_bitfield(self, payload: bytes) -> None:
        for index in range(len(payload) * 8):
            if payload[index // 8] & (0x80 >> (index % 8)):
                self.peer_pieces.add(index)

    # ------------------------------------------------------------------
    # Download path
    async def _update_interest(self) -> None:
        manager = self.session.piece_manager
        if manager is None:
            return
        wants = any(p not in manager.have for p in self.peer_pieces)
        if wants and not self.am_interested:
            self.am_interested = True
            await self._send_message(INTERESTED)
        elif not wants and self.am_interested:
            self.am_interested = False
            await self._send_message(NOT_INTERESTED)

    async def _fill_pipeline(self) -> None:
        manager = self.session.piece_manager
        if (manager is None or self.peer_choking or not self.am_interested
                or self.session.paused):
            return
        want = PIPELINE_SIZE - len(self.in_flight)
        if want <= 0:
            return
        for piece, offset, length in manager.next_requests(
                self.peer_pieces, want, self.in_flight):
            self.in_flight.add((piece, offset))
            await self._send_message(
                REQUEST, struct.pack('!III', piece, offset, length))

    async def _on_piece(self, payload: bytes) -> None:
        if len(payload) < 8:
            return
        piece, offset = struct.unpack('!II', payload[:8])
        data = payload[8:]
        self.in_flight.discard((piece, offset))
        self.downloaded += len(data)
        manager = self.session.piece_manager
        if manager is None:
            return
        result = await manager.on_block(piece, offset, data)
        if result is True:
            await self.session.on_piece_complete(piece)
        await self._update_interest()
        await self._fill_pipeline()

    def _return_in_flight(self) -> None:
        manager = self.session.piece_manager
        if manager:
            manager.cancel_pending(self.in_flight)
        self.in_flight.clear()

    # ------------------------------------------------------------------
    # Upload path
    async def _set_choking(self, choking: bool) -> None:
        if self.am_choking != choking:
            self.am_choking = choking
            await self._send_message(CHOKE if choking else UNCHOKE)

    async def _serve_request(self, payload: bytes) -> None:
        if self.am_choking or len(payload) != 12:
            return
        piece, offset, length = struct.unpack('!III', payload)
        manager = self.session.piece_manager
        if manager is None:
            return
        data = await manager.read_block(piece, offset, length)
        if data is None:
            return
        await self._send_message(
            PIECE, struct.pack('!II', piece, offset) + data)
        self.uploaded += len(data)
        self.session.on_bytes_uploaded(len(data))

    async def send_have(self, piece: int) -> None:
        await self._send_message(HAVE, struct.pack('!I', piece))

    # ------------------------------------------------------------------
    # Extension protocol / metadata exchange
    async def _send_extension_handshake(self) -> None:
        payload: Dict[bytes, object] = {
            b'm': {b'ut_metadata': OUR_UT_METADATA_ID},
            b'v': b'BruvTorrent 1.0',
            b'reqq': 250,
        }
        torrent = self.session.torrent
        if torrent is not None:
            payload[b'metadata_size'] = len(torrent.raw_info)
        await self._send_message(
            EXTENDED, bytes([EXT_HANDSHAKE_ID]) + bencode.encode(payload))

    async def _on_extended(self, payload: bytes) -> None:
        if not payload:
            return
        ext_id = payload[0]
        if ext_id == EXT_HANDSHAKE_ID:
            try:
                info = bencode.decode(payload[1:])
            except bencode.BencodeError:
                return
            if not isinstance(info, dict):
                return
            mapping = info.get(b'm', {})
            if isinstance(mapping, dict):
                self.peer_ut_metadata_id = mapping.get(b'ut_metadata', 0) or 0
            size = info.get(b'metadata_size', 0)
            self.peer_metadata_size = size if isinstance(size, int) else 0
            version = info.get(b'v', b'')
            if isinstance(version, bytes):
                self.client_name = version.decode('utf-8', errors='replace')
            if self.session.needs_metadata and self.peer_ut_metadata_id \
                    and 0 < self.peer_metadata_size <= MAX_MESSAGE_SIZE * 4:
                await self._request_all_metadata()
        elif ext_id == OUR_UT_METADATA_ID:
            await self._on_ut_metadata(payload[1:])

    async def _request_all_metadata(self) -> None:
        pieces = math.ceil(self.peer_metadata_size / METADATA_PIECE_SIZE)
        for piece in range(pieces):
            await self._send_ut_metadata({b'msg_type': 0, b'piece': piece})

    async def _on_ut_metadata(self, payload: bytes) -> None:
        try:
            header, end = bencode.decode_from(payload, 0)
        except (bencode.BencodeError, IndexError):
            return
        if not isinstance(header, dict):
            return
        msg_type = header.get(b'msg_type')
        piece = header.get(b'piece')
        if not isinstance(piece, int):
            return

        if msg_type == 0:  # peer requests a metadata piece from us
            await self._serve_metadata_piece(piece)
        elif msg_type == 1 and self.session.needs_metadata:
            self._metadata_buffer[piece] = payload[end:]
            await self._try_assemble_metadata()
        # msg_type 2 (reject): nothing useful to do, another peer may serve it

    async def _serve_metadata_piece(self, piece: int) -> None:
        torrent = self.session.torrent
        if torrent is None or not self.peer_ut_metadata_id:
            if self.peer_ut_metadata_id:
                await self._send_ut_metadata({b'msg_type': 2, b'piece': piece})
            return
        raw = torrent.raw_info
        start = piece * METADATA_PIECE_SIZE
        if start >= len(raw):
            await self._send_ut_metadata({b'msg_type': 2, b'piece': piece})
            return
        chunk = raw[start:start + METADATA_PIECE_SIZE]
        await self._send_ut_metadata(
            {b'msg_type': 1, b'piece': piece, b'total_size': len(raw)}, chunk)

    async def _try_assemble_metadata(self) -> None:
        size = self.peer_metadata_size
        pieces = math.ceil(size / METADATA_PIECE_SIZE)
        if len(self._metadata_buffer) < pieces:
            return
        raw = b''.join(self._metadata_buffer[i] for i in range(pieces))[:size]
        self._metadata_buffer.clear()
        if hashlib.sha1(raw).digest() == self.session.torrent_hash:
            await self.session.on_metadata_received(raw)
        else:
            logger.warning("metadata from %s failed hash check", self.address)

    async def _send_ut_metadata(self, header: Dict, trailer: bytes = b'') -> None:
        await self._send_message(
            EXTENDED,
            bytes([self.peer_ut_metadata_id]) + bencode.encode(header) + trailer)

    # ------------------------------------------------------------------
    # Plumbing
    async def _send_message(self, message_id: int, payload: bytes = b'') -> None:
        if self.closed or self.writer is None:
            return
        async with self._send_lock:
            self.writer.write(
                struct.pack('!IB', 1 + len(payload), message_id) + payload)
            await self.writer.drain()

    async def _maybe_keepalive(self) -> None:
        now = time.monotonic()
        if now - self._last_keepalive >= KEEPALIVE_INTERVAL:
            self._last_keepalive = now
            if self.writer is not None:
                async with self._send_lock:
                    self.writer.write(struct.pack('!I', 0))
                    await self.writer.drain()

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._return_in_flight()
        if self.writer is not None:
            self.writer.close()
            try:
                await asyncio.wait_for(self.writer.wait_closed(), timeout=2)
            except (OSError, asyncio.TimeoutError):
                pass
        self.session.on_peer_disconnected(self)
