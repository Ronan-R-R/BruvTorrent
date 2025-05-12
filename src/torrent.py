import os
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class TorrentFile:
    path: str
    length: int
    md5sum: Optional[str] = None


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
                data = cls._decode_bencode(f.read())
            return cls._parse_info(data)
        except Exception as e:
            logger.error(f"Failed to parse torrent file: {e}")
            raise

    @staticmethod
    def _decode_bencode(data: bytes) -> Dict[str, Any]:
        """Full bencode decoder implementation"""

        def decode(data, index=0):
            if data[index] == ord('d'):
                index += 1
                result = {}
                while data[index] != ord('e'):
                    key, index = decode(data, index)
                    value, index = decode(data, index)
                    result[key.decode()] = value
                index += 1
                return result, index
            elif data[index] == ord('l'):
                index += 1
                result = []
                while data[index] != ord('e'):
                    item, index = decode(data, index)
                    result.append(item)
                index += 1
                return result, index
            elif data[index] == ord('i'):
                index += 1
                end = data.index(ord('e'), index)
                num = int(data[index:end])
                index = end + 1
                return num, index
            else:
                colon = data.index(ord(':'), index)
                length = int(data[index:colon])
                index = colon + 1
                return data[index:index + length], index + length

        result, _ = decode(data)
        return result

    @staticmethod
    def _parse_info(data: Dict[str, Any]) -> 'TorrentMetadata':
        info = data['info']
        info_hash = hashlib.sha1(str(info).encode()).digest()

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