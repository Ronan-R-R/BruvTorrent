import os
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class TorrentFile:
    """Represents a single file in a torrent."""
    path: str
    length: int
    md5sum: Optional[str] = None


@dataclass
class TorrentMetadata:
    """Contains all metadata for a torrent."""
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
        """Parse a .torrent file into TorrentMetadata."""
        try:
            with open(torrent_path, 'rb') as f:
                data = cls._decode_bencode(f.read())
            return cls._parse_info(data)
        except Exception as e:
            logger.error(f"Failed to parse torrent file: {e}")
            raise

    @staticmethod
    def _decode_bencode(data: bytes) -> Dict[str, Any]:
        """Basic bencode decoder implementation."""
        # Simplified version - consider using a library like bencode.py for production
        if data.startswith(b'd'):
            return dict(TorrentMetadata._decode_dict(data[1:]))
        raise NotImplementedError("Full bencode parsing not implemented")

    @staticmethod
    def _parse_info(data: Dict[str, Any]) -> 'TorrentMetadata':
        """Extract info dictionary into TorrentMetadata."""
        info = data['info']
        info_hash = hashlib.sha1(str(info).encode()).digest()  # Simplified

        if 'files' in info:
            files = [
                TorrentFile(
                    path=os.path.join(*f['path']),
                    length=f['length'],
                    md5sum=f.get('md5sum')
                ) for f in info['files']
            ]
        else:
            files = [
                TorrentFile(
                    path=info['name'],
                    length=info['length'],
                    md5sum=info.get('md5sum')
                )
            ]

        return TorrentMetadata(
            announce=data['announce'],
            info_hash=info_hash,
            name=info['name'],
            files=files,
            piece_length=info['piece length'],
            pieces=[info['pieces'][i:i + 20] for i in range(0, len(info['pieces']), 20)],
            private=info.get('private', False),
            created_by=data.get('created by'),
            creation_date=data.get('creation date'),
            comment=data.get('comment')
        )