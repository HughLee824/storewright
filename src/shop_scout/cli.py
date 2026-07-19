from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy.ext.asyncio import AsyncEngine

from shop_scout.adapters.base import AdapterRegistry
from shop_scout.adapters.taobao import TaobaoAdapter
from shop_scout.browser.cdp import PlaywrightCatalogBackend
from shop_scout.browser.chrome import ChromeProcessManager
from shop_scout.config import Settings
from shop_scout.db.migrations import upgrade_database
from shop_scout.db.repositories import RunRepository
from shop_scout.db.session import create_engine, create_session_factory
from shop_scout.domain.models import RunRequest, ShopInput
from shop_scout.logging import configure_logging
from shop_scout.orchestration.archive_rebuilder import OfflineArchiveRebuilder
from shop_scout.orchestration.catalog import FixtureCatalogBackend
from shop_scout.orchestration.run_service import RunService
from shop_scout.reporting.report import ReportGenerator
from shop_scout.vision.factory import create_vision_provider
from shop_scout.vision.mock import MockVisionProvider

app = typer.Typer(help="Auditable external image-match screening for authorized shops.")
browser_app = typer.Typer(help="Manage the dedicated local Chrome profile.")
review_app = typer.Typer(help="Inspect items that need human review.")
app.add_typer(browser_app, name="browser")
app.add_typer(review_app, name="review")
console = Console()


def _settings() -> Settings:
    configure_logging()
    return Settings()


async def _repository(settings: Settings) -> tuple[RunRepository, AsyncEngine]:
    await asyncio.to_thread(upgrade_database, settings.database_url)
    engine = create_engine(settings.database_url)
    return RunRepository(create_session_factory(engine)), engine


def _load_shops(path: Path) -> list[ShopInput]:
    if not path.is_file():
        raise typer.BadParameter(f"CSV does not exist: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    shops: list[ShopInput] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        if not row.get("shop_url"):
            raise typer.BadParameter(f"Missing shop_url on CSV line {index}")
        url = row["shop_url"].strip()
        if url not in seen:
            seen.add(url)
            shops.append(ShopInput(shop_url=url))
    return shops


def _service(
    settings: Settings,
    repository: RunRepository,
    *,
    mock_vision: bool,
    catalog: FixtureCatalogBackend | PlaywrightCatalogBackend,
    early_stop: bool,
) -> RunService:
    provider = MockVisionProvider() if mock_vision else create_vision_provider(settings)
    return RunService(
        repository=repository,
        adapters=AdapterRegistry([TaobaoAdapter()]),
        catalog=catalog,
        vision=provider,
        artifacts_dir=settings.artifacts_dir,
        max_pool_size=settings.max_pool_size,
        min_image_width=settings.min_image_width,
        min_image_height=settings.min_image_height,
        max_image_bytes=settings.max_image_bytes,
        max_qualified_per_category=settings.max_qualified_products_per_category,
        reject_rate_threshold=settings.shop_reject_rate_threshold,
        early_stop_min_searches=settings.early_stop_min_searches,
        early_stop_confidence=settings.early_stop_confidence,
        max_search_error_rate=settings.max_search_error_rate,
        max_detail_products_per_batch=settings.max_detail_products_per_batch,
        detail_page_interval_seconds=settings.detail_page_interval_seconds,
        pause_after_screening=settings.pause_after_screening,
        early_stop=early_stop,
    )


@app.command("init")
def init_command() -> None:
    """Create runtime directories and initialize the SQLite schema."""

    async def execute() -> None:
        settings = _settings()
        settings.ensure_directories()
        await asyncio.to_thread(upgrade_database, settings.database_url)
        manager = ChromeProcessManager(settings)
        console.print(f"Database initialized: {settings.database_url}")
        chrome = manager.discover()
        console.print(f"Chrome: {chrome or 'not found (set CHROME_EXECUTABLE)'}")
        console.print("Next: shop-scout browser login, then shop-scout browser diagnose")

    asyncio.run(execute())


@browser_app.command("login")
def browser_login(
    url: Annotated[str, typer.Option(help="Initial login URL.")] = "https://www.taobao.com/",
) -> None:
    """Open the dedicated profile for manual login; never reads cookies."""

    async def execute() -> None:
        settings = _settings()
        settings.ensure_directories()
        manager = ChromeProcessManager(settings)
        await manager.start(url)
        console.print("请在专用 Chrome 窗口手工登录。程序不会读取或打印 Cookie。")
        await asyncio.to_thread(input, "完成后按 Enter 关闭本次启动的 Chrome：")
        await manager.stop()

    asyncio.run(execute())


@browser_app.command("diagnose")
def browser_diagnose() -> None:
    """Check browser, storage and configured providers without exposing secrets."""

    async def execute() -> None:
        settings = _settings()
        settings.ensure_directories()
        repository, engine = await _repository(settings)
        del repository
        manager = ChromeProcessManager(settings)
        cdp_ready = await manager.is_cdp_ready()
        playwright_result = "未检查（CDP 未运行）"
        browser_use_result = "未检查（CDP 未运行）"
        page_kind = "unknown"
        if cdp_ready:
            try:
                from playwright.async_api import async_playwright

                playwright = await async_playwright().start()
                browser = await playwright.chromium.connect_over_cdp(settings.cdp_url)
                pages = [page for context in browser.contexts for page in context.pages]
                if pages:
                    from shop_scout.browser.page_state import classify_page_state

                    active = pages[-1]
                    page_kind = classify_page_state(
                        active.url, await active.title(), await active.content()
                    )
                playwright_result = "已连接"
                await playwright.stop()
            except Exception as error:
                playwright_result = f"失败：{type(error).__name__}"
            try:
                from browser_use import Browser

                browser_use = Browser(
                    cdp_url=settings.cdp_url,
                    keep_alive=True,
                    allowed_domains=["*.taobao.com", "*.tmall.com"],
                )
                await browser_use.start()
                await browser_use.stop()
                browser_use_result = "已连接"
            except Exception as error:
                browser_use_result = f"失败：{type(error).__name__}"
        table = Table("检查", "结果")
        table.add_row("Chrome", str(manager.discover() or "未找到"))
        table.add_row("Profile 可写", str(settings.chrome_user_data_dir.is_dir()))
        table.add_row("CDP (127.0.0.1)", "已连接" if cdp_ready else "未运行")
        table.add_row("Playwright", playwright_result)
        table.add_row("Browser Use", browser_use_result)
        table.add_row(
            "导航模型",
            f"{settings.browser_use_provider}/{settings.browser_use_model or '默认模型'}",
        )
        navigation_key = (
            settings.deepseek_api_key
            if settings.browser_use_provider == "deepseek"
            else settings.browser_use_api_key
        )
        table.add_row("导航 API key", "已配置" if navigation_key else "未配置")
        table.add_row("图像检索", "SerpApi Google Lens")
        table.add_row(
            "SerpApi key",
            "已配置" if settings.serpapi_api_key else "未配置",
        )
        table.add_row("当前页面分类", str(page_kind))
        table.add_row("SQLite", "可写")
        console.print(table)
        await engine.dispose()

    asyncio.run(execute())


@app.command("run")
def run_command(
    shops: Annotated[Path, typer.Option(exists=True, dir_okay=False, help="Authorized shops CSV")],
    seed: Annotated[int, typer.Option()] = 20260718,
    mock_vision: Annotated[bool, typer.Option("--mock-vision")] = False,
    confirm_authorized: Annotated[bool, typer.Option("--confirm-authorized")] = False,
    early_stop: Annotated[bool, typer.Option("--early-stop/--no-early-stop")] = True,
) -> None:
    """Start a new screening run."""
    settings = _settings()
    if not mock_vision and settings.app_env != "test" and not confirm_authorized:
        raise typer.BadParameter("Live runs require --confirm-authorized")
    request = RunRequest(
        shops=_load_shops(shops),
        seed=seed,
        mock_vision=mock_vision,
        input_file_path=shops,
        confirm_authorized=confirm_authorized,
    )

    async def execute() -> None:
        settings.ensure_directories()
        repository, engine = await _repository(settings)
        chrome: ChromeProcessManager | None = None
        live_catalog: PlaywrightCatalogBackend | None = None
        if mock_vision:
            catalog = FixtureCatalogBackend(product_count=25)
        else:
            chrome = ChromeProcessManager(settings)
            await chrome.start()
            live_catalog = PlaywrightCatalogBackend(settings, TaobaoAdapter())
            await live_catalog.connect()
            catalog = live_catalog
        try:
            service = _service(
                settings,
                repository,
                mock_vision=mock_vision,
                catalog=catalog,
                early_stop=early_stop,
            )
            run_id = await service.run(request)
            paths = await ReportGenerator(repository, settings.artifacts_dir).generate(run_id)
            run = await repository.get_run(run_id)
            console.print(f"Run {run.status if run else 'unknown'}: {run_id}")
            console.print(f"Report: {paths.html}")
        finally:
            if live_catalog:
                await live_catalog.close()
            if chrome:
                await chrome.stop()
            await engine.dispose()

    asyncio.run(execute())


@app.command("resume")
def resume_command(
    run_id: Annotated[UUID, typer.Option()],
    confirm_authorized: Annotated[bool, typer.Option("--confirm-authorized")] = False,
) -> None:
    """Continue only unfinished steps using the stored configuration snapshot."""

    async def execute() -> None:
        settings = _settings()
        repository, engine = await _repository(settings)
        run = await repository.get_run(run_id)
        if run is None:
            raise typer.BadParameter(f"Run not found: {run_id}")
        mock = bool(run.config_snapshot_json.get("mock_vision"))
        if not mock and settings.app_env != "test" and not confirm_authorized:
            raise typer.BadParameter("Live resume requires --confirm-authorized")
        chrome: ChromeProcessManager | None = None
        live_catalog: PlaywrightCatalogBackend | None = None
        if mock:
            catalog = FixtureCatalogBackend(product_count=25)
        else:
            chrome = ChromeProcessManager(settings)
            await chrome.start()
            live_catalog = PlaywrightCatalogBackend(settings, TaobaoAdapter())
            await live_catalog.connect()
            catalog = live_catalog
        try:
            service = _service(
                settings,
                repository,
                mock_vision=mock,
                catalog=catalog,
                early_stop=bool(run.config_snapshot_json["early_stop"]),
            )
            status = await service.resume(run_id)
            paths = await ReportGenerator(repository, settings.artifacts_dir).generate(run_id)
            console.print(f"Run resumed and {status}: {run_id}")
            console.print(f"Report: {paths.html}")
        finally:
            if live_catalog:
                await live_catalog.close()
            if chrome:
                await chrome.stop()
            await engine.dispose()

    asyncio.run(execute())


@app.command("report")
def report_command(run_id: Annotated[UUID, typer.Option()]) -> None:
    """Regenerate deterministic offline reports for a run."""

    async def execute() -> None:
        settings = _settings()
        repository, engine = await _repository(settings)
        paths = await ReportGenerator(repository, settings.artifacts_dir).generate(run_id)
        console.print(json.dumps(paths.model_dump(mode="json"), ensure_ascii=False, indent=2))
        await engine.dispose()

    asyncio.run(execute())


@app.command("rebuild-archives")
def rebuild_archives_command(run_id: Annotated[UUID, typer.Option()]) -> None:
    """Reparse saved HTML and rebuild clean flat product archives without browsing."""

    async def execute() -> None:
        settings = _settings()
        repository, engine = await _repository(settings)
        rebuilder = OfflineArchiveRebuilder(
            repository,
            AdapterRegistry([TaobaoAdapter()]),
            settings.artifacts_dir,
        )
        result = await rebuilder.rebuild(run_id)
        paths = await ReportGenerator(repository, settings.artifacts_dir).generate(run_id)
        console.print(json.dumps({**result, "report": str(paths.html)}, ensure_ascii=False))
        await engine.dispose()

    asyncio.run(execute())


@review_app.command("list")
def review_list(run_id: Annotated[UUID, typer.Option()]) -> None:
    """List shops requiring review or having insufficient data."""

    async def execute() -> None:
        settings = _settings()
        repository, engine = await _repository(settings)
        rows = await repository.review_rows(run_id)
        table = Table("店铺", "决定", "原因", "摘要")
        for row in rows:
            table.add_row(
                row.shop.display_name or row.shop.canonical_key,
                row.decision or "",
                row.decision_reason_code or "",
                row.decision_summary or "",
            )
        console.print(table)
        await engine.dispose()

    asyncio.run(execute())


if __name__ == "__main__":
    app()
