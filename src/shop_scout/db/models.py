from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shop_scout.db.base import Base, utc_now
from shop_scout.domain.enums import ProductRunStatus, RunStatus, ShopRunStatus, VisionQueryStatus


def uuid_column() -> Mapped[UUID]:
    return mapped_column(primary_key=True, default=uuid4)


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[UUID] = uuid_column()
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.CREATED)
    seed: Mapped[int]
    max_qualified_per_category: Mapped[int]
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_file_path: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    shop_runs: Mapped[list[ShopRunRow]] = relationship(back_populates="run")


class ShopRow(Base):
    __tablename__ = "shops"
    id: Mapped[UUID] = uuid_column()
    canonical_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_url: Mapped[str]
    canonical_url: Mapped[str]
    host: Mapped[str]
    external_shop_id: Mapped[str | None]
    shop_subdomain: Mapped[str | None]
    display_name: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ShopRunRow(Base):
    __tablename__ = "shop_runs"
    __table_args__ = (UniqueConstraint("run_id", "shop_id"),)
    id: Mapped[UUID] = uuid_column()
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    shop_id: Mapped[UUID] = mapped_column(ForeignKey("shops.id"))
    status: Mapped[str] = mapped_column(String(48), default=ShopRunStatus.PENDING)
    decision: Mapped[str | None] = mapped_column(String(48))
    decision_reason_code: Mapped[str | None]
    decision_summary: Mapped[str | None] = mapped_column(Text)
    discovered_count: Mapped[int] = mapped_column(default=0)
    processed_count: Mapped[int] = mapped_column(default=0)
    search_success_count: Mapped[int] = mapped_column(default=0)
    exact_count: Mapped[int] = mapped_column(default=0)
    qualified_count: Mapped[int] = mapped_column(default=0)
    skipped_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    rejection_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))
    catalog_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    early_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    final_listing_url: Mapped[str | None]
    manual_action_reason: Mapped[str | None] = mapped_column(Text)
    failure_screenshot_path: Mapped[str | None]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run: Mapped[RunRow] = relationship(back_populates="shop_runs")
    shop: Mapped[ShopRow] = relationship()
    product_runs: Mapped[list[ProductRunRow]] = relationship(back_populates="shop_run")


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("shop_id", "external_item_id"),)
    id: Mapped[UUID] = uuid_column()
    shop_id: Mapped[UUID] = mapped_column(ForeignKey("shops.id"))
    external_item_id: Mapped[str]
    canonical_url: Mapped[str]
    title: Mapped[str | None]
    listing_image_url: Mapped[str | None]
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductRunRow(Base):
    __tablename__ = "product_runs"
    __table_args__ = (
        UniqueConstraint("shop_run_id", "product_id"),
        UniqueConstraint("shop_run_id", "processing_index"),
    )
    id: Mapped[UUID] = uuid_column()
    shop_run_id: Mapped[UUID] = mapped_column(ForeignKey("shop_runs.id", ondelete="CASCADE"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id"))
    processing_index: Mapped[int]
    order_seed: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(64), default=ProductRunStatus.PENDING)
    category_key: Mapped[str | None]
    detail_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    shop_run: Mapped[ShopRunRow] = relationship(back_populates="product_runs")
    product: Mapped[ProductRow] = relationship()
    screening_image: Mapped[ScreeningImageRow | None] = relationship(back_populates="product_run")
    snapshot: Mapped[ProductSnapshotRow | None] = relationship(back_populates="product_run")
    assets: Mapped[list[ProductAssetRow]] = relationship(back_populates="product_run")
    verdict: Mapped[ProductVerdictRow | None] = relationship(back_populates="product_run")


class ScreeningImageRow(Base):
    __tablename__ = "screening_images"
    __table_args__ = (
        Index("ix_screening_images_sha256", "sha256"),
        Index("ix_screening_images_phash", "phash"),
    )
    id: Mapped[UUID] = uuid_column()
    product_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_runs.id", ondelete="CASCADE"), unique=True
    )
    source_url: Mapped[str]
    raw_path: Mapped[str]
    normalized_path: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    phash: Mapped[str] = mapped_column(String(64))
    width: Mapped[int]
    height: Mapped[int]
    file_size: Mapped[int]
    content_type: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    product_run: Mapped[ProductRunRow] = relationship(back_populates="screening_image")


class ProductSnapshotRow(Base):
    __tablename__ = "product_snapshots"
    id: Mapped[UUID] = uuid_column()
    product_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_runs.id", ondelete="CASCADE"), unique=True
    )
    title: Mapped[str]
    description: Mapped[str | None] = mapped_column(Text)
    category_path_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    materials_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    attributes_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    variants_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    price: Mapped[str | None]
    currency: Mapped[str | None]
    price_details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    detail_json_path: Mapped[str]
    raw_html_path: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    product_run: Mapped[ProductRunRow] = relationship(back_populates="snapshot")


class ProductAssetRow(Base):
    __tablename__ = "product_assets"
    __table_args__ = (UniqueConstraint("product_run_id", "source_url"),)
    id: Mapped[UUID] = uuid_column()
    product_run_id: Mapped[UUID] = mapped_column(ForeignKey("product_runs.id", ondelete="CASCADE"))
    position: Mapped[int]
    role: Mapped[str]
    source_url: Mapped[str]
    raw_path: Mapped[str]
    normalized_path: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    phash: Mapped[str] = mapped_column(String(64))
    width: Mapped[int]
    height: Mapped[int]
    file_size: Mapped[int]
    content_type: Mapped[str]
    product_run: Mapped[ProductRunRow] = relationship(back_populates="assets")


class VisionQueryRow(Base):
    __tablename__ = "vision_queries"
    __table_args__ = (UniqueConstraint("provider", "image_sha256", "variant"),)
    id: Mapped[UUID] = uuid_column()
    provider: Mapped[str]
    image_sha256: Mapped[str] = mapped_column(String(64))
    variant: Mapped[str]
    status: Mapped[str] = mapped_column(String(32), default=VisionQueryStatus.PENDING)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_response_path: Mapped[str | None]
    request_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(default=0)
    error_code: Mapped[str | None]
    error_message: Mapped[str | None] = mapped_column(Text)


class MatchEvidenceRow(Base):
    __tablename__ = "match_evidence"
    id: Mapped[UUID] = uuid_column()
    vision_query_id: Mapped[UUID | None] = mapped_column(ForeignKey("vision_queries.id"))
    product_run_id: Mapped[UUID] = mapped_column(ForeignKey("product_runs.id"))
    kind: Mapped[str]
    url: Mapped[str]
    page_url: Mapped[str | None]
    page_title: Mapped[str | None]
    host: Mapped[str | None]
    registrable_domain: Mapped[str | None]
    relation: Mapped[str]
    reason: Mapped[str]
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProductVerdictRow(Base):
    __tablename__ = "product_verdicts"
    id: Mapped[UUID] = uuid_column()
    product_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("product_runs.id", ondelete="CASCADE"), unique=True
    )
    verdict: Mapped[str]
    reason_code: Mapped[str]
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    product_run: Mapped[ProductRunRow] = relationship(back_populates="verdict")


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[UUID] = uuid_column()
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    shop_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("shop_runs.id"))
    product_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("product_runs.id"))
    event_type: Mapped[str]
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
