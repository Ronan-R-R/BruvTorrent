import asyncio
import logging
import random
import struct
import urllib.parse
from typing import List, Tuple
import aiohttp
import bencodepy

logger = logging.getLogger(__name__)


class Tracker:
    def __init__(self, peer_id: bytes, port: int = 6881):
        self.peer_id = peer_id
        self.port = port
        self.http_timeout = aiohttp.ClientTimeout(total=10)
        self.udp_timeout = 10

    async def get_peers(self, torrent: 'TorrentMetadata') -> List[Tuple[str, int]]:
        """Contact tracker and return list of (ip, port) tuples"""
        try:
            if torrent.announce.startswith('http'):
                return await self._http_tracker(torrent)
            elif torrent.announce.startswith('udp'):
                return await self._udp_tracker(torrent)
            else:
                logger.warning(f"Unsupported tracker protocol: {torrent.announce}")
                return []
        except Exception as e:
            logger.error(f"Tracker error: {e}")
            return []

    async def _http_tracker(self, torrent: 'TorrentMetadata') -> List[Tuple[str, int]]:
        params = {
            'info_hash': torrent.info_hash,
            'peer_id': self.peer_id,
            'uploaded': 0,
            'downloaded': 0,
            'left': sum(f.length for f in torrent.files),
            'port': self.port,
            'compact': 1,
            'numwant': 50
        }

        async with aiohttp.ClientSession(timeout=self.http_timeout) as session:
            async with session.get(torrent.announce, params=params) as response:
                if response.status != 200:
                    raise ConnectionError(f"Tracker returned {response.status}")

                data = bencodepy.decode(await response.read())
                return self._parse_peers(data.get(b'peers', b''))

    async def _udp_tracker(self, torrent: 'TorrentMetadata') -> List[Tuple[str, int]]:
        url = urllib.parse.urlparse(torrent.announce)
        reader, writer = await asyncio.open_connection(url.hostname, url.port)

        try:
            # UDP connection ID
            transaction_id = random.randint(0, 0x7FFFFFFF)
            connect_msg = struct.pack(">QII", 0x41727101980, 0, transaction_id)
            writer.write(connect_msg)
            await writer.drain()

            # Get connection ID
            data = await asyncio.wait_for(reader.read(16), timeout=self.udp_timeout)
            if len(data) < 16:
                raise ConnectionError("Invalid UDP tracker response")

            action, transaction, connection_id = struct.unpack(">IIQ", data)

            # Announce request
            transaction_id = random.randint(0, 0x7FFFFFFF)
            announce_msg = struct.pack(
                ">QII20s20sQQQIIIiH",
                connection_id,
                1,  # announce
                transaction_id,
                torrent.info_hash,
                self.peer_id,
                0,  # downloaded
                sum(f.length for f in torrent.files),  # left
                0,  # uploaded
                0,  # event (0=none)
                0,  # IP address (0=default)
                -1,  # key
                50,  # num_want (-1=default)
                self.port
            )
            writer.write(announce_msg)
            await writer.drain()

            # Get peers
            data = await asyncio.wait_for(reader.read(4096), timeout=self.udp_timeout)
            return self._parse_peers(data[20:])  # Skip header
        finally:
            writer.close()
            await writer.wait_closed()

    def _parse_peers(self, peers_data: bytes) -> List[Tuple[str, int]]:
        """Parse compact peer list (ip:port)"""
        peers = []
        try:
            # Compact format (IP+port as 6 bytes each)
            for i in range(0, len(peers_data), 6):
                ip = '.'.join(str(b) for b in peers_data[i:i + 4])
                port = struct.unpack(">H", peers_data[i + 4:i + 6])[0]
                peers.append((ip, port))
        except struct.error:
            pass
        return peers