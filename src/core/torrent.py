"""Torrent metadata: .torrent files, raw info dicts, and magnet links."""
import hashlib
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.core import bencode


@dataclass
class TorrentFile:
    path: str       # relative path inside the torrent (may contain subdirs)
    length: int
    offset: int     # byte offset within the whole torrent payload


class Torrent:
    """Parsed torrent metadata. Built from a .torrent file or a raw info
    dict received via ut_metadata (magnet links)."""

    def __init__(self) -> None:
        self.name: str = ''
        self.info_hash: bytes = b''
        self.raw_info: bytes = b''          # exact bencoded info dict, served via ut_metadata
        self.piece_length: int = 0
        self.piece_hashes: List[bytes] = []
        self.total_size: int = 0
        self.files: List[TorrentFile] = []
        self.trackers: List[List[str]] = []  # announce-list tiers
        self.private: bool = False
        self.comment: Optional[str] = None
        self.created_by: Optional[str] = None
        self.creation_date: Optional[int] = None
        self.source_path: Optional[str] = None  # original .torrent file, if any

    # ------------------------------------------------------------------
    @classmethod
    def from_file(cls, path: str) -> 'Torrent':
        with open(path, 'rb') as f:
            data = f.read()
        decoded = bencode.decode(data)
        if not isinstance(decoded, dict) or b'info' not in decoded:
            raise ValueError("not a valid torrent file: missing info dict")

        raw_info = _extract_raw_info(data)

        torrent = cls()
        torrent.source_path = path
        torrent._load_info(raw_info)
        torrent._load_trackers(decoded)

        if b'comment' in decoded:
            torrent.comment = _decode_text(decoded[b'comment'])
        if b'created by' in decoded:
            torrent.created_by = _decode_text(decoded[b'created by'])
        if isinstance(decoded.get(b'creation date'), int):
            torrent.creation_date = decoded[b'creation date']
        return torrent

    @classmethod
    def from_metadata(cls, raw_info: bytes, trackers: List[str],
                      expected_hash: Optional[bytes] = None) -> 'Torrent':
        torrent = cls()
        torrent._load_info(raw_info)
        if expected_hash and torrent.info_hash != expected_hash:
            raise ValueError("metadata info hash mismatch")
        if trackers:
            torrent.trackers = [[t] for t in trackers]
        return torrent

    # ------------------------------------------------------------------
    def _load_info(self, raw_info: bytes) -> None:
        info = bencode.decode(raw_info)
        if not isinstance(info, dict):
            raise ValueError("info dict is not a dict")

        self.raw_info = raw_info
        self.info_hash = hashlib.sha1(raw_info).digest()
        self.name = _decode_text(info[b'name'])
        self.piece_length = info[b'piece length']
        pieces = info[b'pieces']
        if len(pieces) % 20 != 0:
            raise ValueError("pieces field length is not a multiple of 20")
        self.piece_hashes = [pieces[i:i + 20] for i in range(0, len(pieces), 20)]
        self.private = info.get(b'private') == 1

        if b'files' in info:  # multi-file
            offset = 0
            for entry in info[b'files']:
                parts = [_sanitize_component(_decode_text(p)) for p in entry[b'path']]
                rel_path = os.path.join(_sanitize_component(self.name), *parts)
                length = entry[b'length']
                self.files.append(TorrentFile(rel_path, length, offset))
                offset += length
            self.total_size = offset
        else:  # single file
            length = info[b'length']
            self.files = [TorrentFile(_sanitize_component(self.name), length, 0)]
            self.total_size = length

        expected_pieces = (self.total_size + self.piece_length - 1) // self.piece_length
        if expected_pieces != len(self.piece_hashes):
            raise ValueError(
                f"piece count mismatch: {len(self.piece_hashes)} hashes "
                f"for {expected_pieces} pieces")

    def _load_trackers(self, decoded: Dict) -> None:
        tiers: List[List[str]] = []
        if b'announce-list' in decoded:
            for tier in decoded[b'announce-list']:
                urls = [_decode_text(u) for u in tier if u]
                if urls:
                    tiers.append(urls)
        if not tiers and decoded.get(b'announce'):
            tiers = [[_decode_text(decoded[b'announce'])]]
        self.trackers = tiers

    # ------------------------------------------------------------------
    @property
    def num_pieces(self) -> int:
        return len(self.piece_hashes)

    def piece_size(self, index: int) -> int:
        if index == self.num_pieces - 1:
            remainder = self.total_size % self.piece_length
            return remainder if remainder else self.piece_length
        return self.piece_length

    @property
    def is_multi_file(self) -> bool:
        return len(self.files) > 1

    @property
    def all_tracker_urls(self) -> List[str]:
        return [url for tier in self.trackers for url in tier]

    def magnet_link(self) -> str:
        parts = [f"magnet:?xt=urn:btih:{self.info_hash.hex()}",
                 f"dn={urllib.parse.quote(self.name)}"]
        parts.extend(f"tr={urllib.parse.quote(url)}" for url in self.all_tracker_urls)
        return '&'.join(parts)


@dataclass
class MagnetLink:
    info_hash: bytes
    display_name: str = ''
    trackers: List[str] = field(default_factory=list)

    @classmethod
    def parse(cls, uri: str) -> 'MagnetLink':
        if not uri.startswith('magnet:?'):
            raise ValueError("not a magnet URI")
        params = urllib.parse.parse_qs(uri[len('magnet:?'):])

        info_hash = b''
        for xt in params.get('xt', []):
            match = re.fullmatch(r'urn:btih:([0-9a-fA-F]{40})', xt)
            if match:
                info_hash = bytes.fromhex(match.group(1))
                break
            match = re.fullmatch(r'urn:btih:([A-Za-z2-7]{32})', xt)
            if match:
                import base64
                info_hash = base64.b32decode(match.group(1).upper())
                break
        if not info_hash:
            raise ValueError("magnet URI has no v1 btih hash")

        name = params.get('dn', [''])[0]
        trackers = params.get('tr', [])
        return cls(info_hash=info_hash, display_name=name, trackers=trackers)


def _extract_raw_info(data: bytes) -> bytes:
    """Return the exact bencoded slice of the top-level info value.

    The info hash must cover the bytes as they appear in the file, so the
    top-level dict is walked positionally instead of re-encoding.
    """
    if data[:1] != b'd':
        raise ValueError("torrent file does not start with a dict")
    index = 1
    while data[index:index + 1] != b'e':
        key, index = bencode.decode_from(data, index)
        start = index
        _, index = bencode.decode_from(data, index)
        if key == b'info':
            return data[start:index]
    raise ValueError("torrent file has no info dict")


def _decode_text(raw: bytes) -> str:
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('utf-8', errors='replace')


def _sanitize_component(name: str) -> str:
    """Strip path traversal and characters illegal in filenames."""
    name = name.replace('\\', '_').replace('/', '_')
    name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
    if name in ('', '.', '..'):
        name = '_'
    return name
