import hashlib

import pytest

from src.core import bencode


def make_torrent_bytes(name=b"test.bin", piece_length=16384,
                       data=b"A" * 40000, files=None):
    """Build a minimal valid single- or multi-file .torrent payload."""
    if files is None:
        pieces = b"".join(
            hashlib.sha1(data[i:i + piece_length]).digest()
            for i in range(0, len(data), piece_length))
        info = {
            b"name": name,
            b"piece length": piece_length,
            b"pieces": pieces,
            b"length": len(data),
        }
    else:
        blob = b"".join(content for _, content in files)
        pieces = b"".join(
            hashlib.sha1(blob[i:i + piece_length]).digest()
            for i in range(0, len(blob), piece_length))
        info = {
            b"name": name,
            b"piece length": piece_length,
            b"pieces": pieces,
            b"files": [{b"length": len(content), b"path": [fname]}
                       for fname, content in files],
        }
    meta = {
        b"announce": b"http://tracker.example/announce",
        b"announce-list": [[b"http://tracker.example/announce"],
                           [b"udp://backup.example:1337"]],
        b"comment": b"a test torrent",
        b"info": info,
    }
    return bencode.encode(meta), data, info


@pytest.fixture
def single_file_torrent(tmp_path):
    payload, data, info = make_torrent_bytes()
    path = tmp_path / "single.torrent"
    path.write_bytes(payload)
    return path, data, info
