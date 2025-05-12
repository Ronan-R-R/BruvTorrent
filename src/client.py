import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional
from src.torrent import TorrentMetadata
from src.ui import BitTorrentUI

class BitTorrentClient:
    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.torrents: Dict[str, TorrentMetadata] = {}
        self.ui = BitTorrentUI(self)
        self._setup_logging()

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('bruvtorrent.log'),
                logging.StreamHandler()
            ]
        )

    async def add_torrent(self, torrent_path: str) -> bool:
        try:
            metadata = TorrentMetadata.from_file(Path(torrent_path))
            self.torrents[metadata.info_hash] = metadata
            self.ui.update_torrent_list(self.torrents)
            return True
        except Exception as e:
            logging.error(f"Error adding torrent: {e}")
            return False

    async def start(self):
        self.ui.mainloop()

if __name__ == "__main__":
    client = BitTorrentClient()
    asyncio.run(client.start())