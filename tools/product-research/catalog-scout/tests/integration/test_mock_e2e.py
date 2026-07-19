from pathlib import Path

import pytest

from storewright_catalog_scout.adapters.base import AdapterRegistry
from storewright_catalog_scout.adapters.taobao import TaobaoAdapter
from storewright_catalog_scout.domain.enums import RunStatus, ShopDecision
from storewright_catalog_scout.domain.models import RunRequest, ShopInput
from storewright_catalog_scout.orchestration.archive_rebuilder import OfflineArchiveRebuilder
from storewright_catalog_scout.orchestration.catalog import FixtureCatalogBackend
from storewright_catalog_scout.orchestration.run_service import RunService
from storewright_catalog_scout.reporting.report import ReportGenerator
from storewright_catalog_scout.vision.mock import MockVisionProvider


def service(
    repository,
    tmp_path: Path,
    provider: MockVisionProvider,
    *,
    product_count: int = 5,
    scenarios=None,
    category_quota: int = 20,
    early_minimum: int = 10,
    detail_batch: int = 100,
    pause_after_screening: bool = False,
) -> RunService:
    return RunService(
        repository=repository,
        adapters=AdapterRegistry([TaobaoAdapter()]),
        catalog=FixtureCatalogBackend(product_count=product_count, scenarios=scenarios),
        vision=provider,
        artifacts_dir=tmp_path / "artifacts",
        max_pool_size=100,
        min_image_width=300,
        min_image_height=300,
        max_image_bytes=2_000_000,
        max_qualified_per_category=category_quota,
        reject_rate_threshold=0.60,
        early_stop_min_searches=early_minimum,
        early_stop_confidence=0.90,
        max_search_error_rate=0.20,
        max_detail_products_per_batch=detail_batch,
        detail_page_interval_seconds=0,
        pause_after_screening=pause_after_screening,
        early_stop=True,
    )


def request(tmp_path: Path) -> RunRequest:
    return RunRequest(
        shops=[ShopInput(shop_url="https://shop.example.taobao.com/")],
        seed=20260718,
        mock_vision=True,
        input_file_path=tmp_path / "shops.csv",
        confirm_authorized=True,
    )


async def test_mock_streaming_end_to_end_and_offline_report(repository, tmp_path: Path) -> None:
    provider = MockVisionProvider()
    run_id = await service(repository, tmp_path, provider).run(request(tmp_path))
    run = await repository.get_run(run_id)
    assert run and run.status == RunStatus.COMPLETED
    rows = await repository.report_rows(run_id)
    assert rows[0].decision == ShopDecision.CANDIDATE
    assert rows[0].qualified_count == 5
    assert all(item.detail_archived for item in rows[0].product_runs)
    assert provider.call_count == 5
    paths = await ReportGenerator(repository, tmp_path / "artifacts").generate(run_id)
    assert all(
        path.is_file()
        for path in [paths.shops_csv, paths.products_csv, paths.html, paths.summary_json]
    )
    assert "流式筛选" in paths.html.read_text()
    assert "检索原始响应" in paths.html.read_text()


async def test_offline_archive_rebuild_is_repeatable(repository, tmp_path: Path) -> None:
    provider = MockVisionProvider()
    run_id = await service(repository, tmp_path, provider, product_count=1).run(request(tmp_path))
    rebuilder = OfflineArchiveRebuilder(
        repository,
        AdapterRegistry([TaobaoAdapter()]),
        tmp_path / "artifacts",
    )
    assert await rebuilder.rebuild(run_id) == {"rebuilt": 1, "skipped": 0}
    assert await rebuilder.rebuild(run_id) == {"rebuilt": 1, "skipped": 0}
    product_run = (await repository.report_rows(run_id))[0].product_runs[0]
    assert product_run.detail_archived
    assert product_run.snapshot is not None
    images_dir = Path(product_run.snapshot.detail_json_path).parent / "images"
    assert all(path.is_file() for path in images_dir.iterdir())
    assert not any(path.is_dir() for path in images_dir.iterdir())


async def test_category_quota_archives_only_twenty_or_configured_limit(
    repository, tmp_path: Path
) -> None:
    provider = MockVisionProvider()
    run_id = await service(
        repository, tmp_path, provider, product_count=8, category_quota=2
    ).run(request(tmp_path))
    shop = (await repository.report_rows(run_id))[0]
    assert shop.qualified_count == 4
    assert sum(item.status == "skipped_category_quota_reached" for item in shop.product_runs) == 4
    assert provider.call_count == 8


async def test_changed_detail_main_image_is_screened_before_archive(
    repository, tmp_path: Path
) -> None:
    class ChangedMainCatalog(FixtureCatalogBackend):
        async def extract_detail(self, shop, product):
            detail = await super().extract_detail(shop, product)
            changed = (
                f"https://fixtures.invalid/images/{product.external_item_id}-detail.png"
                "?scenario=external_full"
            )
            return detail.model_copy(
                update={"main_image_url": changed, "image_urls": [changed]}
            )

    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider, product_count=1)
    runner.catalog = ChangedMainCatalog(product_count=1, scenarios=["empty"])
    run_id = await runner.run(request(tmp_path))
    product_run = (await repository.report_rows(run_id))[0].product_runs[0]
    assert product_run.status == "rejected"
    assert not product_run.detail_archived
    assert provider.call_count == 2


async def test_invalid_detail_image_falls_back_to_screened_listing_image(
    repository, tmp_path: Path
) -> None:
    class SmallDetailCatalog(FixtureCatalogBackend):
        async def extract_detail(self, shop, product):
            detail = await super().extract_detail(shop, product)
            changed = f"https://fixtures.invalid/images/{product.external_item_id}-small.png"
            return detail.model_copy(
                update={"main_image_url": changed, "image_urls": [changed]}
            )

        async def fetch_image_url(self, image_url, referer_url):
            if "-small.png" not in image_url:
                return await super().fetch_image_url(image_url, referer_url)
            from io import BytesIO

            from PIL import Image

            output = BytesIO()
            Image.new("RGB", (100, 100), "white").save(output, "PNG")
            return output.getvalue(), "image/png"

    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider, product_count=1)
    runner.catalog = SmallDetailCatalog(product_count=1, scenarios=["empty"])
    run_id = await runner.run(request(tmp_path))
    product_run = (await repository.report_rows(run_id))[0].product_runs[0]
    assert product_run.status == "qualified"
    assert product_run.detail_archived
    assert provider.call_count == 1


async def test_crash_resume_preserves_order_and_vision_cache(repository, tmp_path: Path) -> None:
    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider)
    runner.crash_after_products = 1
    with pytest.raises(RuntimeError, match="INJECTED_CRASH"):
        await runner.run(request(tmp_path))
    from sqlalchemy import select

    from storewright_catalog_scout.db.models import RunRow

    async with repository.sessions() as session:
        run_id = await session.scalar(select(RunRow.id))
    assert run_id is not None
    first_calls = provider.call_count
    runner.crash_after_products = None
    await runner.resume(run_id)
    assert provider.call_count == first_calls + 4
    rows = await repository.report_rows(run_id)
    assert [item.processing_index for item in rows[0].product_runs] == [0, 1, 2, 3, 4]


async def test_detail_batch_pauses_and_requires_explicit_resume(repository, tmp_path: Path) -> None:
    provider = MockVisionProvider()
    runner = service(
        repository, tmp_path, provider, product_count=6, detail_batch=2
    )
    run_id = await runner.run(request(tmp_path))
    run = await repository.get_run(run_id)
    rows = await repository.report_rows(run_id)
    assert run and run.status == RunStatus.PAUSED
    assert run.last_error == "DETAIL_BATCH_LIMIT_REACHED"
    assert sum(item.status == "qualified" for item in rows[0].product_runs) == 2
    assert sum(item.status == "screened_qualified" for item in rows[0].product_runs) == 4
    assert provider.call_count == 6  # all listing images were screened before details

    assert await runner.resume(run_id) == RunStatus.PAUSED
    assert await runner.resume(run_id) == RunStatus.COMPLETED
    rows = await repository.report_rows(run_id)
    assert sum(item.status == "qualified" for item in rows[0].product_runs) == 6
    assert provider.call_count == 6


async def test_zero_detail_batch_runs_all_products_without_pause(
    repository, tmp_path: Path
) -> None:
    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider, product_count=6, detail_batch=0)
    run_id = await runner.run(request(tmp_path))
    run = await repository.get_run(run_id)
    rows = await repository.report_rows(run_id)
    assert run and run.status == RunStatus.COMPLETED
    assert all(item.status == "qualified" for item in rows[0].product_runs)
    assert all(item.detail_archived for item in rows[0].product_runs)
    assert provider.call_count == 6


async def test_screening_phase_pauses_before_any_detail_navigation(
    repository, tmp_path: Path
) -> None:
    provider = MockVisionProvider()
    runner = service(
        repository,
        tmp_path,
        provider,
        product_count=4,
        pause_after_screening=True,
    )
    run_id = await runner.run(request(tmp_path))
    run = await repository.get_run(run_id)
    rows = await repository.report_rows(run_id)
    assert run and run.status == RunStatus.PAUSED
    assert run.last_error == "SCREENING_PHASE_COMPLETED"
    assert all(item.status == "screened_qualified" for item in rows[0].product_runs)
    assert not any(item.detail_archived for item in rows[0].product_runs)
    assert await runner.resume(run_id) == RunStatus.COMPLETED


async def test_manual_action_during_detail_pauses_entire_run(repository, tmp_path: Path) -> None:
    class LoginCatalog(FixtureCatalogBackend):
        async def extract_detail(self, shop, product):
            from storewright_catalog_scout.exceptions import ManualActionRequiredError

            raise ManualActionRequiredError("login redirect")

    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider, product_count=3)
    runner.catalog = LoginCatalog(product_count=3)
    run_id = await runner.run(request(tmp_path))
    run = await repository.get_run(run_id)
    rows = await repository.report_rows(run_id)
    assert run and run.status == RunStatus.PAUSED
    assert run.last_error == "MANUAL_ACTION_REQUIRED"
    assert rows[0].status == "manual_action_required"
    assert all(item.status == "screened_qualified" for item in rows[0].product_runs)
    assert provider.call_count == 3


async def test_risk_cooldown_during_detail_pauses_without_losing_candidate(
    repository, tmp_path: Path
) -> None:
    class RiskCatalog(FixtureCatalogBackend):
        async def extract_detail(self, shop, product):
            from storewright_catalog_scout.exceptions import RiskCooldownRequiredError

            raise RiskCooldownRequiredError("DETAIL_HTTP_429", "2026-07-19T01:00:00+00:00")

    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider, product_count=3)
    runner.catalog = RiskCatalog(product_count=3)
    run_id = await runner.run(request(tmp_path))
    run = await repository.get_run(run_id)
    rows = await repository.report_rows(run_id)

    assert run and run.status == RunStatus.PAUSED
    assert run.last_error == "DETAIL_HTTP_429"
    assert rows[0].status == "paused"
    assert all(item.status == "screened_qualified" for item in rows[0].product_runs)


async def test_high_rejection_rate_stops_remaining_searches(repository, tmp_path: Path) -> None:
    provider = MockVisionProvider()
    runner = service(
        repository,
        tmp_path,
        provider,
        product_count=12,
        scenarios=["external_full"] * 12,
        early_minimum=5,
    )
    run_id = await runner.run(request(tmp_path))
    shop = (await repository.report_rows(run_id))[0]
    assert shop.decision == ShopDecision.REJECTED
    assert shop.early_stopped
    assert shop.exact_count == 5
    assert shop.processed_count == 5
    assert 0 < provider.call_count <= 5  # identical image hashes reuse the provider cache
    assert sum(item.status == "skipped_after_shop_rejected" for item in shop.product_runs) == 7


async def test_manual_action_stops_shop_without_searching(repository, tmp_path: Path) -> None:
    class ManualCatalog(FixtureCatalogBackend):
        async def collect_pool(self, shop, max_items):
            from storewright_catalog_scout.exceptions import ManualActionRequiredError

            raise ManualActionRequiredError("verification detected")

    provider = MockVisionProvider()
    runner = service(repository, tmp_path, provider)
    runner.catalog = ManualCatalog()
    run_id = await runner.run(request(tmp_path))
    shop = (await repository.report_rows(run_id))[0]
    assert shop.status == "manual_action_required"
    assert shop.decision == ShopDecision.REVIEW
    assert provider.call_count == 0
