"""End-to-end loopback test: a seeding engine serves a real download to a
leeching engine over localhost, exercising the full wire protocol."""
import asyncio
import os

import pytest

from src.core.engine import Engine
from src.core.session import State
from tests.conftest import make_torrent_bytes


@pytest.mark.asyncio
async def test_loopback_download(tmp_path):
    data = os.urandom(80000)  # ~5 pieces at 16 KiB
    payload, _, _ = make_torrent_bytes(name=b"payload.bin",
                                       piece_length=16384, data=data)
    torrent_path = tmp_path / "x.torrent"
    torrent_path.write_bytes(payload)

    # Seeder already has the complete file on disk.
    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    (seed_dir / "payload.bin").write_bytes(data)

    seeder = Engine(save_dir=str(seed_dir), port=6981)
    leecher = Engine(save_dir=str(tmp_path / "leech"), port=6982)
    await seeder.start_listener()
    await leecher.start_listener()

    try:
        seed_session = await seeder.add_torrent_file(str(torrent_path))
        leech_session = await leecher.add_torrent_file(str(torrent_path))

        # Wait for the seeder to finish its existing-data check.
        for _ in range(50):
            if seed_session.piece_manager and seed_session.piece_manager.is_complete:
                break
            await asyncio.sleep(0.1)
        assert seed_session.piece_manager.is_complete

        # Hand the leecher the seeder's address directly (no tracker needed).
        leech_session.known_addresses.add(("127.0.0.1", seeder.port))

        for _ in range(100):
            if leech_session.piece_manager and leech_session.piece_manager.is_complete:
                break
            await asyncio.sleep(0.1)

        assert leech_session.piece_manager.is_complete, "leecher did not finish"
        leecher.sessions[leech_session.torrent_hash]  # still tracked
        downloaded = (tmp_path / "leech" / "payload.bin").read_bytes()
        assert downloaded == data
        assert seed_session.uploaded >= len(data)
    finally:
        await seeder.shutdown()
        await leecher.shutdown()
