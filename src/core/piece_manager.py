"""Piece/block bookkeeping and disk IO."""
import asyncio
import hashlib
import logging
import os
import time
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

from src.core.torrent import Torrent

BLOCK_SIZE = 16384
PENDING_TIMEOUT = 25.0   # seconds before a requested block is handed out again
ENDGAME_THRESHOLD = 32   # remaining blocks before duplicate requests are allowed

logger = logging.getLogger('piece_manager')

BlockRequest = Tuple[int, int, int]  # (piece index, offset, length)


class PieceManager:
    def __init__(self, torrent: Torrent, save_dir: str):
        self.torrent = torrent
        self.save_dir = save_dir
        self.have: Set[int] = set()
        # piece index -> {offset: data} for partially received pieces
        self._buffers: Dict[int, Dict[int, bytes]] = {}
        # (piece, offset) -> time requested
        self._pending: Dict[Tuple[int, int], float] = {}
        self._handles: Dict[str, object] = {}
        self._io_lock = asyncio.Lock()
        self._block_counts: List[int] = [
            (torrent.piece_size(i) + BLOCK_SIZE - 1) // BLOCK_SIZE
            for i in range(torrent.num_pieces)
        ]

    # ------------------------------------------------------------------
    # Progress
    @property
    def is_complete(self) -> bool:
        return len(self.have) == self.torrent.num_pieces

    @property
    def bytes_complete(self) -> int:
        return sum(self.torrent.piece_size(i) for i in self.have)

    @property
    def bytes_left(self) -> int:
        return self.torrent.total_size - self.bytes_complete

    @property
    def progress(self) -> float:
        if self.torrent.num_pieces == 0:
            return 0.0
        return len(self.have) / self.torrent.num_pieces

    @property
    def bitfield(self) -> bytes:
        num = self.torrent.num_pieces
        field = bytearray((num + 7) // 8)
        for index in self.have:
            field[index // 8] |= 0x80 >> (index % 8)
        return bytes(field)

    # ------------------------------------------------------------------
    # Request scheduling
    def block_length(self, piece: int, offset: int) -> int:
        return min(BLOCK_SIZE, self.torrent.piece_size(piece) - offset)

    def _blocks_of(self, piece: int) -> Iterator[Tuple[int, int]]:
        for i in range(self._block_counts[piece]):
            offset = i * BLOCK_SIZE
            yield offset, self.block_length(piece, offset)

    def remaining_block_count(self) -> int:
        count = 0
        for piece in range(self.torrent.num_pieces):
            if piece in self.have:
                continue
            received = self._buffers.get(piece, {})
            count += self._block_counts[piece] - len(received)
        return count

    def next_requests(self, peer_pieces: Set[int], count: int,
                      in_flight: Set[Tuple[int, int]]) -> List[BlockRequest]:
        """Pick up to `count` blocks to request from a peer.

        Prefers pieces already in progress so they finish sooner. Near the
        end, re-requests pending blocks (endgame) excluding ones this peer
        already has in flight.
        """
        now = time.monotonic()
        requests: List[BlockRequest] = []

        def try_piece(piece: int, allow_pending: bool) -> None:
            for offset, length in self._blocks_of(piece):
                if len(requests) >= count:
                    return
                if offset in self._buffers.get(piece, {}):
                    continue
                key = (piece, offset)
                if key in in_flight:
                    continue
                pending_at = self._pending.get(key)
                if pending_at is not None and not allow_pending \
                        and now - pending_at < PENDING_TIMEOUT:
                    continue
                self._pending[key] = now
                requests.append((piece, offset, length))

        in_progress = [p for p in self._buffers if p not in self.have and p in peer_pieces]
        fresh = [p for p in range(self.torrent.num_pieces)
                 if p in peer_pieces and p not in self.have and p not in self._buffers]

        for piece in in_progress + fresh:
            if len(requests) >= count:
                break
            try_piece(piece, allow_pending=False)

        if not requests and self.remaining_block_count() <= ENDGAME_THRESHOLD:
            for piece in in_progress:
                if len(requests) >= count:
                    break
                try_piece(piece, allow_pending=True)

        return requests

    def cancel_pending(self, blocks: Set[Tuple[int, int]]) -> None:
        """Return blocks to the pool when a peer disconnects."""
        for key in blocks:
            self._pending.pop(key, None)

    # ------------------------------------------------------------------
    # Data path
    async def on_block(self, piece: int, offset: int, data: bytes) -> Optional[bool]:
        """Store a received block.

        Returns True when the block completed a verified piece, False when
        the piece failed verification (and was reset), None otherwise.
        """
        if piece in self.have or piece >= self.torrent.num_pieces:
            return None
        if len(data) != self.block_length(piece, offset):
            logger.warning("piece %d: bad block length at offset %d", piece, offset)
            return None

        self._pending.pop((piece, offset), None)
        buffer = self._buffers.setdefault(piece, {})
        if offset in buffer:
            return None  # endgame duplicate
        buffer[offset] = data

        if len(buffer) < self._block_counts[piece]:
            return None

        # Piece complete: verify and write outside the event loop.
        del self._buffers[piece]
        piece_data = b''.join(buffer[o] for o in sorted(buffer))
        if hashlib.sha1(piece_data).digest() != self.torrent.piece_hashes[piece]:
            logger.warning("piece %d failed hash check, discarding", piece)
            for block_offset, _ in self._blocks_of(piece):
                self._pending.pop((piece, block_offset), None)
            return False

        async with self._io_lock:
            await asyncio.to_thread(self._write_piece, piece, piece_data)
        self.have.add(piece)
        return True

    async def read_block(self, piece: int, offset: int, length: int) -> Optional[bytes]:
        """Read a verified block from disk for upload."""
        if piece not in self.have:
            return None
        if offset + length > self.torrent.piece_size(piece) or length > 2 ** 17:
            return None
        start = piece * self.torrent.piece_length + offset
        async with self._io_lock:
            return await asyncio.to_thread(self._read_range, start, length)

    async def verify_existing(self, progress_cb: Optional[Callable[[float], None]] = None) -> None:
        """Hash-check data already on disk and mark complete pieces (resume)."""
        loop = asyncio.get_running_loop()
        num = self.torrent.num_pieces

        def check(piece: int) -> bool:
            start = piece * self.torrent.piece_length
            data = self._read_range(start, self.torrent.piece_size(piece))
            return hashlib.sha1(data).digest() == self.torrent.piece_hashes[piece]

        has_any_file = any(
            os.path.exists(os.path.join(self.save_dir, f.path))
            for f in self.torrent.files)
        if not has_any_file:
            return

        for piece in range(num):
            async with self._io_lock:
                if await loop.run_in_executor(None, check, piece):
                    self.have.add(piece)
            if progress_cb and (piece % 16 == 0 or piece == num - 1):
                progress_cb((piece + 1) / num)

    # ------------------------------------------------------------------
    # File layer (runs in worker threads; guarded by _io_lock)
    def _map_range(self, start: int, length: int) -> Iterator[Tuple[str, int, int]]:
        """Map a global byte range to (file path, file offset, chunk length)."""
        for tfile in self.torrent.files:
            file_end = tfile.offset + tfile.length
            if file_end <= start:
                continue
            if tfile.offset >= start + length:
                break
            chunk_start = max(start, tfile.offset)
            chunk_end = min(start + length, file_end)
            yield (os.path.join(self.save_dir, tfile.path),
                   chunk_start - tfile.offset,
                   chunk_end - chunk_start)

    def _open(self, path: str):
        handle = self._handles.get(path)
        if handle is None or handle.closed:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            mode = 'r+b' if os.path.exists(path) else 'w+b'
            handle = open(path, mode)
            self._handles[path] = handle
        return handle

    def _write_piece(self, piece: int, data: bytes) -> None:
        start = piece * self.torrent.piece_length
        consumed = 0
        for path, file_offset, chunk_len in self._map_range(start, len(data)):
            handle = self._open(path)
            handle.seek(file_offset)
            handle.write(data[consumed:consumed + chunk_len])
            handle.flush()
            consumed += chunk_len

    def _read_range(self, start: int, length: int) -> bytes:
        chunks: List[bytes] = []
        for path, file_offset, chunk_len in self._map_range(start, length):
            if not os.path.exists(path):
                chunks.append(b'\x00' * chunk_len)
                continue
            handle = self._open(path)
            handle.seek(file_offset)
            data = handle.read(chunk_len)
            if len(data) < chunk_len:
                data += b'\x00' * (chunk_len - len(data))
            chunks.append(data)
        return b''.join(chunks)

    def close(self) -> None:
        for handle in self._handles.values():
            try:
                handle.close()
            except OSError:
                pass
        self._handles.clear()
