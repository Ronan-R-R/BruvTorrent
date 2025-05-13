import asyncio
import socket
import urllib.parse
import aiohttp
import struct
from typing import Dict, List, Tuple, Optional
from urllib.parse import urlparse

class Tracker:
    def __init__(self, torrent):
        self.torrent = torrent
        self.peer_id = self._generate_peer_id()
        self.http_timeout = 30

    async def get_peers(self) -> List[Tuple[str, int]]:
        if self.torrent.announce.startswith('http'):
            return await self._get_peers_from_http_tracker()
        elif self.torrent.announce.startswith('udp'):
            return await self._get_peers_from_udp_tracker()
        else:
            raise RuntimeError(f"Unsupported tracker protocol: {self.torrent.announce}")

    async def _get_peers_from_http_tracker(self) -> List[Tuple[str, int]]:
        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'uploaded': 0,
            'downloaded': 0,
            'port': 6881,
            'left': self.torrent.total_size,
            'compact': 1
        }

        url = self.torrent.announce + '?' + urllib.parse.urlencode(params)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.http_timeout)) as session:
            async with session.get(url) as response:
                if not response.status == 200:
                    raise ConnectionError(f"HTTP tracker response: {response.status}")
                data = await response.read()
                return self._decode_http_response(data)

    async def _get_peers_from_udp_tracker(self) -> List[Tuple[str, int]]:
        parsed = urlparse(self.torrent.announce)
        tracker_host, tracker_port = parsed.hostname, parsed.port

        # Create UDP connection
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.http_timeout)

        # Connection ID for UDP trackers (magic number)
        connection_id = 0x41727101980
        transaction_id = 12345  # Random ID

        # Connect request
        connect_payload = struct.pack('!QII', connection_id, 0, transaction_id)
        sock.sendto(connect_payload, (tracker_host, tracker_port))

        # Get connect response
        response = sock.recv(16)
        action, transaction_id, connection_id = struct.unpack('!IIQ', response)

        if action != 0 or transaction_id != transaction_id:
            raise ConnectionError("Invalid UDP tracker response")

        # Announce request
        announce_payload = struct.pack(
            '!QII20s20sQQQIIIiH',
            connection_id,
            1,  # announce
            transaction_id,
            self.torrent.info_hash,
            self.peer_id.encode(),
            0,  # downloaded
            self.torrent.total_size,  # left
            0,  # uploaded
            0,  # event (0=none)
            0,  # IP address (0=default)
            transaction_id,  # key
            -1,  # num_want (-1=default)
            6881  # port
        )
        sock.sendto(announce_payload, (tracker_host, tracker_port))

        # Get announce response
        response = sock.recv(1024)
        action, transaction_id, interval, leechers, seeders = struct.unpack('!IIIII', response[:20])
        peers = response[20:]

        if action != 1 or transaction_id != transaction_id:
            raise ConnectionError("Invalid UDP tracker announce response")

        # Parse peers (6 bytes per peer: 4 for IP, 2 for port)
        peers_list = []
        for i in range(0, len(peers), 6):
            ip = socket.inet_ntoa(peers[i:i+4])
            port = struct.unpack('!H', peers[i+4:i+6])[0]
            peers_list.append((ip, port))

        return peers_list

    def _decode_http_response(self, response: bytes) -> List[Tuple[str, int]]:
        try:
            import bencodepy
            decoded = bencodepy.decode(response)
        except ImportError:
            import bencode
            decoded = bencode.bdecode(response)

        if b'peers' not in decoded:
            raise ConnectionError("Invalid tracker response - no peers")

        peers = decoded[b'peers']
        if isinstance(peers, list):
            # Dictionary model
            return [(p[b'ip'].decode(), p[b'port']) for p in peers]
        else:
            # Binary model
            peers_list = []
            for i in range(0, len(peers), 6):
                ip = socket.inet_ntoa(peers[i:i+4])
                port = struct.unpack('!H', peers[i+4:i+6])[0]
                peers_list.append((ip, port))
            return peers_list

    def _generate_peer_id(self) -> str:
        import random
        import string
        return '-PC0001-' + ''.join(random.choices(string.digits, k=12))

    async def announce(self, uploaded: int, downloaded: int, left: int, event: str = '') -> List[Tuple[str, int]]:
        """Announce to tracker with current stats"""
        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': left,
            'port': 6881,
            'compact': 1
        }

        if event:
            params['event'] = event

        url = self.torrent.announce + '?' + urllib.parse.urlencode(params)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.http_timeout)) as session:
            async with session.get(url) as response:
                if not response.status == 200:
                    raise ConnectionError(f"Tracker announce failed: {response.status}")
                data = await response.read()
                return self._decode_http_response(data)