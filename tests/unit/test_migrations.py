import sqlite3
from pathlib import Path

from shop_scout.db.migrations import upgrade_database


def test_empty_database_upgrades_to_packaged_head(tmp_path: Path) -> None:
    database = tmp_path / "fresh.db"
    upgrade_database(f"sqlite:///{database}")
    with sqlite3.connect(database) as connection:
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        price_column = connection.execute(
            "SELECT COUNT(*) FROM pragma_table_info('product_snapshots') "
            "WHERE name='price_details_json'"
        ).fetchone()
    assert version == ("0002_price_details",)
    assert price_column == (1,)
