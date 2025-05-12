import asyncio
import hashlib
import logging
import random
import socket
import struct
from typing import Optional, Tuple

class PeerConnection:
    def __init__(self, ip: str, port: int, info_hash: bytes, peer_id: bytes):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.bitfield = bytearray()
        self.connected = False

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.ip, self.port)
            await self._handshake()
            self.connected = True
            return True
        except Exception as e:
            logging.error(f"Connection failed to {self.ip}:{self.port}: {e}")
            return False

    async def _handshake(self):
        handshake = (
            chr(19).encode() +
            b'BitTorrent protocol' +
            bytes(8) +
            self.info_hash +
            self.peer_id
        )
        self.writer.write(handshake)
        await self.writer.drain()

        response = await self.reader.read(68)
        if len(response) != 68:
            raise ConnectionError("Invalid handshake response")

    async def download_piece(self, piece_index: int, piece_hash: bytes) -> Optional[bytes]:
        if not self.connected:
            await self.connect()

        try:
            # Request the piece
            await self._send_interested()
            await self._request_piece(piece_index)

            # Receive data
            piece_data = await self._receive_piece(piece_index)
            if hashlib.sha1(piece_data).digest() != piece_hash:
                raise ValueError("Piece hash mismatch")

            return piece_data
        except Exception as e:
            logging.error(f"Failed to download piece {piece_index}: {e}")
            return None

    async def _send_interested(self):
        self.writer.write(struct.pack(">Ib", 1, 2))  # Interested message
        await self.writer.drain()

    async def _request_piece(self, piece_index: int):
        block_size = 2**14  # 16KB blocks
        num_blocks = (self.piece_length + block_size - 1) // block_size

        for block_offset in range(0, self.piece_length, block_size):
            block_length = min(block_size, self.piece_length - block_offset)
            message = struct.pack(
                ">IbIII",
                13,  # length
                6,   # request
                piece_index,
                block_offset,
                block_length
            )
            self.writer.write(message)
            await self.writer.drain()