import hashlib

import pytest

from src.core.piece_manager import BLOCK_SIZE, PieceManager
from src.core.torrent import Torrent
from tests.conftest import make_torrent_bytes


@pytest.fixture
def manager(tmp_path):
    payload, data, _ = make_torrent_bytes(data=b"Z" * 40000, piece_length=16384)
    tpath = tmp_path / "t.torrent"
    tpath.write_bytes(payload)
    torrent = Torrent.from_file(str(tpath))
    return PieceManager(torrent, str(tmp_path / "out")), torrent, data


@pytest.mark.asyncio
async def test_full_download_writes_correct_file(manager, tmp_path):
    pm, torrent, data = manager
    for piece in range(torrent.num_pieces):
        offset = 0
        while offset < torrent.piece_size(piece):
            length = pm.block_length(piece, offset)
            start = piece * torrent.piece_length + offset
            await pm.on_block(piece, offset, data[start:start + length])
            offset += length
    assert pm.is_complete
    pm.close()
    out_file = tmp_path / "out" / "test.bin"
    assert out_file.read_bytes() == data


@pytest.mark.asyncio
async def test_bad_hash_resets_piece(manager):
    pm, torrent, data = manager
    offset = 0
    while offset < torrent.piece_size(0):
        length = pm.block_length(0, offset)
        result = await pm.on_block(0, offset, b"\x00" * length)
        offset += length
    assert result is False
    assert 0 not in pm.have


def test_next_requests_respects_peer_pieces(manager):
    pm, torrent, _ = manager
    requests = pm.next_requests({0}, count=10, in_flight=set())
    assert all(piece == 0 for piece, _, _ in requests)


def test_bitfield_roundtrip(manager):
    pm, torrent, _ = manager
    pm.have.add(0)
    field = pm.bitfield
    assert field[0] & 0x80


@pytest.mark.asyncio
async def test_verify_existing_marks_complete(manager, tmp_path):
    pm, torrent, data = manager
    for piece in range(torrent.num_pieces):
        offset = 0
        while offset < torrent.piece_size(piece):
            length = pm.block_length(piece, offset)
            start = piece * torrent.piece_length + offset
            await pm.on_block(piece, offset, data[start:start + length])
            offset += length
    pm.close()

    fresh = PieceManager(torrent, str(tmp_path / "out"))
    await fresh.verify_existing()
    assert fresh.is_complete
    fresh.close()
