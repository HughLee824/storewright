from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

import storewright_catalog_scout.db.models  # noqa: F401
from storewright_catalog_scout.db.base import Base


async def initialize_database(engine: AsyncEngine) -> None:
    """Create the schema; Alembic uses the same metadata for installed deployments."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def upgrade_database(database_url: str) -> None:
    """Apply committed Alembic revisions for CLI initialization."""
    from storewright_catalog_scout import alembic as packaged_alembic

    config = Config()
    config.set_main_option("script_location", str(packaged_alembic.package_path()))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
