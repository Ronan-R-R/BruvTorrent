import asyncio
import hashlib
import logging
import os
import time
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.parse
import aiohttp
import bencodepy

from src.torrent import TorrentMetadata
from src.ui import BitTorrentUI
from src.peer import PeerConnection

logger = logging.getLogger(__name__)


class BitTorrentClient:
    def __init__(self, download_dir: str = None):
        # Set default download directory (Windows Downloads/BruvTorrent or fallback)
        self.download_dir = self._get_default_download_path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.torrents: Dict[str, TorrentMetadata] = {}
        self.peer_id = self._generate_peer_id()
        self.ui = BitTorrentUI(self)
        self.download_speeds: Dict[str, deque] = {}
        self.active_downloads = set()
        self._setup_logging()

    def _get_default_download_path(self, custom_path: str = None) -> Path:
        """Determine the appropriate download path"""
        if custom_path:
            return Path(custom_path)

        # Try Windows Downloads folder first
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            return downloads / "BruvTorrent"

        # Fallback to current directory
        return Path.cwd() / "BruvTorrent_Downloads"

    def _generate_peer_id(self) -> bytes:
        return b'-BR0001-' + os.urandom(12)

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.download_dir / 'bruvtorrent.log'),
                logging.StreamHandler()
            ]
        )

    def set_download_path(self, path: str) -> bool:
        """Set a new download location with validation"""
        try:
            new_path = Path(path)

            # Test if we can write to this location
            test_file = new_path / ".bruvtorrent_test"
            test_file.touch()
            test_file.unlink()

            # Create directory if it doesn't exist
            new_path.mkdir(parents=True, exist_ok=True)

            # Move existing downloads if any
            if self.download_dir.exists() and self.download_dir != new_path:
                for item in self.download_dir.iterdir():
                    if item.is_file():
                        item.rename(new_path / item.name)

            self.download_dir = new_path
            self.ui.log_message(f"Download location set to: {self.download_dir}")
            return True

        except Exception as e:
            self.ui.log_message(f"Failed to set download location: {e}")
            return False

    async def add_torrent(self, torrent_path: str) -> bool:
        """Add a torrent file to the client"""
        try:
            metadata = TorrentMetadata.from_file(Path(torrent_path))
            self.torrents[metadata.info_hash.hex()] = metadata

            # Initialize UI display
            self.ui.update_torrent_list(self.torrents)
            self.ui.update_torrent_progress(
                metadata.info_hash.hex(),
                progress=0,
                status="Ready",
                download_speed="0 B/s",
                upload_speed="0 B/s",
                peers=0
            )
            return True
        except Exception as e:
            self.ui.log_message(f"Error adding torrent: {e}")
            return False

    async def _get_peers(self, torrent: TorrentMetadata) -> List[Tuple[str, int]]:
        """Contact tracker and return list of (ip, port) tuples"""
        try:
            params = {
                'info_hash': torrent.info_hash,
                'peer_id': self.peer_id,
                'uploaded': '0',  # Ensure string values
                'downloaded': '0',
                'left': str(sum(f.length for f in torrent.files)),
                'port': '6881',
                'compact': '1',
                'numwant': '50'
            }

            # Convert bytes parameters to URL-safe strings
            encoded_params = []
            for k, v in params.items():
                if isinstance(v, bytes):
                    v = v.hex()  # Convert bytes to hex string
                encoded_params.append(f"{k}={urllib.parse.quote_plus(str(v))}")

            url = f"{torrent.announce}?{'&'.join(encoded_params)}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise ConnectionError(f"Tracker returned {response.status}")

                    data = bencodepy.decode(await response.read())
                    peers_data = data.get(b'peers', b'')

                    # Handle both binary and dictionary peer formats
                    if isinstance(peers_data, dict):
                        peers = []
                        for peer in peers_data.get(b'peers', []):
                            ip = peer.get(b'ip', b'').decode()
                            port = peer.get(b'port', 0)
                            if ip and port:
                                peers.append((ip, port))
                        return peers
                    else:
                        return self._parse_peers(peers_data)

        except Exception as e:
            logger.error(f"Tracker error: {e}")
            return []

    def _parse_peers(self, peers_data: bytes) -> List[Tuple[str, int]]:
        """Parse compact peer list (ip:port) with multiple format support"""
        peers = []

        # Handle binary format
        if isinstance(peers_data, bytes):
            try:
                for i in range(0, len(peers_data), 6):
                    if i + 6 > len(peers_data):
                        break
                    ip_bytes = peers_data[i:i + 4]
                    port_bytes = peers_data[i + 4:i + 6]
                    ip = '.'.join(str(b) for b in ip_bytes)
                    port = int.from_bytes(port_bytes, 'big')
                    peers.append((ip, port))
            except Exception:
                pass

        return peers

    async def _download_piece(self, peers: List[Tuple[str, int]],
                              torrent: TorrentMetadata,
                              piece_index: int,
                              piece_hash: bytes) -> Optional[bytes]:
        """Download a single piece from peers"""
        for peer_ip, peer_port in peers:
            try:
                peer = PeerConnection(
                    peer_ip, peer_port,
                    torrent.info_hash,
                    self.peer_id,
                    torrent.piece_length
                )
                if await peer.connect():
                    piece_data = await peer.download_piece(piece_index, piece_hash)
                    if piece_data and hashlib.sha1(piece_data).digest() == piece_hash:
                        return piece_data
            except Exception as e:
                logger.warning(f"Peer {peer_ip}:{peer_port} failed: {e}")
        return None

    async def _write_piece(self, torrent: TorrentMetadata,
                           piece_index: int,
                           data: bytes) -> int:
        """Write downloaded piece to appropriate files"""
        piece_start = piece_index * torrent.piece_length
        remaining_data = data
        bytes_written = 0

        for file in torrent.files:
            if piece_start >= file.length:
                piece_start -= file.length
                continue

            file_path = self.download_dir / file.path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'rb+' if file_path.exists() else 'wb') as f:
                f.seek(piece_start)
                chunk = remaining_data[:file.length - piece_start]
                f.write(chunk)
                bytes_written += len(chunk)

            remaining_data = remaining_data[file.length - piece_start:]
            piece_start = 0

            if not remaining_data:
                break

        return bytes_written

    def _calculate_speed(self, info_hash: str) -> float:
        """Calculate download speed in bytes/sec"""
        if info_hash not in self.download_speeds or len(self.download_speeds[info_hash]) < 2:
            return 0

        samples = self.download_speeds[info_hash]
        total_bytes = sum(b for _, b in samples)
        time_span = samples[-1][0] - samples[0][0]

        return total_bytes / time_span if time_span > 0 else 0

    def _format_speed(self, speed_bytes: float) -> str:
        """Convert bytes/sec to human-readable format"""
        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if speed_bytes < 1024:
                return f"{speed_bytes:.1f} {unit}"
            speed_bytes /= 1024
        return f"{speed_bytes:.1f} GB/s"

    async def download_torrent(self, info_hash: str):
        """Main download handler"""
        if info_hash in self.active_downloads:
            return

        self.active_downloads.add(info_hash)
        torrent = self.torrents.get(info_hash)
        if not torrent:
            return

        try:
            # Initialize speed tracking
            self.download_speeds[info_hash] = deque(maxlen=10)
            start_time = time.time()
            total_downloaded = 0

            # Get peers from tracker
            peers = await self._get_peers(torrent)
            if not peers:
                raise ConnectionError("No peers available")

            self.ui.update_torrent_progress(
                info_hash,
                peers=len(peers),
                status="Downloading"
            )

            # Download each piece
            for piece_index, piece_hash in enumerate(torrent.pieces):
                if info_hash not in self.active_downloads:
                    break

                piece_data = await self._download_piece(peers, torrent, piece_index, piece_hash)
                if not piece_data:
                    continue

                # Write to disk and track speed
                bytes_written = await self._write_piece(torrent, piece_index, piece_data)
                total_downloaded += bytes_written
                self.download_speeds[info_hash].append((time.time(), bytes_written))

                # Update UI
                progress = int((piece_index + 1) / len(torrent.pieces) * 100)
                speed = self._calculate_speed(info_hash)
                self.ui.update_torrent_progress(
                    info_hash,
                    progress=progress,
                    download_speed=self._format_speed(speed),
                    peers=len(peers)
                )

            if info_hash in self.active_downloads:
                elapsed = time.time() - start_time
                avg_speed = total_downloaded / elapsed if elapsed > 0 else 0
                self.ui.log_message(
                    f"Download completed: {total_downloaded / 1e6:.2f} MB "
                    f"at {self._format_speed(avg_speed)} average"
                )
                self.ui.update_torrent_progress(info_hash, status="Completed")

        except Exception as e:
            self.ui.log_message(f"Download failed: {e}")
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
        self.download_speeds.pop(info_hash, None)
        self.ui.update_torrent_list(self.torrents)

    async def start(self):
        """Start the client UI"""
        await self.ui.start_ui()


if __name__ == "__main__":
    async def main():
        client = BitTorrentClient()
        await client.start()


    asyncio.run(main())