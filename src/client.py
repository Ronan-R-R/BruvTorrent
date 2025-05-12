import asyncio
import logging
import tracemalloc
from pathlib import Path
from typing import Dict, Optional
from src.torrent import TorrentMetadata
from src.ui import BitTorrentUI

# Start memory tracking
tracemalloc.start()


class BitTorrentClient:
    def __init__(self, download_dir: str = "downloads"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.torrents: Dict[str, TorrentMetadata] = {}
        self.ui = BitTorrentUI(self)
        self._setup_logging()
        self.active_downloads = set()

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
        """Add a torrent file to the client"""
        try:
            metadata = TorrentMetadata.from_file(Path(torrent_path))
            self.torrents[metadata.info_hash] = metadata
            self.ui.update_torrent_list(self.torrents)

            # Initialize progress display
            self.ui.update_torrent_progress(
                metadata.info_hash,
                progress=0,
                status="Ready",
                download_speed="0 KB/s",
                upload_speed="0 KB/s",
                peers=0
            )
            return True
        except Exception as e:
            self.ui.log_message(f"Error adding torrent: {e}")
            return False

    async def download_torrent(self, info_hash: str):
        """Handle actual torrent downloading"""
        if info_hash in self.active_downloads:
            return

        self.active_downloads.add(info_hash)
        try:
            torrent = self.torrents.get(info_hash)
            if not torrent:
                return

            # Update status
            self.ui.update_torrent_progress(info_hash, status="Downloading")

            # Simulate download progress (replace with actual implementation)
            for i in range(1, 101):
                if info_hash not in self.active_downloads:  # Check if paused/removed
                    break

                await asyncio.sleep(0.1)  # Simulate work
                progress = i
                download_speed = i * 100  # Simulated speed

                # Update UI
                self.ui.update_torrent_progress(
                    info_hash,
                    progress=progress,
                    download_speed=f"{download_speed} KB/s",
                    peers=5  # Simulated peers
                )

            if info_hash in self.active_downloads:
                self.ui.update_torrent_progress(info_hash, status="Completed")

        except Exception as e:
            self.ui.log_message(f"Download error: {e}")
            self.ui.update_torrent_progress(info_hash, status="Error")
        finally:
            self.active_downloads.discard(info_hash)

    async def pause_torrent(self, info_hash: str):
        """Pause a torrent download"""
        self.active_downloads.discard(info_hash)
        self.ui.update_torrent_progress(info_hash, status="Paused")

    async def remove_torrent(self, info_hash: str):
        """Remove a torrent"""
        self.active_downloads.discard(info_hash)
        self.torrents.pop(info_hash, None)
        self.ui.update_torrent_list(self.torrents)

    async def start(self):
        """Start the client UI"""
        await self.ui.start_ui()


if __name__ == "__main__":
    async def main():
        client = BitTorrentClient()
        await client.start()


    asyncio.run(main())