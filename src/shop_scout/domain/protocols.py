from pathlib import Path
from typing import Protocol
from uuid import UUID

from shop_scout.domain.enums import PageKind, UrlRelation
from shop_scout.domain.models import (
    ImageArtifact,
    ProductDetail,
    ProductRef,
    ShopIdentity,
    WebDetectionResult,
)


class SourceAdapter(Protocol):
    source_name: str

    def identify_shop_url(
        self, input_url: str, display_name: str | None = None
    ) -> ShopIdentity: ...

    def classify_url(self, url: str) -> PageKind: ...

    def collect_product_pool_html(self, html: str, base_url: str) -> list[ProductRef]: ...

    def extract_product_detail_html(
        self, html: str, product: ProductRef, base_url: str
    ) -> ProductDetail: ...

    def classify_relation(
        self, shop: ShopIdentity, product: ProductRef, candidate_url: str
    ) -> UrlRelation: ...


class WebDetectionProvider(Protocol):
    name: str

    async def detect(
        self, image: ImageArtifact, *, run_id: UUID, output_dir: Path
    ) -> WebDetectionResult: ...
