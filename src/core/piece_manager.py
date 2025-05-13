import asyncio
import hashlib
import logging
import os
from typing import Dict, List, Optional, Tuple

from src.core.torrent import Torrent

class Block:
    def __init__(self, piece: int, offset: int, length: int):
        self.piece = piece
        self.offset = offset
        self.length = length
        self.data: Optional[bytes] = None
        self.status = Block.MISSING

    MISSING = 0
    PENDING = 1
    RETRIEVED = 2

class Piece:
    def __init__(self, index: int, blocks: List[Block], hash_value: bytes):
        self.index = index
        self.blocks = blocks
        self.hash = hash_value
        self.is_complete = False

class PieceManager:
    def __init__(self, torrent: Torrent):
        self.torrent = torrent
        self.peers = {}
        self.pending_blocks = []
        self.missing_blocks = []
        self.completed_pieces = []
        self.max_pending_time = 300  # 5 minutes
        self.missing_pieces = self._initiate_pieces()
        self.total_pieces = len(torrent.pieces)
        self.fd = None
        self.logger = logging.getLogger('piece_manager')
        self.data_dir = "downloads"
        os.makedirs(self.data_dir, exist_ok=True)
        self.file = os.path.join(self.data_dir, self.torrent.output_file)

    def _initiate_pieces(self) -> List[Piece]:
        pieces = []
        total_pieces = len(self.torrent.pieces)
        std_piece_blocks = self._create_blocks(total_pieces - 1, self.torrent.piece_length)

        # All pieces except last are of the same size
        for index, hash_value in enumerate(self.torrent.pieces):
            if index < total_pieces - 1:
                blocks = std_piece_blocks
            else:
                last_piece_length = self.torrent.total_size % self.torrent.piece_length
                blocks = self._create_blocks(index, last_piece_length)

            pieces.append(Piece(index, blocks, hash_value))

        return pieces

    def _create_blocks(self, piece_index: int, piece_length: int) -> List[Block]:
        blocks = []
        num_blocks = piece_length // self.torrent.block_length
        if piece_length % self.torrent.block_length:
            num_blocks += 1

        for i in range(num_blocks):
            offset = i * self.torrent.block_length
            block_length = min(self.torrent.block_length, piece_length - offset)
            blocks.append(Block(piece_index, offset, block_length))

        return blocks

    def close(self):
        if self.fd:
            self.fd.close()

    async def block_received(self, piece_index: int, block_offset: int, data: bytes) -> None:
        for piece in self.missing_pieces:
            if piece.index == piece_index:
                for block in piece.blocks:
                    if block.offset == block_offset:
                        block.data = data
                        block.status = Block.RETRIEVED
                        await self._check_piece_completion(piece)
                        break
                break

    async def _check_piece_completion(self, piece: Piece) -> None:
        if all(block.status == Block.RETRIEVED for block in piece.blocks):
            if await self._validate_piece(piece):
                await self._write_piece(piece)
                self.missing_pieces.remove(piece)
                self.completed_pieces.append(piece)
                piece.is_complete = True
                self.logger.info(f"Piece {piece.index} completed")
            else:
                self.logger.warning(f"Piece {piece.index} failed validation, resetting")
                for block in piece.blocks:
                    block.status = Block.MISSING
                    block.data = None

    async def _validate_piece(self, piece: Piece) -> bool:
        piece_data = b''.join([block.data for block in piece.blocks])
        hashed_piece = hashlib.sha1(piece_data).digest()
        return hashed_piece == piece.hash

    async def _write_piece(self, piece: Piece) -> None:
        if not self.fd:
            mode = 'r+b' if os.path.exists(self.file) else 'wb'
            self.fd = open(self.file, mode)

        piece_data = b''.join([block.data for block in piece.blocks])
        for file in self.torrent.files:
            file_offset = piece.index * self.torrent.piece_length
            file_end = file_offset + len(piece_data)

            if file['length'] <= file_offset:
                continue  # This piece is for a later file

            if file_offset < file['length']:
                self.fd.seek(file['offset'] + file_offset)
                data_to_write = piece_data[:min(len(piece_data), file['length'] - file_offset)]
                self.fd.write(data_to_write)
                piece_data = piece_data[len(data_to_write):]

                if not piece_data:
                    break

        self.fd.flush()

    def next_request(self, peer_bitfield: List[int]) -> Optional[Block]:
        if not peer_bitfield:
            return None

        for piece in self.missing_pieces:
            if not peer_bitfield[piece.index]:
                continue

            for block in piece.blocks:
                if block.status == Block.MISSING:
                    block.status = Block.PENDING
                    return block

        return None

    def get_peer_progress(self, peer_id: str) -> float:
        if peer_id not in self.peers:
            return 0.0
        return self.peers[peer_id]['progress']

    def update_peer_progress(self, peer_id: str, bitfield: bytes) -> None:
        total_pieces = len(bitfield) * 8
        completed = sum(bin(b).count('1') for b in bitfield)
        progress = completed / total_pieces if total_pieces > 0 else 0
        self.peers[peer_id] = {'bitfield': bitfield, 'progress': progress}

    def get_completion(self) -> float:
        downloaded = sum(piece.is_complete for piece in self.completed_pieces)
        return downloaded / self.total_pieces if self.total_pieces > 0 else 0