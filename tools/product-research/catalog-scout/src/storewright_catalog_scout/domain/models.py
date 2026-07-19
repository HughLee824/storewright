from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from storewright_catalog_scout.domain.enums import (
    EvidenceKind,
    PageKind,
    ProductVerdict,
    ShopDecision,
    UrlRelation,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShopInput(DomainModel):
    shop_url: HttpUrl | str


class ShopIdentity(DomainModel):
    original_url: str
    canonical_url: str
    host: str
    registrable_domain: str
    canonical_key: str
    external_shop_id: str | None = None
    shop_subdomain: str | None = None
    display_name: str | None = None


class NavigationResult(DomainModel):
    success: bool
    final_url: str | None = None
    page_kind: PageKind
    requires_human: bool = False
    reason: str
    visible_product_count: int | None = None


class ProductRef(DomainModel):
    external_item_id: str
    canonical_url: str
    title: str | None = None
    listing_image_url: str | None = None
    source_position: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductDetail(DomainModel):
    external_item_id: str
    canonical_url: str
    title: str
    main_image_url: str
    image_urls: list[str] = Field(default_factory=list)
    image_roles: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    category_path: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)
    variants: list[dict[str, Any]] = Field(default_factory=list)
    price: str | None = None
    currency: str | None = None
    price_details: dict[str, Any] = Field(default_factory=dict)
    source: Literal[
        "structured_state", "og_image", "json_ld", "visible_image", "listing_fallback"
    ]
    raw_html: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageArtifact(DomainModel):
    source_url: str
    raw_path: Path
    normalized_path: Path
    sha256: str
    phash: str
    width: int
    height: int
    file_size: int
    content_type: str
    role: str = "gallery"


class WebImageMatch(DomainModel):
    url: str
    score: float | None = None


class WebPageMatch(DomainModel):
    url: str
    title: str | None = None
    full_matching_images: list[WebImageMatch] = Field(default_factory=list)
    partial_matching_images: list[WebImageMatch] = Field(default_factory=list)


class WebDetectionResult(DomainModel):
    provider: str
    image_sha256: str
    full_matching_images: list[WebImageMatch] = Field(default_factory=list)
    partial_matching_images: list[WebImageMatch] = Field(default_factory=list)
    pages_with_matching_images: list[WebPageMatch] = Field(default_factory=list)
    visually_similar_images: list[WebImageMatch] = Field(default_factory=list)
    best_guess_labels: list[str] = Field(default_factory=list)
    web_entities: list[dict[str, Any]] = Field(default_factory=list)
    raw_response_path: Path


class MatchEvidence(DomainModel):
    kind: EvidenceKind
    url: str
    page_url: str | None = None
    page_title: str | None = None
    relation: UrlRelation
    reason: str


class ProductDecisionResult(DomainModel):
    verdict: ProductVerdict
    reason_code: str
    summary: str
    evidence: list[MatchEvidence] = Field(default_factory=list)
    confidence: Decimal


class ShopDecisionResult(DomainModel):
    decision: ShopDecision
    reason_code: str
    summary: str
    discovered_count: int
    processed_count: int
    search_success_count: int
    exact_count: int
    qualified_count: int
    skipped_count: int
    error_count: int
    rejection_rate: Decimal
    early_stopped: bool


class ShopContext(DomainModel):
    discovered_count: int
    processed_count: int
    search_success_count: int
    exact_count: int
    qualified_count: int
    skipped_count: int
    error_count: int
    catalog_complete: bool = True
    early_stopped: bool = False
    reject_rate_threshold: float = 0.6
    max_search_error_rate: float = 0.2


class RunRequest(DomainModel):
    shops: list[ShopInput]
    seed: int
    mock_vision: bool
    input_file_path: Path
    confirm_authorized: bool


class ReportPaths(DomainModel):
    run_id: UUID
    shops_csv: Path
    products_csv: Path
    html: Path
    summary_json: Path
