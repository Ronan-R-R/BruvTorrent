import os
import hashlib
import logging
import bencodepy
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

@dataclass
class TorrentFile:
    path: Path
    length: int
    md5sum: Optional[str] = None
    downloaded: bool = False

@dataclass
class TorrentMetadata:
    announce: str
    info_hash: bytes
    name: str
    files: List[TorrentFile]
    piece_length: int
    pieces: List[bytes]
    private: bool = False
    created_by: Optional[str] = None
    creation_date: Optional[int] = None
    comment: Optional[str] = None

    @classmethod
    def from_file(cls, torrent_path: Path) -> 'TorrentMetadata':
        try:
            with open(torrent_path, 'rb') as f:
                data = bencodepy.decode(f.read())
            return cls._parse_info(data)
        except Exception as e:
            logger.error(f"Failed to parse torrent file: {e}")
            raise

    @staticmethod
    def _parse_info(data: Dict[str, Any]) -> 'TorrentMetadata':
        info = data[b'info']
        info_hash = hashlib.sha1(bencodepy.encode(info)).digest()

        if b'files' in info:
            files = [
                TorrentFile(
                    path=Path(*[p.decode() for p in f[b'path']]),
                    length=f[b'length'],
                    md5sum=f.get(b'md5sum', b'').decode() or None
                ) for f in info[b'files']
            ]
        else:
            files = [
                TorrentFile(
                    path=Path(info[b'name'].decode()),
                    length=info[b'length'],
                    md5sum=info.get(b'md5sum', b'').decode() or None
                )
            ]

        return TorrentMetadata(
            announce=data[b'announce'].decode(),
            info_hash=info_hash,
            name=info[b'name'].decode(),
            files=files,
            piece_length=info[b'piece length'],
            pieces=[info[b'pieces'][i:i+20] for i in range(0, len(info[b'pieces']), 20)],
            private=info.get(b'private', 0) == 1,
            created_by=data.get(b'created by', b'').decode() or None,
            creation_date=data.get(b'creation date'),
            comment=data.get(b'comment', b'').decode() or None
        )