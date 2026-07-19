from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import UUID

from shop_scout.adapters.base import AdapterRegistry
from shop_scout.constants import DEFAULT_VISION_VARIANT
from shop_scout.db.models import ProductRow, ProductRunRow, ShopRunRow
from shop_scout.db.repositories import RunRepository
from shop_scout.domain.enums import ProductRunStatus, ProductVerdict, RunStatus, ShopRunStatus
from shop_scout.domain.models import (
    ImageArtifact,
    ProductDecisionResult,
    ProductDetail,
    ProductRef,
    RunRequest,
    ShopContext,
    ShopIdentity,
    ShopInput,
    WebDetectionResult,
)
from shop_scout.domain.protocols import SourceAdapter, WebDetectionProvider
from shop_scout.exceptions import ManualActionRequiredError, VisionProviderError
from shop_scout.extraction.category import detail_category, provisional_category
from shop_scout.images.processor import process_image_bytes, safe_segment
from shop_scout.matching.rule_engine import decide_product
from shop_scout.matching.shop_policy import decide_shop, should_reject_early
from shop_scout.orchestration.catalog import CatalogBackend
from shop_scout.sampling.sampler import order_products

TERMINAL_PRODUCT_STATUSES = {
    ProductRunStatus.QUALIFIED,
    ProductRunStatus.REJECTED,
    ProductRunStatus.REVIEW,
    ProductRunStatus.SKIPPED_CATEGORY_QUOTA_REACHED,
    ProductRunStatus.SKIPPED_AFTER_SHOP_REJECTED,
}


class RunService:
    def __init__(
        self,
        *,
        repository: RunRepository,
        adapters: AdapterRegistry,
        catalog: CatalogBackend,
        vision: WebDetectionProvider,
        artifacts_dir: Path,
        max_pool_size: int,
        min_image_width: int,
        min_image_height: int,
        max_image_bytes: int,
        max_qualified_per_category: int,
        reject_rate_threshold: float,
        early_stop_min_searches: int,
        early_stop_confidence: float,
        max_search_error_rate: float,
        max_detail_products_per_batch: int,
        detail_page_interval_seconds: float,
        pause_after_screening: bool,
        early_stop: bool,
    ) -> None:
        self.repository = repository
        self.adapters = adapters
        self.catalog = catalog
        self.vision = vision
        self.artifacts_dir = artifacts_dir
        self.max_pool_size = max_pool_size
        self.min_image_width = min_image_width
        self.min_image_height = min_image_height
        self.max_image_bytes = max_image_bytes
        self.max_qualified_per_category = max_qualified_per_category
        self.reject_rate_threshold = reject_rate_threshold
        self.early_stop_min_searches = early_stop_min_searches
        self.early_stop_confidence = early_stop_confidence
        self.max_search_error_rate = max_search_error_rate
        self.max_detail_products_per_batch = max_detail_products_per_batch
        self.detail_page_interval_seconds = detail_page_interval_seconds
        self.pause_after_screening = pause_after_screening
        self.early_stop = early_stop
        self.crash_after_products: int | None = None
        self._processed_products = 0

    async def run(self, request: RunRequest) -> UUID:
        config = {
            "seed": request.seed,
            "mock_vision": request.mock_vision,
            "vision_provider": self.vision.name,
            "input_file_path": str(request.input_file_path),
            "shops": [item.model_dump(mode="json") for item in request.shops],
            "max_pool_size": self.max_pool_size,
            "max_qualified_per_category": self.max_qualified_per_category,
            "reject_rate_threshold": self.reject_rate_threshold,
            "early_stop_min_searches": self.early_stop_min_searches,
            "early_stop_confidence": self.early_stop_confidence,
            "max_search_error_rate": self.max_search_error_rate,
            "max_detail_products_per_batch": self.max_detail_products_per_batch,
            "detail_page_interval_seconds": self.detail_page_interval_seconds,
            "pause_after_screening": self.pause_after_screening,
            "early_stop": self.early_stop,
        }
        run = await self.repository.create_run(request, config)
        try:
            paused, reason = await self._process_run(run.id, request.shops, request.seed)
        except Exception as error:
            await self.repository.set_run_status(run.id, RunStatus.FAILED, str(error))
            raise
        await self.repository.set_run_status(
            run.id, RunStatus.PAUSED if paused else RunStatus.COMPLETED, reason
        )
        return run.id

    async def resume(self, run_id: UUID) -> RunStatus:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        shops = [ShopInput.model_validate(item) for item in run.config_snapshot_json["shops"]]
        await self.repository.set_run_status(run_id, RunStatus.RUNNING)
        try:
            paused, reason = await self._process_run(run_id, shops, run.seed)
        except Exception as error:
            await self.repository.set_run_status(run_id, RunStatus.FAILED, str(error))
            raise
        status = RunStatus.PAUSED if paused else RunStatus.COMPLETED
        await self.repository.set_run_status(run_id, status, reason)
        return status

    async def _process_run(
        self, run_id: UUID, shops: list[ShopInput], seed: int
    ) -> tuple[bool, str | None]:
        for shop_input in shops:
            adapter = self.adapters.for_url(str(shop_input.shop_url))
            identity = adapter.identify_shop_url(str(shop_input.shop_url))
            shop_run = await self.repository.get_or_create_shop_run(run_id, identity)
            if shop_run.status == ShopRunStatus.COMPLETED:
                continue
            try:
                pause_reason = await self._process_shop(
                    run_id, shop_run, adapter, identity, seed
                )
                if pause_reason:
                    return True, pause_reason
            except ManualActionRequiredError as error:
                await self.repository.mark_shop_manual_action(shop_run.id, str(error))
                await self.repository.add_event(
                    run_id,
                    "manual_action_required",
                    "Shop stopped because login or verification requires a human",
                    shop_run_id=shop_run.id,
                    metadata={"reason": str(error)},
                )
                return True, "MANUAL_ACTION_REQUIRED"
        return False, None

    async def _process_shop(
        self,
        run_id: UUID,
        shop_run: ShopRunRow,
        adapter: SourceAdapter,
        identity: ShopIdentity,
        seed: int,
    ) -> str | None:
        product_runs = await self.repository.load_product_runs(shop_run.id)
        if not product_runs:
            await self.repository.set_shop_stage(
                shop_run.id, ShopRunStatus.DISCOVERING_PRODUCTS
            )
            discovered = await self.catalog.collect_pool(identity, self.max_pool_size)
            order_seed, ordered = order_products(discovered, seed, identity.canonical_key)
            product_runs = await self.repository.save_products(
                shop_run.id,
                shop_run.shop_id,
                ordered,
                order_seed=order_seed,
                catalog_complete=len(discovered) < self.max_pool_size,
            )
        await self.repository.set_shop_stage(shop_run.id, ShopRunStatus.PROCESSING_PRODUCTS)
        for row in product_runs:
            if (
                row.status == ProductRunStatus.QUALIFIED
                and (not row.category_key or row.category_key == "uncategorized")
            ):
                await self.repository.set_product_stage(
                    row.id,
                    ProductRunStatus.QUALIFIED,
                    category_key=provisional_category(row.product.title),
                )
        product_runs = await self.repository.load_product_runs(shop_run.id)
        early_stopped = self._should_reject_shop_early(product_runs)

        # Phase 1 never opens product detail pages. It only screens public
        # listing images and persists a resumable verdict.
        screened_this_call = 0
        for index, product_run in enumerate(product_runs):
            status = ProductRunStatus(product_run.status)
            if status in TERMINAL_PRODUCT_STATUSES or status == ProductRunStatus.SCREENED_QUALIFIED:
                continue
            if early_stopped:
                await self._skip_remaining(product_runs[index:])
                break
            await self._screen_product(run_id, shop_run, product_run, identity, adapter)
            screened_this_call += 1
            self._processed_products += 1
            if self.crash_after_products == self._processed_products:
                raise RuntimeError("INJECTED_CRASH")
            product_runs = await self.repository.load_product_runs(shop_run.id)
            if self._should_reject_shop_early(product_runs):
                early_stopped = True
                await self._skip_remaining(product_runs[index + 1 :])
                break

        product_runs = await self.repository.load_product_runs(shop_run.id)
        if early_stopped:
            await self._save_final_shop_decision(shop_run, product_runs, early_stopped=True)
            return None

        # Reserve at most N candidates per provisional title category before
        # any detail navigation. This is deterministic across resume calls.
        reserved: dict[str, int] = {}
        for row in product_runs:
            if row.status == ProductRunStatus.QUALIFIED:
                category = row.category_key or provisional_category(row.product.title)
                reserved[category] = reserved.get(category, 0) + 1
        for row in product_runs:
            if row.status != ProductRunStatus.SCREENED_QUALIFIED:
                continue
            category = row.category_key or provisional_category(row.product.title)
            await self.repository.set_product_stage(
                row.id, ProductRunStatus.SCREENED_QUALIFIED, category_key=category
            )
            if reserved.get(category, 0) >= self.max_qualified_per_category:
                await self.repository.set_product_stage(
                    row.id,
                    ProductRunStatus.SKIPPED_CATEGORY_QUOTA_REACHED,
                    category_key=category,
                )
            else:
                reserved[category] = reserved.get(category, 0) + 1

        # Phase 2 is rate-limited and persists after every product. A positive
        # batch limit is an optional operator safeguard; zero runs continuously.
        product_runs = await self.repository.load_product_runs(shop_run.id)
        if (
            self.pause_after_screening
            and screened_this_call
            and any(row.status == ProductRunStatus.SCREENED_QUALIFIED for row in product_runs)
        ):
            await self.repository.pause_shop(shop_run.id, "SCREENING_PHASE_COMPLETED")
            await self.repository.add_event(
                run_id,
                "screening_phase_paused",
                "Listing-image screening completed; explicit resume is required before details",
                shop_run_id=shop_run.id,
                metadata={"screened_in_call": screened_this_call},
            )
            return "SCREENING_PHASE_COMPLETED"

        detail_count = 0
        for row in product_runs:
            if row.status != ProductRunStatus.SCREENED_QUALIFIED:
                continue
            if (
                self.max_detail_products_per_batch > 0
                and detail_count >= self.max_detail_products_per_batch
            ):
                await self.repository.pause_shop(shop_run.id, "DETAIL_BATCH_LIMIT_REACHED")
                await self.repository.add_event(
                    run_id,
                    "detail_batch_paused",
                    "Detail batch limit reached; explicit resume is required",
                    shop_run_id=shop_run.id,
                    metadata={"processed_in_batch": detail_count},
                )
                return "DETAIL_BATCH_LIMIT_REACHED"
            if detail_count:
                await asyncio.sleep(self.detail_page_interval_seconds)
            await self._archive_screened_product(run_id, shop_run, row, identity, adapter)
            detail_count += 1

        completed = await self.repository.load_product_runs(shop_run.id)
        await self._save_final_shop_decision(shop_run, completed, early_stopped=False)
        return None

    def _should_reject_shop_early(self, rows: list[ProductRunRow]) -> bool:
        if not self.early_stop:
            return False
        stats = _stats(rows)
        return should_reject_early(
            exact_count=stats.exact_count,
            search_success_count=stats.search_success_count,
            minimum_searches=self.early_stop_min_searches,
            reject_rate_threshold=self.reject_rate_threshold,
            confidence=self.early_stop_confidence,
        )

    async def _save_final_shop_decision(
        self, shop_run: ShopRunRow, rows: list[ProductRunRow], *, early_stopped: bool
    ) -> None:
        stats = _stats(rows)
        context = ShopContext(
            discovered_count=len(rows),
            processed_count=stats.processed_count,
            search_success_count=stats.search_success_count,
            exact_count=stats.exact_count,
            qualified_count=stats.qualified_count,
            skipped_count=stats.skipped_count,
            error_count=stats.error_count,
            catalog_complete=shop_run.catalog_complete,
            early_stopped=early_stopped,
            reject_rate_threshold=self.reject_rate_threshold,
            max_search_error_rate=self.max_search_error_rate,
        )
        await self.repository.save_shop_decision(shop_run.id, decide_shop(context))

    async def _skip_remaining(self, rows: list[ProductRunRow]) -> None:
        for row in rows:
            if ProductRunStatus(row.status) not in TERMINAL_PRODUCT_STATUSES:
                await self.repository.set_product_stage(
                    row.id, ProductRunStatus.SKIPPED_AFTER_SHOP_REJECTED
                )

    async def _screen_product(
        self,
        run_id: UUID,
        shop_run: ShopRunRow,
        product_run: ProductRunRow,
        identity: ShopIdentity,
        adapter: SourceAdapter,
    ) -> None:
        product = _product_ref(product_run.product)
        output_dir = (
            self.artifacts_dir
            / str(run_id)
            / "shops"
            / safe_segment(identity.canonical_key)
            / "products"
            / safe_segment(product.external_item_id)
        )
        source_image_url = product.listing_image_url
        if not source_image_url:
            decision = decide_product(
                None,
                lambda url: adapter.classify_relation(identity, product, url),
                source_image_url=product.canonical_url,
                error_code="LISTING_IMAGE_MISSING",
            )
            await self.repository.save_decision(product_run.id, decision, None)
            await self.repository.set_product_stage(
                product_run.id, ProductRunStatus.REVIEW, "LISTING_IMAGE_MISSING"
            )
            return
        await self.repository.set_product_stage(
            product_run.id, ProductRunStatus.PREPARING_SCREEN_IMAGE
        )
        try:
            if product_run.screening_image is not None:
                screen_image = _screening_image(product_run)
            else:
                screen_image = await self._prepare_image(
                    source_image_url,
                    product.canonical_url,
                    output_dir / "screening-listing",
                )
                await self.repository.save_screening_image(product_run.id, screen_image)
        except Exception as error:
            decision = decide_product(
                None,
                lambda url: adapter.classify_relation(identity, product, url),
                source_image_url=source_image_url,
                error_code=f"IMAGE_ERROR_{type(error).__name__.upper()}",
            )
            await self.repository.save_decision(product_run.id, decision, None)
            await self.repository.set_product_stage(
                product_run.id, ProductRunStatus.REVIEW, str(error)
            )
            return
        decision, query_id = await self._screen(
            run_id, shop_run, product_run, identity, product, adapter, screen_image
        )
        if decision.verdict != ProductVerdict.NO_INDEXED_MATCH_FOUND:
            await self.repository.save_decision(product_run.id, decision, query_id)
            status = (
                ProductRunStatus.REJECTED
                if decision.verdict == ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH
                else ProductRunStatus.REVIEW
            )
            await self.repository.set_product_stage(product_run.id, status)
            return
        await self.repository.save_decision(product_run.id, decision, query_id)
        await self.repository.set_product_stage(
            product_run.id,
            ProductRunStatus.SCREENED_QUALIFIED,
            category_key=provisional_category(product.title),
        )

    async def _archive_screened_product(
        self,
        run_id: UUID,
        shop_run: ShopRunRow,
        product_run: ProductRunRow,
        identity: ShopIdentity,
        adapter: SourceAdapter,
    ) -> None:
        product = _product_ref(product_run.product)
        output_dir = (
            self.artifacts_dir
            / str(run_id)
            / "shops"
            / safe_segment(identity.canonical_key)
            / "products"
            / safe_segment(product.external_item_id)
        )
        if product_run.screening_image is None or product_run.verdict is None:
            raise RuntimeError("SCREENED_PRODUCT_STATE_INCOMPLETE")
        screen_image = _screening_image(product_run)
        decision = _decision_from_row(product_run)
        query_id: UUID | None = None
        source_image_url = screen_image.source_url
        await self.repository.set_product_stage(
            product_run.id, ProductRunStatus.EXTRACTING_DETAIL
        )
        try:
            detail = await self.catalog.extract_detail(identity, product)
        except ManualActionRequiredError as error:
            await self.repository.set_product_stage(
                product_run.id,
                ProductRunStatus.SCREENED_QUALIFIED,
                str(error),
            )
            raise
        except Exception as error:
            decision = decide_product(
                None,
                lambda url: adapter.classify_relation(identity, product, url),
                source_image_url=source_image_url,
                error_code=f"DETAIL_ERROR_{type(error).__name__.upper()}",
            )
            await self.repository.save_decision(product_run.id, decision, None)
            await self.repository.set_product_stage(
                product_run.id, ProductRunStatus.REVIEW, str(error)
            )
            return
        if detail.main_image_url != source_image_url:
            await self.repository.set_product_stage(
                product_run.id, ProductRunStatus.SEARCHING_DETAIL_IMAGE
            )
            try:
                detail_image = await self._prepare_image(
                    detail.main_image_url,
                    detail.canonical_url,
                    output_dir / "screening-detail",
                )
            except Exception as error:
                await self.repository.add_event(
                    run_id,
                    "detail_image_fallback",
                    "Invalid detail image; retained the screened listing image",
                    shop_run_id=shop_run.id,
                    product_run_id=product_run.id,
                    metadata={"error_type": type(error).__name__},
                )
                detail = detail.model_copy(
                    update={
                        "main_image_url": source_image_url,
                        "image_urls": list(
                            dict.fromkeys([source_image_url, *detail.image_urls])
                        ),
                        "source": "listing_fallback",
                    }
                )
                detail_image = None
            if detail_image is not None:
                decision, query_id = await self._screen(
                    run_id, shop_run, product_run, identity, product, adapter, detail_image
                )
                if decision.verdict != ProductVerdict.NO_INDEXED_MATCH_FOUND:
                    await self.repository.save_decision(product_run.id, decision, query_id)
                    status = (
                        ProductRunStatus.REJECTED
                        if decision.verdict == ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH
                        else ProductRunStatus.REVIEW
                    )
                    await self.repository.set_product_stage(product_run.id, status)
                    return
                screen_image = detail_image
        category_key = detail_category(
            detail.category_path,
            product_run.category_key or provisional_category(product.title),
        )
        await self.repository.set_product_stage(
            product_run.id, ProductRunStatus.ARCHIVING, category_key=category_key
        )
        category_count = await self.repository.category_qualified_count(
            shop_run.id, category_key
        )
        if category_count >= self.max_qualified_per_category:
            await self.repository.save_decision(product_run.id, decision, query_id)
            await self.repository.set_product_stage(
                product_run.id,
                ProductRunStatus.SKIPPED_CATEGORY_QUOTA_REACHED,
                category_key=category_key,
            )
            return
        assets = await self._archive_detail(detail, output_dir, screen_image)
        detail_json_path = output_dir / "product.json"
        raw_html_path = output_dir / "evidence" / "raw.html" if detail.raw_html else None
        detail_json_path.parent.mkdir(parents=True, exist_ok=True)
        detail_json_path.write_text(
            json.dumps(
                detail.model_dump(mode="json", exclude={"raw_html"}),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if raw_html_path and detail.raw_html:
            raw_html_path.parent.mkdir(parents=True, exist_ok=True)
            raw_html_path.write_text(detail.raw_html, encoding="utf-8")
        await self.repository.save_archive(
            product_run.id, detail, detail_json_path, raw_html_path, assets
        )
        await self.repository.save_decision(product_run.id, decision, query_id)
        await self.repository.set_product_stage(
            product_run.id, ProductRunStatus.QUALIFIED, category_key=category_key
        )
        await self.repository.add_event(
            run_id,
            "product_qualified",
            "Product passed exact-match screening and was archived",
            shop_run_id=shop_run.id,
            product_run_id=product_run.id,
            metadata={"category": category_key},
        )

    async def _screen(
        self,
        run_id: UUID,
        shop_run: ShopRunRow,
        product_run: ProductRunRow,
        identity: ShopIdentity,
        product: ProductRef,
        adapter: SourceAdapter,
        image: ImageArtifact,
    ) -> tuple[ProductDecisionResult, UUID | None]:
        await self.repository.set_product_stage(
            product_run.id, ProductRunStatus.SEARCHING_LISTING_IMAGE
        )
        duplicate = await self.repository.find_cross_shop_image(image.sha256, shop_run.shop_id)
        if duplicate:
            return (
                decide_product(
                    None,
                    lambda url: adapter.classify_relation(identity, product, url),
                    source_image_url=image.source_url,
                    local_cross_shop_url=duplicate[1].canonical_url,
                ),
                None,
            )
        result, query_id, error_code = await self._vision_result(run_id, image)
        return (
            decide_product(
                result,
                lambda url: adapter.classify_relation(identity, product, url),
                source_image_url=image.source_url,
                error_code=error_code,
            ),
            query_id,
        )

    async def _prepare_image(
        self,
        image_url: str,
        referer_url: str,
        output_dir: Path,
        *,
        normalized_name: str | None = None,
        raw_output_dir: Path | None = None,
        role: str = "gallery",
    ) -> ImageArtifact:
        content, content_type = await self.catalog.fetch_image_url(image_url, referer_url)
        return process_image_bytes(
            content,
            source_url=image_url,
            output_dir=output_dir,
            content_type=content_type,
            min_width=self.min_image_width,
            min_height=self.min_image_height,
            max_bytes=self.max_image_bytes,
            normalized_name=normalized_name,
            raw_output_dir=raw_output_dir,
            role=role,
        )

    async def _archive_detail(
        self, detail: ProductDetail, output_dir: Path, screened: ImageArtifact
    ) -> list[ImageArtifact]:
        images_dir = output_dir / "images"
        originals_dir = output_dir / "evidence" / "original-images"
        images_dir.mkdir(parents=True, exist_ok=True)
        originals_dir.mkdir(parents=True, exist_ok=True)
        main_name = "001-main.jpg"
        main_normalized = images_dir / main_name
        main_raw = originals_dir / "001-main.raw"
        shutil.copy2(screened.normalized_path, main_normalized)
        shutil.copy2(screened.raw_path, main_raw)
        assets = [
            screened.model_copy(
                update={
                    "normalized_path": main_normalized,
                    "raw_path": main_raw,
                    "role": "main",
                }
            )
        ]
        seen_hashes = {screened.sha256}
        seen_phashes = {screened.phash}
        image_urls = dict.fromkeys(detail.image_urls or [detail.main_image_url])
        for image_url in image_urls:
            if image_url == screened.source_url:
                continue
            role = detail.image_roles.get(image_url, "gallery")
            position = len(assets) + 1
            filename = f"{position:03d}-{safe_segment(role)}.jpg"
            try:
                candidate = await self._prepare_image(
                    image_url,
                    detail.canonical_url,
                    images_dir,
                    normalized_name=filename,
                    raw_output_dir=originals_dir,
                    role=role,
                )
            except Exception:
                continue
            if candidate.sha256 in seen_hashes or candidate.phash in seen_phashes:
                candidate.normalized_path.unlink(missing_ok=True)
                candidate.raw_path.unlink(missing_ok=True)
                continue
            seen_hashes.add(candidate.sha256)
            seen_phashes.add(candidate.phash)
            assets.append(candidate)
        sources_path = output_dir / "evidence" / "image-sources.json"
        sources_path.write_text(
            json.dumps(
                [
                    {
                        "position": index,
                        "role": asset.role,
                        "source_url": asset.source_url,
                        "sha256": asset.sha256,
                        "phash": asset.phash,
                        "width": asset.width,
                        "height": asset.height,
                        "normalized_path": str(asset.normalized_path),
                    }
                    for index, asset in enumerate(assets, start=1)
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return assets

    async def _vision_result(
        self, run_id: UUID, image: ImageArtifact
    ) -> tuple[WebDetectionResult | None, UUID | None, str | None]:
        cached = await self.repository.get_vision_cache(
            self.vision.name, image.sha256, DEFAULT_VISION_VARIANT
        )
        if cached and cached.result_json:
            return WebDetectionResult.model_validate(cached.result_json), cached.id, None
        try:
            result = await self.vision.detect(
                image, run_id=run_id, output_dir=self.artifacts_dir / str(run_id) / "vision"
            )
        except VisionProviderError as error:
            await self.repository.save_vision_failure(
                self.vision.name,
                image.sha256,
                DEFAULT_VISION_VARIANT,
                error.code,
                str(error),
            )
            return None, None, error.code
        query = await self.repository.save_vision_success(result, DEFAULT_VISION_VARIANT)
        return result, query.id, None


class _Stats:
    def __init__(self) -> None:
        self.processed_count = 0
        self.search_success_count = 0
        self.exact_count = 0
        self.qualified_count = 0
        self.skipped_count = 0
        self.error_count = 0


def _stats(rows: list[ProductRunRow]) -> _Stats:
    stats = _Stats()
    for row in rows:
        status = ProductRunStatus(row.status)
        if (
            status in TERMINAL_PRODUCT_STATUSES
            and status != ProductRunStatus.SKIPPED_AFTER_SHOP_REJECTED
        ):
            stats.processed_count += 1
        if status in {
            ProductRunStatus.SKIPPED_CATEGORY_QUOTA_REACHED,
            ProductRunStatus.SKIPPED_AFTER_SHOP_REJECTED,
        }:
            stats.skipped_count += 1
        if status == ProductRunStatus.QUALIFIED:
            stats.qualified_count += 1
        if row.verdict is None:
            continue
        verdict = ProductVerdict(row.verdict.verdict)
        if verdict == ProductVerdict.SEARCH_ERROR:
            stats.error_count += 1
        else:
            stats.search_success_count += 1
        if verdict == ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH:
            stats.exact_count += 1
    return stats


def _product_ref(row: ProductRow) -> ProductRef:
    return ProductRef(
        external_item_id=row.external_item_id,
        canonical_url=row.canonical_url,
        title=row.title,
        listing_image_url=row.listing_image_url,
        source_position=0,
        metadata=row.metadata_json,
    )


def _screening_image(row: ProductRunRow) -> ImageArtifact:
    image = row.screening_image
    if image is None:
        raise RuntimeError("SCREENING_IMAGE_MISSING")
    return ImageArtifact(
        source_url=image.source_url,
        raw_path=Path(image.raw_path),
        normalized_path=Path(image.normalized_path),
        sha256=image.sha256,
        phash=image.phash,
        width=image.width,
        height=image.height,
        file_size=image.file_size,
        content_type=image.content_type,
    )


def _decision_from_row(row: ProductRunRow) -> ProductDecisionResult:
    verdict = row.verdict
    if verdict is None:
        raise RuntimeError("PRODUCT_VERDICT_MISSING")
    return ProductDecisionResult(
        verdict=ProductVerdict(verdict.verdict),
        reason_code=verdict.reason_code,
        summary=verdict.summary,
        evidence=[],
        confidence=verdict.confidence,
    )
