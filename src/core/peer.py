import asyncio
import logging
import socket
import struct
import time
from typing import Optional, Tuple

from src.core.piece_manager import PieceManager
from src.utils.network_utils import check_firewall_permissions

class PeerConnection:
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
    MESSAGE_LENGTH = 4

    def __init__(self, peer_id: str, info_hash: bytes, piece_manager: PieceManager,
                 peer: Tuple[str, int], timeout: int = 30):
        self.peer_id = peer_id
        self.info_hash = info_hash
        self.piece_manager = piece_manager
        self.peer = peer
        self.timeout = timeout
        self.writer: Optional[asyncio.StreamWriter] = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.bitfield = []
        self.connected = False
        self.choked = True
        self.peer_choked = True
        self.interested = False
        self.peer_interested = False
        self.logger = logging.getLogger('peer')
        self.last_activity = time.time()

    async def connect(self) -> bool:
        """Establish connection with peer including handshake and bitfield exchange"""
        try:
            # First attempt connection
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.peer[0], self.peer[1]),
                    timeout=self.timeout
                )
            except (asyncio.TimeoutError, ConnectionRefusedError) as e:
                # If first attempt fails, check firewall
                self.logger.debug(f"Initial connection failed: {str(e)}")
                if not check_firewall_permissions(self.peer[0], self.peer[1]):
                    self.logger.warning("Firewall appears to be blocking connections")
                    # Don't return yet - try again in case it was a temporary issue

                # Second attempt
                try:
                    self.reader, self.writer = await asyncio.wait_for(
                        asyncio.open_connection(self.peer[0], self.peer[1]),
                        timeout=self.timeout
                    )
                except (asyncio.TimeoutError, ConnectionRefusedError) as e:
                    self.logger.warning(f"Persistent connection failure to {self.peer}: {str(e)}")
                    return False

            # Perform handshake
            if not await self._handshake():
                return False

            # Receive initial messages
            await self._receive_bitfield()
            self.connected = True
            self.last_activity = time.time()
            return True

        except Exception as e:
            self.logger.warning(f"Failed to connect to peer {self.peer}: {str(e)}")
            await self.close()
            return False

    async def _check_firewall_permissions(self) -> bool:
        """Verify firewall isn't blocking our connection"""
        try:
            return check_firewall_permissions(self.peer[0], self.peer[1])
        except Exception as e:
            self.logger.debug(f"Firewall check failed: {str(e)}")
            return True  # Continue anyway

    async def _check_firewall_permissions(self) -> bool:
        """Check if firewall might be blocking connections"""
        try:
            # Try a test connection
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(2)
            test_socket.connect((self.peer[0], self.peer[1]))
            test_socket.close()
            return True
        except socket.error as e:
            self.logger.warning(f"Firewall may be blocking connections to {self.peer}: {e}")
            # Here you would typically prompt the user to add firewall permission
            # For now we'll just log and continue
            return True  # Try anyway in case it's just the test that failed

    async def _handshake(self) -> bool:
        try:
            handshake = (
                    self.HANDSHAKE +
                    bytes(8) +  # Reserved bytes
                    self.info_hash +
                    self.peer_id.encode()
            )
            self.writer.write(handshake)
            await self.writer.drain()

            response = await asyncio.wait_for(
                self.reader.read(68),
                timeout=self.timeout
            )

            if len(response) != 68:
                self.logger.warning(f"Invalid handshake length from {self.peer}")
                return False

            if response[:20] != self.HANDSHAKE:
                self.logger.warning(f"Invalid handshake protocol from {self.peer}")
                return False

            if response[28:48] != self.info_hash:
                self.logger.warning(f"Invalid info hash from {self.peer}")
                return False

            return True

        except asyncio.TimeoutError:
            self.logger.warning(f"Handshake timeout with {self.peer}")
            return False
        except Exception as e:
            self.logger.warning(f"Handshake failed with {self.peer}: {str(e)}")
            return False

    async def _receive_bitfield(self) -> None:
        try:
            length = await self._read_message_length()
            if length == 0:
                return

            message_id = await self._read_message_id()
            if message_id != self.BITFIELD:
                self.logger.debug(f"Expected bitfield, got {message_id} from {self.peer}")
                return

            bitfield_bytes = await asyncio.wait_for(
                self.reader.read(length - 1),
                timeout=self.timeout
            )
            self.bitfield = self._parse_bitfield(bitfield_bytes)
            self.last_activity = time.time()

        except asyncio.TimeoutError:
            self.logger.warning(f"Bitfield receive timeout from {self.peer}")
            raise
        except Exception as e:
            self.logger.warning(f"Error receiving bitfield from {self.peer}: {str(e)}")
            raise

    async def receive_messages(self) -> None:
        while self.connected:
            try:
                if time.time() - self.last_activity > self.timeout:
                    self.logger.warning(f"Connection timeout with {self.peer}")
                    break

                length = await self._read_message_length()
                if length == 0:  # Keep-alive
                    self.last_activity = time.time()
                    continue

                message_id = await self._read_message_id()
                self.last_activity = time.time()

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
                self.logger.warning(f"Connection error with {self.peer}: {str(e)}")
                break
            except struct.error as e:
                self.logger.warning(f"Protocol error with {self.peer}: {str(e)}")
                break
            except Exception as e:
                self.logger.warning(f"Unexpected error with {self.peer}: {str(e)}")
                break

        self.connected = False
        await self.close()

    async def _handle_piece_message(self, length: int) -> None:
        try:
            piece_index = await self._read_piece_index()
            block_offset = await self._read_block_offset()
            block_data = await self._read_bytes(length - 8)

            if block_data:
                await self.piece_manager.block_received(
                    piece_index, block_offset, block_data
                )
        except Exception as e:
            self.logger.warning(f"Error handling piece message: {str(e)}")
            raise

    async def _read_message_length(self) -> int:
        data = await asyncio.wait_for(
            self.reader.read(self.MESSAGE_LENGTH),
            timeout=self.timeout
        )
        return struct.unpack('!I', data)[0] if data else 0

    async def _read_message_id(self) -> int:
        data = await asyncio.wait_for(
            self.reader.read(1),
            timeout=self.timeout
        )
        return struct.unpack('!B', data)[0] if data else -1

    async def _read_piece_index(self) -> int:
        data = await asyncio.wait_for(
            self.reader.read(4),
            timeout=self.timeout
        )
        return struct.unpack('!I', data)[0] if data else -1

    async def _read_block_offset(self) -> int:
        data = await asyncio.wait_for(
            self.reader.read(4),
            timeout=self.timeout
        )
        return struct.unpack('!I', data)[0] if data else -1

    async def _read_bytes(self, length: int) -> bytes:
        return await asyncio.wait_for(
            self.reader.read(length),
            timeout=self.timeout
        )

    def _parse_bitfield(self, bitfield: bytes) -> list:
        bits = []
        for byte in bitfield:
            for i in range(8):
                bits.append(byte >> (7 - i) & 1)
        return bits

    async def close(self) -> None:
        self.connected = False
        if self.writer:
            try:
                self.writer.close()
                await asyncio.wait_for(
                    self.writer.wait_closed(),
                    timeout=2
                )
            except Exception as e:
                self.logger.debug(f"Error closing connection: {str(e)}")