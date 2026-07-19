from alembic import context
from sqlalchemy import engine_from_config, pool

import shop_scout.db.models  # noqa: F401
from shop_scout.db.base import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    database_url = config.get_main_option("sqlalchemy.url") or ""
    context.configure(
        url=database_url.replace("+aiosqlite", ""),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = str(section["sqlalchemy.url"]).replace("+aiosqlite", "")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
