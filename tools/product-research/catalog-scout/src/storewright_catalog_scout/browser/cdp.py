from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from storewright_catalog_scout.adapters.taobao import (
    TaobaoAdapter,
    canonical_product_url,
    extract_item_id,
)
from storewright_catalog_scout.browser.detail_access import DetailAccessPolicy
from storewright_catalog_scout.browser.navigator import BrowserUseNavigator
from storewright_catalog_scout.browser.page_state import classify_page_state
from storewright_catalog_scout.config import Settings
from storewright_catalog_scout.domain.enums import PageKind
from storewright_catalog_scout.domain.models import (
    CatalogDiscovery,
    ProductDetail,
    ProductRef,
    ShopIdentity,
)
from storewright_catalog_scout.exceptions import (
    CatalogScoutError,
    ManualActionRequiredError,
    RiskCooldownRequiredError,
)
from storewright_catalog_scout.extraction.url_normalizer import normalize_http_url
from storewright_catalog_scout.orchestration.catalog import CatalogBackend


class PlaywrightCatalogBackend(CatalogBackend):
    def __init__(self, settings: Settings, adapter: TaobaoAdapter) -> None:
        self.settings = settings
        self.adapter = adapter
        self.navigator = BrowserUseNavigator(settings)
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.detail_page: Page | None = None
        self.image_client: httpx.AsyncClient | None = None
        self.detail_access = DetailAccessPolicy(
            settings.detail_access_state_path,
            interval_seconds=settings.detail_page_interval_seconds,
            jitter_seconds=settings.detail_page_interval_jitter_seconds,
            max_per_hour=settings.detail_page_max_per_hour,
            risk_cooldown_seconds=settings.detail_risk_cooldown_seconds,
            max_risk_cooldown_seconds=settings.detail_risk_max_cooldown_seconds,
        )

    async def connect(self) -> None:
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.connect_over_cdp(self.settings.cdp_url)
        if not self.browser.contexts:
            raise RuntimeError("CDP browser has no context")
        self.context = self.browser.contexts[0]
        self.image_client = httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=5,
            timeout=self.settings.vision_timeout_seconds,
        )

    async def close(self) -> None:
        if self.detail_page:
            await self.detail_page.close()
        if self.image_client:
            await self.image_client.aclose()
            self.image_client = None
        # connect_over_cdp attaches to a user-owned Chrome process. Stopping
        # Playwright disconnects this client; Browser.close() could terminate
        # the attached browser and must not be used here.
        self.browser = None
        if self.playwright:
            await self.playwright.stop()

    async def collect_pool(self, shop: ShopIdentity, max_items: int) -> CatalogDiscovery:
        if self.context is None:
            raise RuntimeError("Playwright catalog is not connected")
        listing_url = self.adapter.product_listing_url(shop.original_url)
        page = self.context.pages[-1] if self.context.pages else await self.context.new_page()
        direct_ready = False
        try:
            await page.goto(
                listing_url,
                wait_until="domcontentloaded",
                timeout=self.settings.navigation_timeout_ms,
            )
            direct_state = classify_page_state(
                page.url, await page.title(), await page.content()
            )
            if direct_state == PageKind.UNKNOWN:
                direct_state = self.adapter.classify_url(page.url)
            if direct_state in {PageKind.LOGIN, PageKind.VERIFICATION, PageKind.BLOCKED}:
                raise ManualActionRequiredError(
                    f"Listing page requires human action: {direct_state}"
                )
            direct_ready = (
                direct_state == PageKind.PRODUCT_LISTING
                and await self._wait_for_listing(page)
            )
        except ManualActionRequiredError:
            raise
        except Exception:
            direct_ready = False
        if not direct_ready:
            navigation = await self.navigator.ensure_product_listing(
                shop.original_url,
                listing_url,
            )
            if navigation.requires_human or navigation.page_kind in {
                PageKind.LOGIN,
                PageKind.VERIFICATION,
                PageKind.BLOCKED,
            }:
                raise ManualActionRequiredError(navigation.reason)
            page = await self._active_page(navigation.final_url or shop.original_url)
            if not navigation.success:
                raise CatalogScoutError(f"NAVIGATION_FAILED: {navigation.reason}")
            if not await self._wait_for_listing(page):
                raise CatalogScoutError("NAVIGATION_FAILED: product listing did not become ready")
        initial_state = classify_page_state(page.url, await page.title(), await page.content())
        if initial_state == PageKind.UNKNOWN:
            initial_state = self.adapter.classify_url(page.url)
        if initial_state in {PageKind.LOGIN, PageKind.VERIFICATION, PageKind.BLOCKED}:
            raise ManualActionRequiredError(f"Page requires human action: {initial_state}")
        if initial_state != PageKind.PRODUCT_LISTING:
            raise CatalogScoutError("NAVIGATION_FAILED: product listing was not reached")
        seen: dict[str, ProductRef] = {}
        visited_pages: set[str] = set()
        catalog_complete = False
        while page.url not in visited_pages:
            visited_pages.add(page.url)
            legacy_page = (
                await page.locator(self.adapter.browser_legacy_listing_selector).count() > 0
            )
            stable = 0
            for _ in range(1 if legacy_page else self.settings.max_scroll_rounds):
                await self._raise_for_manual_action(page)
                before = len(seen)
                await self._collect_visible_products(page, seen)
                stable = stable + 1 if len(seen) == before else 0
                if len(seen) >= max_items:
                    has_next_page = (
                        legacy_page
                        and await page.locator(
                            self.adapter.browser_next_page_selector
                        ).count()
                        > 0
                    )
                    return CatalogDiscovery(
                        items=list(seen.values())[:max_items],
                        catalog_complete=(
                            legacy_page and not has_next_page and len(seen) == max_items
                        ),
                    )
                if legacy_page or stable >= self.settings.stable_scroll_rounds:
                    break
                height = await page.evaluate("window.innerHeight")
                await page.mouse.wheel(0, int(height * 0.8))
                await page.wait_for_timeout(self.settings.page_action_delay_ms)

            next_page = page.locator(self.adapter.browser_next_page_selector)
            if await next_page.count() == 0:
                catalog_complete = True
                break
            next_url = await next_page.first.get_attribute("href")
            if not next_url:
                break
            try:
                normalized_next = normalize_http_url(next_url, page.url)
            except ValueError:
                break
            if urlsplit(normalized_next).hostname != urlsplit(page.url).hostname:
                break
            await page.goto(
                normalized_next,
                wait_until="domcontentloaded",
                timeout=self.settings.navigation_timeout_ms,
            )
            if not await self._wait_for_listing(page):
                raise CatalogScoutError("PAGINATION_FAILED: product listing did not become ready")
        return CatalogDiscovery(
            items=list(seen.values())[:max_items], catalog_complete=catalog_complete
        )

    async def _wait_for_listing(self, page: Page) -> bool:
        deadline = 10_000
        elapsed = 0
        while elapsed <= deadline:
            state = classify_page_state(page.url, await page.title(), await page.content())
            if state in {PageKind.LOGIN, PageKind.VERIFICATION, PageKind.BLOCKED}:
                raise ManualActionRequiredError(f"Page requires human action: {state}")
            if await page.locator(self.adapter.browser_listing_selector).count() >= 2:
                return True
            await page.wait_for_timeout(250)
            elapsed += 250
        return False

    async def _raise_for_manual_action(self, page: Page) -> None:
        state = classify_page_state(page.url, await page.title(), await page.content())
        if state not in {PageKind.LOGIN, PageKind.VERIFICATION, PageKind.BLOCKED}:
            return
        screenshot = self.settings.artifacts_dir / "manual-action.png"
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(screenshot), full_page=False)
        raise ManualActionRequiredError(f"Page requires human action: {state}")

    async def _collect_visible_products(
        self, page: Page, seen: dict[str, ProductRef]
    ) -> None:
        raw: list[dict[str, Any]] = await page.locator(
            self.adapter.browser_listing_selector
        ).evaluate_all(self.adapter.browser_listing_extraction_script)
        for item in raw:
            try:
                url = canonical_product_url(str(item["href"]), page.url)
            except ValueError:
                continue
            item_id = extract_item_id(url)
            if not item_id or item_id in seen:
                continue
            image = str(item.get("image") or "") or None
            if image:
                try:
                    image = self.adapter.normalize_listing_image_url(image, page.url)
                except ValueError:
                    image = None
            seen[item_id] = ProductRef(
                external_item_id=item_id,
                canonical_url=url,
                title=str(item.get("title") or "") or None,
                listing_image_url=image,
                source_position=len(seen),
            )

    async def extract_detail(self, shop: ShopIdentity, product: ProductRef) -> ProductDetail:
        if self.context is None:
            raise RuntimeError("Playwright catalog is not connected")
        if self.detail_page is None:
            self.detail_page = await self.context.new_page()
        await self.detail_access.wait_before_request()
        self.detail_access.record_request()
        try:
            response = await self.detail_page.goto(
                product.canonical_url,
                wait_until="domcontentloaded",
                timeout=self.settings.navigation_timeout_ms,
            )
        except PlaywrightTimeoutError as error:
            retry_at = self.detail_access.record_risk("DETAIL_NAVIGATION_TIMEOUT")
            raise RiskCooldownRequiredError("DETAIL_NAVIGATION_TIMEOUT", retry_at) from error
        if response is None or response.status in {403, 429} or response.status >= 500:
            status = response.status if response else "NO_RESPONSE"
            retry_at = self.detail_access.record_risk(f"DETAIL_HTTP_{status}")
            await self._save_risk_screenshot()
            raise RiskCooldownRequiredError(f"DETAIL_HTTP_{status}", retry_at)
        html = await self.detail_page.content()
        state = classify_page_state(self.detail_page.url, await self.detail_page.title(), html)
        if state in {PageKind.LOGIN, PageKind.VERIFICATION, PageKind.BLOCKED}:
            self.detail_access.record_risk(f"DETAIL_PAGE_{state.value.upper()}")
            await self._save_risk_screenshot()
            raise ManualActionRequiredError(f"Detail page requires human action: {state}")
        final_item_id = extract_item_id(self.detail_page.url)
        if (
            state != PageKind.PRODUCT_DETAIL
            or final_item_id != product.external_item_id
            or not self.adapter.has_product_detail_evidence(html)
        ):
            retry_at = self.detail_access.record_risk("DETAIL_PAGE_UNEXPECTED")
            await self._save_risk_screenshot()
            raise RiskCooldownRequiredError("DETAIL_PAGE_UNEXPECTED", retry_at)
        detail = self.adapter.extract_product_detail_html(html, product, self.detail_page.url)
        self.detail_access.record_success()
        return detail

    async def fetch_image_url(self, image_url: str, referer_url: str) -> tuple[bytes, str]:
        if self.image_client is None:
            raise RuntimeError("Public image client is not connected")
        response = await self.image_client.get(
            image_url,
            headers={"Referer": referer_url, "User-Agent": "storewright-catalog-scout/0.1"},
        )
        response.raise_for_status()
        return response.content, response.headers.get(
            "content-type", "application/octet-stream"
        )

    async def _active_page(self, final_url: str) -> Page:
        assert self.context is not None
        for page in reversed(self.context.pages):
            if page.url == final_url:
                return page
        target_host = final_url.split("/", 3)[2].lower() if "://" in final_url else ""
        for page in reversed(self.context.pages):
            if target_host and target_host in page.url.lower():
                return page
        raise RuntimeError(f"Active listing page not found for {final_url}")

    async def _save_risk_screenshot(self) -> None:
        if self.detail_page is None:
            return
        screenshot = self.settings.artifacts_dir / "manual-action.png"
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        try:
            await self.detail_page.screenshot(path=str(screenshot), full_page=False)
        except Exception:
            # Evidence capture must never suppress the protective pause.
            return
