from pathlib import Path

import pytest

from shop_scout.db.migrations import initialize_database
from shop_scout.db.repositories import RunRepository
from shop_scout.db.session import create_engine, create_session_factory


@pytest.fixture
async def repository(tmp_path: Path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await initialize_database(engine)
    yield RunRepository(create_session_factory(engine))
    await engine.dispose()
