"""Tracker communication: HTTP(S) (BEP 3) and UDP (BEP 15)."""
import asyncio
import logging
import random
import socket
import struct
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import urlparse

import aiohttp

from src.core import bencode

logger = logging.getLogger('tracker')

UDP_MAGIC = 0x41727101980
DEFAULT_INTERVAL = 1800
EVENT_CODES = {'': 0, 'completed': 1, 'started': 2, 'stopped': 3}


@dataclass
class AnnounceResult:
    peers: List[Tuple[str, int]] = field(default_factory=list)
    interval: int = DEFAULT_INTERVAL
    seeders: int = 0
    leechers: int = 0


class TrackerError(Exception):
    pass


class TrackerPool:
    """Announces across all tracker tiers, remembering which URL in each
    tier responded so it can be tried first next time (BEP 12)."""

    def __init__(self, tiers: List[List[str]], info_hash: bytes,
                 peer_id: bytes, port: int):
        self.tiers = [list(tier) for tier in tiers]
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.port = port
        self.http_timeout = 25

    async def announce(self, uploaded: int, downloaded: int, left: int,
                       event: str = '') -> AnnounceResult:
        merged = AnnounceResult(peers=[], interval=DEFAULT_INTERVAL)
        seen: set = set()
        any_ok = False

        for tier in self.tiers:
            for position, url in enumerate(tier):
                try:
                    result = await self._announce_one(
                        url, uploaded, downloaded, left, event)
                except (TrackerError, aiohttp.ClientError, asyncio.TimeoutError,
                        OSError, bencode.BencodeError) as exc:
                    logger.debug("tracker %s failed: %s", url, exc)
                    continue
                # Move the working tracker to the front of its tier.
                if position != 0:
                    tier.insert(0, tier.pop(position))
                any_ok = True
                for peer in result.peers:
                    if peer not in seen:
                        seen.add(peer)
                        merged.peers.append(peer)
                merged.interval = max(merged.interval, result.interval)
                merged.seeders = max(merged.seeders, result.seeders)
                merged.leechers = max(merged.leechers, result.leechers)
                break  # one success per tier is enough

        if not any_ok:
            raise TrackerError("all trackers failed")
        return merged

    async def _announce_one(self, url: str, uploaded: int, downloaded: int,
                            left: int, event: str) -> AnnounceResult:
        scheme = urlparse(url).scheme
        if scheme in ('http', 'https'):
            return await self._announce_http(url, uploaded, downloaded, left, event)
        if scheme == 'udp':
            return await self._announce_udp(url, uploaded, downloaded, left, event)
        raise TrackerError(f"unsupported tracker scheme: {scheme}")

    # ------------------------------------------------------------------
    async def _announce_http(self, url: str, uploaded: int, downloaded: int,
                             left: int, event: str) -> AnnounceResult:
        params = {
            'info_hash': self.info_hash,
            'peer_id': self.peer_id,
            'port': self.port,
            'uploaded': uploaded,
            'downloaded': downloaded,
            'left': left,
            'compact': 1,
            'numwant': 80,
        }
        if event:
            params['event'] = event
        query = urllib.parse.urlencode(params)
        full_url = f"{url}{'&' if '?' in url else '?'}{query}"

        timeout = aiohttp.ClientTimeout(total=self.http_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(full_url) as response:
                if response.status != 200:
                    raise TrackerError(f"HTTP {response.status}")
                body = await response.read()

        decoded = bencode.decode(body)
        if not isinstance(decoded, dict):
            raise TrackerError("malformed tracker response")
        if b'failure reason' in decoded:
            raise TrackerError(decoded[b'failure reason'].decode('utf-8', 'replace'))

        result = AnnounceResult()
        result.interval = decoded.get(b'interval', DEFAULT_INTERVAL)
        result.seeders = decoded.get(b'complete', 0)
        result.leechers = decoded.get(b'incomplete', 0)
        result.peers = _parse_peers(decoded.get(b'peers', b''))
        result.peers.extend(_parse_peers6(decoded.get(b'peers6', b'')))
        return result

    # ------------------------------------------------------------------
    async def _announce_udp(self, url: str, uploaded: int, downloaded: int,
                            left: int, event: str) -> AnnounceResult:
        parsed = urlparse(url)
        if not parsed.hostname or not parsed.port:
            raise TrackerError("malformed UDP tracker URL")
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _UdpTrackerProtocol(),
            remote_addr=(parsed.hostname, parsed.port))
        try:
            connection_id = await self._udp_connect(protocol, transport)
            return await self._udp_announce(
                protocol, transport, connection_id,
                uploaded, downloaded, left, event)
        finally:
            transport.close()

    async def _udp_connect(self, protocol: '_UdpTrackerProtocol',
                           transport) -> int:
        transaction_id = random.randint(0, 0xFFFFFFFF)
        request = struct.pack('!QII', UDP_MAGIC, 0, transaction_id)
        data = await protocol.exchange(transport, request, transaction_id)
        if len(data) < 16:
            raise TrackerError("short UDP connect response")
        action, txn, connection_id = struct.unpack('!IIQ', data[:16])
        if action != 0 or txn != transaction_id:
            raise TrackerError("bad UDP connect response")
        return connection_id

    async def _udp_announce(self, protocol: '_UdpTrackerProtocol', transport,
                            connection_id: int, uploaded: int, downloaded: int,
                            left: int, event: str) -> AnnounceResult:
        transaction_id = random.randint(0, 0xFFFFFFFF)
        key = random.randint(0, 0xFFFFFFFF)
        request = struct.pack(
            '!QII20s20sQQQIIIiH',
            connection_id, 1, transaction_id,
            self.info_hash, self.peer_id,
            downloaded, left, uploaded,
            EVENT_CODES.get(event, 0), 0, key, -1, self.port)
        data = await protocol.exchange(transport, request, transaction_id)
        if len(data) < 20:
            raise TrackerError("short UDP announce response")
        action, txn, interval, leechers, seeders = struct.unpack('!IIIII', data[:20])
        if action != 1 or txn != transaction_id:
            raise TrackerError("bad UDP announce response")
        result = AnnounceResult()
        result.interval = interval or DEFAULT_INTERVAL
        result.seeders = seeders
        result.leechers = leechers
        result.peers = _parse_peers(data[20:])
        return result


class _UdpTrackerProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self._futures: Dict[int, asyncio.Future] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) < 8:
            return
        txn = struct.unpack('!I', data[4:8])[0]
        future = self._futures.pop(txn, None)
        if future and not future.done():
            future.set_result(data)

    async def exchange(self, transport, request: bytes,
                       transaction_id: int, retries: int = 3) -> bytes:
        loop = asyncio.get_running_loop()
        for attempt in range(retries):
            future = loop.create_future()
            self._futures[transaction_id] = future
            transport.sendto(request)
            try:
                return await asyncio.wait_for(future, timeout=3 * (attempt + 1))
            except asyncio.TimeoutError:
                self._futures.pop(transaction_id, None)
        raise TrackerError("UDP tracker timed out")


def _parse_peers(raw) -> List[Tuple[str, int]]:
    """Handle both compact (bytes) and dictionary (list) peer models."""
    if isinstance(raw, list):
        peers = []
        for entry in raw:
            if isinstance(entry, dict) and b'ip' in entry and b'port' in entry:
                ip = entry[b'ip'].decode('utf-8', 'replace')
                peers.append((ip, entry[b'port']))
        return peers
    if not isinstance(raw, bytes):
        return []
    peers = []
    for i in range(0, len(raw) - 5, 6):
        ip = socket.inet_ntoa(raw[i:i + 4])
        port = struct.unpack('!H', raw[i + 4:i + 6])[0]
        if port:
            peers.append((ip, port))
    return peers


def _parse_peers6(raw) -> List[Tuple[str, int]]:
    if not isinstance(raw, bytes):
        return []
    peers = []
    for i in range(0, len(raw) - 17, 18):
        ip = socket.inet_ntop(socket.AF_INET6, raw[i:i + 16])
        port = struct.unpack('!H', raw[i + 16:i + 18])[0]
        if port:
            peers.append((ip, port))
    return peers
