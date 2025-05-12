import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List
from .torrent import TorrentMetadata
from .ui import BitTorrentUI

class BitTorrentClient:
    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir).absolute()
        self.download_dir.mkdir(exist_ok=True)
        self.torrents: Dict[bytes, TorrentMetadata] = {}
        self.active_downloads: Dict[bytes, List] = {}
        self.ui = BitTorrentUI(self)
        self._setup_logging()

    async def add_torrent(self, torrent_path: str) -> bool:
        try:
            metadata = TorrentMetadata.from_file(Path(torrent_path))
            if metadata.info_hash in self.torrents:
                logging.warning(f"Torrent already added: {metadata.name}")
                return False

            self.torrents[metadata.info_hash] = metadata
            self._init_download(metadata)
            self.ui.update_torrent_list()
            return True
        except Exception as e:
            logging.error(f"Error adding torrent: {e}")
            return False

    def _init_download(self, metadata: TorrentMetadata):
        """Initialize download structures"""
        self.active_downloads[metadata.info_hash] = {
            'downloaded': 0,
            'total': sum(f.length for f in metadata.files),
            'pieces': [False] * len(metadata.pieces),
            'peers': []
        }

    async def _download_piece(self, peer, piece_index):
        """Core download logic for a single piece"""
        try:
            # Implement actual peer communication here
            piece_data = b''  # Replace with real data from peer
            self._verify_and_save_piece(piece_index, piece_data)
        except Exception as e:
            logging.error(f"Error downloading piece {piece_index}: {e}")

    def _verify_and_save_piece(self, piece_index: int, data: bytes):
        """Verify hash and save downloaded piece"""
        metadata = self._get_metadata_by_piece(piece_index)
        if hashlib.sha1(data).digest() == metadata.pieces[piece_index]:
            self._write_piece_to_file(piece_index, data)
            self.active_downloads[metadata.info_hash]['pieces'][piece_index] = True
            self._update_progress(metadata.info_hash)

    def run(self):
        """Start the application"""
        self.ui.mainloop()