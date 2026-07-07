import hashlib

import pytest

from src.core import bencode
from src.core.torrent import MagnetLink, Torrent
from tests.conftest import make_torrent_bytes


def test_parse_single_file(single_file_torrent):
    path, data, info = single_file_torrent
    torrent = Torrent.from_file(str(path))
    assert torrent.name == "test.bin"
    assert torrent.total_size == len(data)
    assert torrent.is_multi_file is False
    assert torrent.num_pieces == len(torrent.piece_hashes)


def test_info_hash_matches_raw_info(single_file_torrent):
    path, _, info = single_file_torrent
    torrent = Torrent.from_file(str(path))
    expected = hashlib.sha1(bencode.encode(info)).digest()
    assert torrent.info_hash == expected


def test_announce_list_tiers(single_file_torrent):
    path, _, _ = single_file_torrent
    torrent = Torrent.from_file(str(path))
    assert len(torrent.trackers) == 2
    assert "http://tracker.example/announce" in torrent.all_tracker_urls


def test_multi_file(tmp_path):
    files = [(b"a.txt", b"a" * 20000), (b"b.txt", b"b" * 30000)]
    payload, _, _ = make_torrent_bytes(name=b"bundle", files=files)
    path = tmp_path / "multi.torrent"
    path.write_bytes(payload)
    torrent = Torrent.from_file(str(path))
    assert torrent.is_multi_file
    assert torrent.total_size == 50000
    assert torrent.files[1].offset == 20000


def test_piece_size_last_piece(single_file_torrent):
    path, data, _ = single_file_torrent
    torrent = Torrent.from_file(str(path))
    total = sum(torrent.piece_size(i) for i in range(torrent.num_pieces))
    assert total == len(data)


def test_magnet_roundtrip(single_file_torrent):
    path, _, _ = single_file_torrent
    torrent = Torrent.from_file(str(path))
    magnet = MagnetLink.parse(torrent.magnet_link())
    assert magnet.info_hash == torrent.info_hash
    assert magnet.display_name == torrent.name


def test_magnet_rejects_non_magnet():
    with pytest.raises(ValueError):
        MagnetLink.parse("http://not-a-magnet")


def test_path_traversal_sanitized(tmp_path):
    import os
    files = [(b"../../evil.txt", b"x" * 16384)]
    payload, _, _ = make_torrent_bytes(name=b"bundle", files=files)
    path = tmp_path / "evil.torrent"
    path.write_bytes(payload)
    torrent = Torrent.from_file(str(path))
    # No path component may be a traversal token, so the resolved file
    # cannot escape the save directory.
    components = torrent.files[0].path.replace("\\", "/").split("/")
    assert ".." not in components
    save_dir = str(tmp_path / "out")
    resolved = os.path.realpath(os.path.join(save_dir, torrent.files[0].path))
    assert resolved.startswith(os.path.realpath(save_dir))
