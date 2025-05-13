import asyncio
import logging
import random
import struct
from typing import Dict, Optional, Tuple

from src.core.piece_manager import PieceManager

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

    async def connect(self) -> bool:
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.peer[0], self.peer[1]),
                timeout=self.timeout
            )
            await self._handshake()
            await self._receive_bitfield()
            self.connected = True
            return True
        except Exception as e:
            self.logger.warning(f"Failed to connect to peer {self.peer}: {e}")
            return False

    async def _handshake(self) -> None:
        handshake = (
            self.HANDSHAKE +
            bytes(8) +  # Reserved bytes
            self.info_hash +
            self.peer_id.encode()
        )
        self.writer.write(handshake)
        await self.writer.drain()

        response = await self.reader.read(68)
        if len(response) != 68:
            raise ConnectionError("Invalid handshake length")
        if response[:20] != self.HANDSHAKE:
            raise ConnectionError("Invalid handshake protocol")
        if response[28:48] != self.info_hash:
            raise ConnectionError("Invalid info hash")

    async def _receive_bitfield(self) -> None:
        length = await self._read_message_length()
        if length == 0:
            return

        message_id = await self._read_message_id()
        if message_id != self.BITFIELD:
            raise ConnectionError(f"Expected bitfield, got {message_id}")

        bitfield_bytes = await self.reader.read(length - 1)
        self.bitfield = self._parse_bitfield(bitfield_bytes)

    def _parse_bitfield(self, bitfield: bytes) -> list:
        bits = []
        for byte in bitfield:
            for i in range(8):
                bits.append(byte >> (7 - i) & 1)
        return bits

    async def _read_message_length(self) -> int:
        data = await self.reader.read(self.MESSAGE_LENGTH)
        return struct.unpack('!I', data)[0] if data else 0

    async def _read_message_id(self) -> int:
        data = await self.reader.read(1)
        return struct.unpack('!B', data)[0] if data else -1

    async def send_interested(self) -> None:
        message = struct.pack('!IB', 1, self.INTERESTED)
        self.writer.write(message)
        await self.writer.drain()
        self.interested = True

    async def send_not_interested(self) -> None:
        message = struct.pack('!IB', 1, self.NOT_INTERESTED)
        self.writer.write(message)
        await self.writer.drain()
        self.interested = False

    async def send_request(self, piece_index: int, block_offset: int, block_length: int) -> None:
        message = struct.pack(
            '!IBIII',
            13,
            self.REQUEST,
            piece_index,
            block_offset,
            block_length
        )
        self.writer.write(message)
        await self.writer.drain()

    async def send_unchoke(self) -> None:
        message = struct.pack('!IB', 1, self.UNCHOKE)
        self.writer.write(message)
        await self.writer.drain()
        self.choked = False

    async def send_have(self, piece_index: int) -> None:
        message = struct.pack('!IBI', 5, self.HAVE, piece_index)
        self.writer.write(message)
        await self.writer.drain()

    async def receive_messages(self) -> None:
        while self.connected:
            try:
                length = await self._read_message_length()
                if length == 0:
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
                    piece_index = struct.unpack('!I', await self.reader.read(4))[0]
                    self.bitfield[piece_index] = 1
                elif message_id == self.PIECE:
                    piece_index = struct.unpack('!I', await self.reader.read(4))[0]
                    block_offset = struct.unpack('!I', await self.reader.read(4))[0]
                    block_data = await self.reader.read(length - 9)
                    await self.piece_manager.block_received(
                        piece_index, block_offset, block_data
                    )
                elif message_id == self.BITFIELD:
                    bitfield_bytes = await self.reader.read(length - 1)
                    self.bitfield = self._parse_bitfield(bitfield_bytes)
                else:
                    await self.reader.read(length - 1)  # Skip unknown messages
            except (ConnectionError, asyncio.IncompleteReadError) as e:
                self.logger.warning(f"Connection error with peer {self.peer}: {e}")
                self.connected = False
                break

    async def close(self) -> None:
        self.connected = False
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()