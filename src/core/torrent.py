import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple, Union
import urllib.parse

try:
    import bencodepy
except ImportError:
    import bencode as bencodepy

class Torrent:
    def __init__(self, path: str):
        self.path = path
        self.total_size: int = 0
        self.piece_length: int = 0
        self.pieces: List[bytes] = []
        self.announce: str = ''
        self.info_hash: bytes = b''
        self.block_length: int = 2**14  # 16KB standard block size
        self.files: List[Dict] = []
        self.output_file: str = ''
        self._parse()

    def _parse(self) -> None:
        with open(self.path, 'rb') as f:
            data = bencodepy.decode(f.read())

        self.announce = data.get(b'announce', b'').decode('utf-8')
        info = data[b'info']

        # Calculate info hash
        encoded_info = bencodepy.encode(info)
        self.info_hash = hashlib.sha1(encoded_info).digest()

        self.piece_length = info[b'piece length']
        pieces = info[b'pieces']
        self.pieces = [pieces[i:i+20] for i in range(0, len(pieces), 20)]

        if b'files' in info:  # Multi-file torrent
            self._parse_multi_file(info)
        else:  # Single file torrent
            self._parse_single_file(info)

    def _parse_single_file(self, info: Dict) -> None:
        self.output_file = info[b'name'].decode('utf-8')
        file_length = info[b'length']
        self.total_size = file_length
        self.files = [{
            'path': self.output_file,
            'length': file_length,
            'offset': 0
        }]

    def _parse_multi_file(self, info: Dict) -> None:
        directory = info[b'name'].decode('utf-8')
        self.output_file = directory
        offset = 0

        for file_info in info[b'files']:
            file_path = os.path.join(directory, *[p.decode('utf-8') for p in file_info[b'path']])
            file_length = file_info[b'length']
            self.files.append({
                'path': file_path,
                'length': file_length,
                'offset': offset
            })
            offset += file_length

        self.total_size = offset

    @property
    def is_multi_file(self) -> bool:
        return len(self.files) > 1

    def get_announce_list(self) -> List[str]:
        """Returns list of backup trackers if available"""
        try:
            with open(self.path, 'rb') as f:
                data = bencodepy.decode(f.read())
            if b'announce-list' in data:
                return [url.decode('utf-8') for tier in data[b'announce-list'] for url in tier]
        except:
            return []
        return []

    def get_comment(self) -> Optional[str]:
        """Returns torrent comment if available"""
        try:
            with open(self.path, 'rb') as f:
                data = bencodepy.decode(f.read())
            return data.get(b'comment', b'').decode('utf-8') or None
        except:
            return None

    def get_created_by(self) -> Optional[str]:
        """Returns torrent creator if available"""
        try:
            with open(self.path, 'rb') as f:
                data = bencodepy.decode(f.read())
            return data.get(b'created by', b'').decode('utf-8') or None
        except:
            return None

    def get_creation_date(self) -> Optional[int]:
        """Returns torrent creation date timestamp if available"""
        try:
            with open(self.path, 'rb') as f:
                data = bencodepy.decode(f.read())
            return data.get(b'creation date', None)
        except:
            return None

    def get_magnet_link(self) -> str:
        """Generates a magnet link for the torrent"""
        xt = f"urn:btih:{self.info_hash.hex()}"
        dn = urllib.parse.quote(self.output_file)
        tr = "&tr=" + "&tr=".join(urllib.parse.quote(tracker) for tracker in self.get_announce_list())
        return f"magnet:?xt={xt}&dn={dn}{tr}"