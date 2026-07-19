from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import tldextract
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from storewright_catalog_scout.db.base import utc_now
from storewright_catalog_scout.db.models import (
    EventRow,
    MatchEvidenceRow,
    ProductAssetRow,
    ProductRow,
    ProductRunRow,
    ProductSnapshotRow,
    ProductVerdictRow,
    RunRow,
    ScreeningImageRow,
    ShopRow,
    ShopRunRow,
    VisionQueryRow,
)
from storewright_catalog_scout.domain.enums import (
    ProductRunStatus,
    RunStatus,
    ShopRunStatus,
    VisionQueryStatus,
)
from storewright_catalog_scout.domain.models import (
    ImageArtifact,
    ProductDecisionResult,
    ProductDetail,
    ProductRef,
    RunRequest,
    ShopDecisionResult,
    ShopIdentity,
    WebDetectionResult,
)


class RunRepository:
    def __init__(self, sessions) -> None:
        self.sessions = sessions

    async def create_run(self, request: RunRequest, config: dict) -> RunRow:
        async with self.sessions.begin() as session:
            row = RunRow(
                status=RunStatus.RUNNING,
                seed=request.seed,
                max_qualified_per_category=int(config["max_qualified_per_category"]),
                config_snapshot_json=config,
                input_file_path=str(request.input_file_path),
                started_at=utc_now(),
            )
            session.add(row)
            await session.flush()
            return row

    async def get_run(self, run_id: UUID) -> RunRow | None:
        async with self.sessions() as session:
            return await session.get(RunRow, run_id)

    async def set_run_status(
        self, run_id: UUID, status: RunStatus, error: str | None = None
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            row.status = status
            row.last_error = error
            if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                row.finished_at = utc_now()

    async def get_or_create_shop_run(
        self, run_id: UUID, identity: ShopIdentity
    ) -> ShopRunRow:
        async with self.sessions.begin() as session:
            shop = await session.scalar(
                select(ShopRow).where(ShopRow.canonical_key == identity.canonical_key)
            )
            if shop is None:
                shop = ShopRow(
                    canonical_key=identity.canonical_key,
                    original_url=identity.original_url,
                    canonical_url=identity.canonical_url,
                    host=identity.host,
                    external_shop_id=identity.external_shop_id,
                    shop_subdomain=identity.shop_subdomain,
                    display_name=identity.display_name,
                )
                session.add(shop)
                await session.flush()
            row = await session.scalar(
                select(ShopRunRow).where(
                    ShopRunRow.run_id == run_id,
                    ShopRunRow.shop_id == shop.id,
                )
            )
            if row is None:
                row = ShopRunRow(
                    run_id=run_id,
                    shop_id=shop.id,
                    status=ShopRunStatus.PENDING,
                    started_at=utc_now(),
                )
                session.add(row)
                await session.flush()
            return row

    async def set_shop_stage(self, shop_run_id: UUID, status: ShopRunStatus) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ShopRunRow, shop_run_id)
            if row is None:
                raise KeyError(shop_run_id)
            row.status = status

    async def pause_shop(self, shop_run_id: UUID, reason: str) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ShopRunRow, shop_run_id)
            if row is None:
                raise KeyError(shop_run_id)
            row.status = ShopRunStatus.PAUSED
            row.manual_action_reason = reason

    async def mark_shop_manual_action(self, shop_run_id: UUID, reason: str) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ShopRunRow, shop_run_id)
            if row is None:
                raise KeyError(shop_run_id)
            row.status = ShopRunStatus.MANUAL_ACTION_REQUIRED
            row.decision = "review"
            row.decision_reason_code = "MANUAL_ACTION_REQUIRED"
            row.decision_summary = "登录或安全验证需要人工处理，自动流程已停止。"
            row.manual_action_reason = reason
            row.finished_at = utc_now()

    async def save_products(
        self,
        shop_run_id: UUID,
        shop_id: UUID,
        products: Sequence[ProductRef],
        *,
        order_seed: int,
        catalog_complete: bool,
    ) -> list[ProductRunRow]:
        async with self.sessions.begin() as session:
            shop_run = await session.get(ShopRunRow, shop_run_id)
            if shop_run is None:
                raise KeyError(shop_run_id)
            shop_run.discovered_count = len(products)
            shop_run.catalog_complete = catalog_complete
            for index, item in enumerate(products):
                product = await session.scalar(
                    select(ProductRow).where(
                        ProductRow.shop_id == shop_id,
                        ProductRow.external_item_id == item.external_item_id,
                    )
                )
                if product is None:
                    product = ProductRow(
                        shop_id=shop_id,
                        external_item_id=item.external_item_id,
                        canonical_url=item.canonical_url,
                        title=item.title,
                        listing_image_url=item.listing_image_url,
                        metadata_json=item.metadata,
                    )
                    session.add(product)
                    await session.flush()
                else:
                    product.canonical_url = item.canonical_url
                    product.title = item.title or product.title
                    product.listing_image_url = item.listing_image_url or product.listing_image_url
                    product.metadata_json = item.metadata
                    product.last_seen_at = utc_now()
                existing = await session.scalar(
                    select(ProductRunRow).where(
                        ProductRunRow.shop_run_id == shop_run_id,
                        ProductRunRow.product_id == product.id,
                    )
                )
                if existing is None:
                    session.add(
                        ProductRunRow(
                            shop_run_id=shop_run_id,
                            product_id=product.id,
                            processing_index=index,
                            order_seed=str(order_seed),
                        )
                    )
            await session.flush()
        return await self.load_product_runs(shop_run_id)

    async def load_product_runs(self, shop_run_id: UUID) -> list[ProductRunRow]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ProductRunRow)
                .where(ProductRunRow.shop_run_id == shop_run_id)
                .options(
                    selectinload(ProductRunRow.product),
                    selectinload(ProductRunRow.screening_image),
                    selectinload(ProductRunRow.snapshot),
                    selectinload(ProductRunRow.assets),
                    selectinload(ProductRunRow.verdict),
                )
                .order_by(ProductRunRow.processing_index)
            )
            return list(rows)

    async def set_product_stage(
        self,
        product_run_id: UUID,
        status: ProductRunStatus,
        error: str | None = None,
        category_key: str | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ProductRunRow, product_run_id)
            if row is None:
                raise KeyError(product_run_id)
            row.status = status
            row.last_error = error
            if category_key is not None:
                row.category_key = category_key
            if status in {
                ProductRunStatus.QUALIFIED,
                ProductRunStatus.REJECTED,
                ProductRunStatus.REVIEW,
                ProductRunStatus.FAILED,
                ProductRunStatus.SKIPPED_CATEGORY_QUOTA_REACHED,
                ProductRunStatus.SKIPPED_AFTER_SHOP_REJECTED,
            }:
                row.completed_at = utc_now()

    async def save_screening_image(
        self, product_run_id: UUID, image: ImageArtifact
    ) -> ScreeningImageRow:
        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ScreeningImageRow).where(
                    ScreeningImageRow.product_run_id == product_run_id
                )
            )
            if existing is not None:
                return existing
            row = ScreeningImageRow(
                product_run_id=product_run_id,
                source_url=image.source_url,
                raw_path=str(image.raw_path),
                normalized_path=str(image.normalized_path),
                sha256=image.sha256,
                phash=image.phash,
                width=image.width,
                height=image.height,
                file_size=image.file_size,
                content_type=image.content_type,
            )
            session.add(row)
            await session.flush()
            return row

    async def find_cross_shop_image(
        self, sha256: str, current_shop_id: UUID
    ) -> tuple[ScreeningImageRow, ProductRow] | None:
        async with self.sessions() as session:
            result = await session.execute(
                select(ScreeningImageRow, ProductRow)
                .join(ProductRunRow, ScreeningImageRow.product_run_id == ProductRunRow.id)
                .join(ProductRow, ProductRunRow.product_id == ProductRow.id)
                .where(ScreeningImageRow.sha256 == sha256, ProductRow.shop_id != current_shop_id)
                .limit(1)
            )
            row = result.first()
            return (row[0], row[1]) if row else None

    async def get_vision_cache(
        self, provider: str, sha256: str, variant: str
    ) -> VisionQueryRow | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(VisionQueryRow).where(
                    VisionQueryRow.provider == provider,
                    VisionQueryRow.image_sha256 == sha256,
                    VisionQueryRow.variant == variant,
                    VisionQueryRow.status == VisionQueryStatus.SUCCEEDED,
                )
            )

    async def save_vision_success(self, result: WebDetectionResult, variant: str) -> VisionQueryRow:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(VisionQueryRow).where(
                    VisionQueryRow.provider == result.provider,
                    VisionQueryRow.image_sha256 == result.image_sha256,
                    VisionQueryRow.variant == variant,
                )
            )
            if row is None:
                row = VisionQueryRow(
                    provider=result.provider,
                    image_sha256=result.image_sha256,
                    variant=variant,
                    status=VisionQueryStatus.SUCCEEDED,
                    result_json=result.model_dump(mode="json"),
                    raw_response_path=str(result.raw_response_path),
                    request_started_at=utc_now(),
                    request_finished_at=utc_now(),
                    attempt_count=1,
                )
                session.add(row)
            else:
                row.status = VisionQueryStatus.SUCCEEDED
                row.result_json = result.model_dump(mode="json")
                row.raw_response_path = str(result.raw_response_path)
                row.request_finished_at = utc_now()
                row.attempt_count += 1
            await session.flush()
            return row

    async def save_vision_failure(
        self, provider: str, sha256: str, variant: str, code: str, message: str
    ) -> None:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(VisionQueryRow).where(
                    VisionQueryRow.provider == provider,
                    VisionQueryRow.image_sha256 == sha256,
                    VisionQueryRow.variant == variant,
                )
            )
            if row is None:
                row = VisionQueryRow(
                    provider=provider,
                    image_sha256=sha256,
                    variant=variant,
                    status=VisionQueryStatus.FAILED,
                    result_json=None,
                    request_started_at=utc_now(),
                    request_finished_at=utc_now(),
                    attempt_count=1,
                    error_code=code,
                    error_message=message,
                )
                session.add(row)
            else:
                row.status = VisionQueryStatus.FAILED
                row.request_finished_at = utc_now()
                row.attempt_count += 1
                row.error_code = code
                row.error_message = message

    async def save_decision(
        self,
        product_run_id: UUID,
        decision: ProductDecisionResult,
        vision_query_id: UUID | None,
    ) -> None:
        from urllib.parse import urlsplit

        async with self.sessions.begin() as session:
            existing = await session.scalar(
                select(ProductVerdictRow).where(
                    ProductVerdictRow.product_run_id == product_run_id
                )
            )
            if existing is None:
                session.add(
                    ProductVerdictRow(
                        product_run_id=product_run_id,
                        verdict=decision.verdict,
                        reason_code=decision.reason_code,
                        summary=decision.summary,
                        confidence=decision.confidence,
                    )
                )
            else:
                existing.verdict = decision.verdict
                existing.reason_code = decision.reason_code
                existing.summary = decision.summary
                existing.confidence = decision.confidence
            for item in decision.evidence:
                host = urlsplit(item.url).hostname
                registered = tldextract.extract(host or "").top_domain_under_public_suffix or None
                session.add(
                    MatchEvidenceRow(
                        vision_query_id=vision_query_id,
                        product_run_id=product_run_id,
                        kind=item.kind,
                        url=item.url,
                        page_url=item.page_url,
                        page_title=item.page_title,
                        host=host,
                        registrable_domain=registered,
                        relation=item.relation,
                        reason=item.reason,
                        raw_json={},
                    )
                )

    async def save_archive(
        self,
        product_run_id: UUID,
        detail: ProductDetail,
        detail_json_path: Path,
        raw_html_path: Path | None,
        assets: Sequence[ImageArtifact],
    ) -> None:
        async with self.sessions.begin() as session:
            product_run = await session.get(ProductRunRow, product_run_id)
            if product_run is None:
                raise KeyError(product_run_id)
            existing_snapshot = await session.scalar(
                select(ProductSnapshotRow).where(
                    ProductSnapshotRow.product_run_id == product_run_id
                )
            )
            if existing_snapshot is None:
                session.add(
                    ProductSnapshotRow(
                        product_run_id=product_run_id,
                        title=detail.title,
                        description=detail.description,
                        category_path_json=detail.category_path,
                        materials_json=detail.materials,
                        attributes_json=detail.attributes,
                        variants_json=detail.variants,
                        price=detail.price,
                        currency=detail.currency,
                        price_details_json=detail.price_details,
                        detail_json_path=str(detail_json_path),
                        raw_html_path=str(raw_html_path) if raw_html_path else None,
                    )
                )
            for index, image in enumerate(assets):
                existing = await session.scalar(
                    select(ProductAssetRow).where(
                        ProductAssetRow.product_run_id == product_run_id,
                        ProductAssetRow.source_url == image.source_url,
                    )
                )
                if existing is None:
                    session.add(
                        ProductAssetRow(
                            product_run_id=product_run_id,
                            position=index,
                            role=image.role if index else "main",
                            source_url=image.source_url,
                            raw_path=str(image.raw_path),
                            normalized_path=str(image.normalized_path),
                            sha256=image.sha256,
                            phash=image.phash,
                            width=image.width,
                            height=image.height,
                            file_size=image.file_size,
                            content_type=image.content_type,
                        )
                    )
            product_run.detail_archived = True

    async def replace_archive(
        self,
        product_run_id: UUID,
        detail: ProductDetail,
        detail_json_path: Path,
        raw_html_path: Path | None,
        assets: Sequence[ImageArtifact],
    ) -> None:
        async with self.sessions.begin() as session:
            product_run = await session.get(ProductRunRow, product_run_id)
            if product_run is None:
                raise KeyError(product_run_id)
            snapshot = await session.scalar(
                select(ProductSnapshotRow).where(
                    ProductSnapshotRow.product_run_id == product_run_id
                )
            )
            if snapshot is None:
                snapshot = ProductSnapshotRow(product_run_id=product_run_id)
                session.add(snapshot)
            snapshot.title = detail.title
            snapshot.description = detail.description
            snapshot.category_path_json = detail.category_path
            snapshot.materials_json = detail.materials
            snapshot.attributes_json = detail.attributes
            snapshot.variants_json = detail.variants
            snapshot.price = detail.price
            snapshot.currency = detail.currency
            snapshot.price_details_json = detail.price_details
            snapshot.detail_json_path = str(detail_json_path)
            snapshot.raw_html_path = str(raw_html_path) if raw_html_path else None
            await session.execute(
                delete(ProductAssetRow).where(ProductAssetRow.product_run_id == product_run_id)
            )
            for index, image in enumerate(assets):
                session.add(
                    ProductAssetRow(
                        product_run_id=product_run_id,
                        position=index,
                        role=image.role if index else "main",
                        source_url=image.source_url,
                        raw_path=str(image.raw_path),
                        normalized_path=str(image.normalized_path),
                        sha256=image.sha256,
                        phash=image.phash,
                        width=image.width,
                        height=image.height,
                        file_size=image.file_size,
                        content_type=image.content_type,
                    )
                )
            product_run.detail_archived = True

    async def category_qualified_count(self, shop_run_id: UUID, category_key: str) -> int:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ProductRunRow.id).where(
                    ProductRunRow.shop_run_id == shop_run_id,
                    ProductRunRow.category_key == category_key,
                    ProductRunRow.status == ProductRunStatus.QUALIFIED,
                    ProductRunRow.detail_archived.is_(True),
                )
            )
            return len(list(rows))

    async def save_shop_decision(self, shop_run_id: UUID, decision: ShopDecisionResult) -> None:
        async with self.sessions.begin() as session:
            row = await session.get(ShopRunRow, shop_run_id)
            if row is None:
                raise KeyError(shop_run_id)
            row.status = ShopRunStatus.COMPLETED
            row.decision = decision.decision
            row.decision_reason_code = decision.reason_code
            row.decision_summary = decision.summary
            row.discovered_count = decision.discovered_count
            row.processed_count = decision.processed_count
            row.search_success_count = decision.search_success_count
            row.exact_count = decision.exact_count
            row.qualified_count = decision.qualified_count
            row.skipped_count = decision.skipped_count
            row.error_count = decision.error_count
            row.rejection_rate = decision.rejection_rate
            row.early_stopped = decision.early_stopped
            row.finished_at = utc_now()

    async def add_event(
        self,
        run_id: UUID,
        event_type: str,
        message: str,
        *,
        shop_run_id: UUID | None = None,
        product_run_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        async with self.sessions.begin() as session:
            session.add(
                EventRow(
                    run_id=run_id,
                    shop_run_id=shop_run_id,
                    product_run_id=product_run_id,
                    event_type=event_type,
                    message=message,
                    metadata_json=metadata or {},
                )
            )

    async def report_rows(self, run_id: UUID) -> list[ShopRunRow]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ShopRunRow)
                .where(ShopRunRow.run_id == run_id)
                .options(
                    selectinload(ShopRunRow.shop),
                    selectinload(ShopRunRow.product_runs).selectinload(ProductRunRow.product),
                    selectinload(ShopRunRow.product_runs).selectinload(
                        ProductRunRow.screening_image
                    ),
                    selectinload(ShopRunRow.product_runs).selectinload(ProductRunRow.snapshot),
                    selectinload(ShopRunRow.product_runs).selectinload(ProductRunRow.assets),
                    selectinload(ShopRunRow.product_runs).selectinload(ProductRunRow.verdict),
                )
            )
            return list(rows)

    async def review_rows(self, run_id: UUID) -> list[ShopRunRow]:
        return [
            row
            for row in await self.report_rows(run_id)
            if row.decision in {"review", "insufficient_data"}
        ]

    async def evidence_for_product(self, product_run_id: UUID) -> list[MatchEvidenceRow]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(MatchEvidenceRow)
                .where(MatchEvidenceRow.product_run_id == product_run_id)
                .order_by(MatchEvidenceRow.created_at)
            )
            return list(rows)

    async def vision_for_sha256(self, sha256: str) -> VisionQueryRow | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(VisionQueryRow)
                .where(
                    VisionQueryRow.image_sha256 == sha256,
                    VisionQueryRow.status == VisionQueryStatus.SUCCEEDED,
                )
                .order_by(VisionQueryRow.request_finished_at.desc())
                .limit(1)
            )
