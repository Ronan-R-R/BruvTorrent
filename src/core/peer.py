import asyncio
import logging
import struct
import time
from typing import List, Optional, Tuple, Callable, Awaitable


class PeerConnection:
    """Handles peer communication for BitTorrent protocol"""

    # Protocol constants
    CHOKE = 0
    UNCHOKE = 1
    INTERESTED = 2
    NOT_INTERESTED = 3
    HAVE = 4
    BITFIELD = 5
    REQUEST = 6
    PIECE = 7
    CANCEL = 8
    PORT = 9
    HANDSHAKE = b'\x13BitTorrent protocol'
    RESERVED = bytes(8)
    MESSAGE_LENGTH = 4
    HANDSHAKE_SIZE = 68
    DEFAULT_BLOCK_SIZE = 2 ** 14  # 16KB

    def __init__(self,
                 peer_id: str,
                 info_hash: bytes,
                 peer: Tuple[str, int],
                 timeout: int = 30,
                 block_received_callback: Optional[Callable[[int, int, bytes], Awaitable[None]]] = None):
        """
        Initialize peer connection

        Args:
            peer_id: Our peer ID
            info_hash: Torrent info hash
            peer: Tuple of (ip, port)
            timeout: Connection timeout in seconds
            block_received_callback: Async callback when block is received (piece_index, block_offset, data)
        """
        self.peer_id = peer_id
        self.info_hash = info_hash
        self.peer = peer
        self.timeout = timeout
        self.block_received_cb = block_received_callback
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.bitfield: List[int] = []
        self.connected = False
        self.choked = True
        self.peer_choked = True
        self.interested = False
        self.peer_interested = False
        self.logger = logging.getLogger('peer')
        self.last_activity = time.time()

    async def connect(self) -> bool:
        """Establish connection and perform handshake"""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.peer[0], self.peer[1]),
                timeout=self.timeout
            )

            # Perform handshake
            handshake = (
                    self.HANDSHAKE +
                    self.RESERVED +
                    self.info_hash +
                    self.peer_id.encode()
            )
            self.writer.write(handshake)
            await self.writer.drain()

            # Verify handshake response
            response = await asyncio.wait_for(
                self.reader.read(self.HANDSHAKE_SIZE),
                timeout=self.timeout
            )

            if (len(response) != self.HANDSHAKE_SIZE or
                    not response.startswith(self.HANDSHAKE) or
                    response[28:48] != self.info_hash):
                raise ConnectionError("Invalid handshake response")

            # Get bitfield
            await self._receive_bitfield()
            self.connected = True
            return True

        except (asyncio.TimeoutError, ConnectionError, OSError) as e:
            self.logger.warning(f"Connection failed to {self.peer}: {e}")
            await self.close()
            return False

    async def _receive_bitfield(self) -> None:
        """Receive and process bitfield message"""
        length = await self._read_message_length()
        if length == 0:
            return

        message_id = await self._read_message_id()
        if message_id != self.BITFIELD:
            raise ConnectionError(f"Expected bitfield, got {message_id}")

        bitfield_bytes = await self._read_bytes(length - 1)
        self.bitfield = self._parse_bitfield(bitfield_bytes)

    def _parse_bitfield(self, bitfield: bytes) -> List[int]:
        """Convert bitfield bytes to list of bits"""
        return [byte >> (7 - i) & 1
                for byte in bitfield
                for i in range(8)]

    async def receive_messages(self) -> None:
        """Process incoming messages from peer"""
        while self.connected:
            try:
                length = await self._read_message_length()
                if length == 0:  # Keep-alive
                    continue

                message_id = await self._read_message_id()

                if message_id == self.CHOKE:
                    self.peer_choked = True
                elif message_id == self.UNCHOKE:
                    self.peer_choked = False
                elif message_id == self.INTERESTED:
                    self.peer_interested = True
                elif message_id == self.NOT_INTERESTED:
                    self.peer_interested = False
                elif message_id == self.HAVE:
                    piece_index = await self._read_piece_index()
                    if piece_index < len(self.bitfield):
                        self.bitfield[piece_index] = 1
                elif message_id == self.PIECE:
                    await self._handle_piece_message(length - 1)
                elif message_id == self.BITFIELD:
                    bitfield_bytes = await self._read_bytes(length - 1)
                    self.bitfield = self._parse_bitfield(bitfield_bytes)
                else:
                    await self._read_bytes(length - 1)  # Skip unknown messages

            except (ConnectionError, asyncio.IncompleteReadError) as e:
                self.logger.warning(f"Connection error: {e}")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error: {e}")
                break

        await self.close()

    async def _handle_piece_message(self, length: int) -> None:
        """Process incoming piece data"""
        piece_index = await self._read_piece_index()
        block_offset = await self._read_block_offset()
        block_data = await self._read_bytes(length - 8)

        if self.block_received_cb:
            await self.block_received_cb(piece_index, block_offset, block_data)

    # Helper methods for reading protocol messages
    async def _read_message_length(self) -> int:
        data = await self._read_bytes(self.MESSAGE_LENGTH)
        return struct.unpack('!I', data)[0]

    async def _read_message_id(self) -> int:
        data = await self._read_bytes(1)
        return struct.unpack('!B', data)[0]

    async def _read_piece_index(self) -> int:
        data = await self._read_bytes(4)
        return struct.unpack('!I', data)[0]

    async def _read_block_offset(self) -> int:
        data = await self._read_bytes(4)
        return struct.unpack('!I', data)[0]

    async def _read_bytes(self, length: int) -> bytes:
        """Read exactly length bytes with timeout"""
        data = await asyncio.wait_for(
            self.reader.read(length),
            timeout=self.timeout
        )
        if len(data) != length:
            raise ConnectionError(f"Expected {length} bytes, got {len(data)}")
        return data

    # Message sending methods
    async def send_interested(self) -> None:
        await self._send_message(self.INTERESTED)

    async def send_not_interested(self) -> None:
        await self._send_message(self.NOT_INTERESTED)

    async def send_unchoke(self) -> None:
        await self._send_message(self.UNCHOKE)

    async def send_request(self, piece_index: int, offset: int, length: int) -> None:
        message = struct.pack('!IBIII', 13, self.REQUEST, piece_index, offset, length)
        self.writer.write(message)
        await self.writer.drain()

    async def _send_message(self, message_id: int, payload: bytes = b'') -> None:
        """Send basic 1-byte message"""
        message = struct.pack('!IB', 1 + len(payload), message_id) + payload
        self.writer.write(message)
        await self.writer.drain()

    async def close(self) -> None:
        """Clean up connection"""
        self.connected = False
        if self.writer:
            self.writer.close()
            try:
                await asyncio.wait_for(
                    self.writer.wait_closed(),
                    timeout=1
                )
            except Exception:
                pass