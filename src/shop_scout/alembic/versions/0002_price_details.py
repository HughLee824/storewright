"""Store structured price details.

Revision ID: 0002_price_details
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import context, op

revision: str = "0002_price_details"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not context.is_offline_mode() and _has_price_details_column():
        return
    op.add_column(
        "product_snapshots",
        sa.Column("price_details_json", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    if not context.is_offline_mode() and not _has_price_details_column():
        return
    op.drop_column("product_snapshots", "price_details_json")


def _has_price_details_column() -> bool:
    columns = sa.inspect(op.get_bind()).get_columns("product_snapshots")
    return any(column["name"] == "price_details_json" for column in columns)
