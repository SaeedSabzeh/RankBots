import tempfile

import pytest

from engine.db import Store


@pytest.fixture(scope="session")
def pg_uri():
    """A throwaway local Postgres. Database tests are skipped if it can't start."""
    pgserver = pytest.importorskip("pgserver")
    data_dir = tempfile.mkdtemp(prefix="rankbots-pg-")
    try:
        server = pgserver.get_server(data_dir, cleanup_mode="stop")
    except Exception as e:  # pragma: no cover - depends on the machine
        pytest.skip(f"embedded Postgres unavailable: {e}")
    yield server.get_uri()
    server.cleanup()


@pytest.fixture
async def store(pg_uri):
    s = await Store.connect(pg_uri)
    await s.migrate()
    await s.pool.execute("TRUNCATE chats, players, plays, duels")
    yield s
    await s.close()
