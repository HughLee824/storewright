from pathlib import Path

import pytest

from storewright_catalog_scout.adapters.taobao import TaobaoAdapter
from storewright_catalog_scout.browser.cdp import PlaywrightCatalogBackend
from storewright_catalog_scout.config import Settings


class FakeMouse:
    async def wheel(self, _x: int, _y: int) -> None:
        raise AssertionError("Legacy paginated listings must not use infinite scrolling")


class FakeLocator:
    def __init__(self, page: "FakeListingPage", selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        adapter = self.page.adapter
        if self.selector == adapter.browser_listing_selector:
            return 2
        if self.selector == adapter.browser_legacy_listing_selector:
            return 2
        if self.selector == adapter.browser_next_page_selector:
            return 1 if self.page.page_number == 1 else 0
        return 0

    async def evaluate_all(self, _script: str) -> list[dict[str, object]]:
        offset = 0 if self.page.page_number == 1 else 2
        return [
            {
                "href": f"https://detail.tmall.com/item.htm?id={offset + index}",
                "title": f"Item {offset + index}",
                "image": (
                    "https://img.alicdn.com/bao/uploaded/"
                    f"item-{offset + index}.jpg_180x180.jpg"
                ),
            }
            for index in (1, 2)
        ]

    async def get_attribute(self, name: str) -> str | None:
        if name == "href" and self.page.page_number == 1:
            return "https://seller.tmall.com/search.htm?search=y&pageNo=2"
        return None


class FakeListingPage:
    def __init__(self, adapter: TaobaoAdapter) -> None:
        self.adapter = adapter
        self.url = "about:blank"
        self.page_number = 1
        self.mouse = FakeMouse()

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url
        self.page_number = 2 if "pageNo=2" in url else 1

    async def title(self) -> str:
        return "店内搜索页"

    async def content(self) -> str:
        offset = 0 if self.page_number == 1 else 2
        return (
            f'<a href="item.htm?id={offset + 1}">a</a>'
            f'<a href="item.htm?id={offset + 2}">b</a>'
        )

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None

    async def evaluate(self, _script: str) -> int:
        return 900


class FakeContext:
    def __init__(self, page: FakeListingPage) -> None:
        self.pages = [page]


class DelayedLocator(FakeLocator):
    async def count(self) -> int:
        self.page.selector_checks += 1  # type: ignore[attr-defined]
        return 2 if self.page.selector_checks >= 3 else 0  # type: ignore[attr-defined]


class DelayedListingPage(FakeListingPage):
    def __init__(self, adapter: TaobaoAdapter) -> None:
        super().__init__(adapter)
        self.url = "https://seller.tmall.com/search.htm?search=y"
        self.selector_checks = 0
        self.waits = 0

    def locator(self, selector: str) -> FakeLocator:
        if selector == self.adapter.browser_listing_selector:
            return DelayedLocator(self, selector)
        return super().locator(selector)

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        self.waits += 1


def backend(tmp_path: Path) -> tuple[PlaywrightCatalogBackend, TaobaoAdapter]:
    adapter = TaobaoAdapter()
    settings = Settings(artifacts_dir=tmp_path / "artifacts")
    catalog = PlaywrightCatalogBackend(settings, adapter)
    catalog.context = FakeContext(FakeListingPage(adapter))  # type: ignore[assignment]
    return catalog, adapter


@pytest.mark.asyncio
async def test_paginated_legacy_listing_is_complete_and_uses_original_images(
    tmp_path: Path,
) -> None:
    catalog, adapter = backend(tmp_path)
    shop = adapter.identify_shop_url("https://seller.tmall.com/shop/view_shop.htm")

    discovery = await catalog.collect_pool(shop, max_items=10)

    assert discovery.catalog_complete
    assert [item.external_item_id for item in discovery.items] == ["1", "2", "3", "4"]
    assert all(
        item.listing_image_url and "_180x180" not in item.listing_image_url
        for item in discovery.items
    )


@pytest.mark.asyncio
async def test_catalog_limit_marks_paginated_listing_incomplete(tmp_path: Path) -> None:
    catalog, adapter = backend(tmp_path)
    shop = adapter.identify_shop_url("https://seller.tmall.com/shop/view_shop.htm")

    discovery = await catalog.collect_pool(shop, max_items=3)

    assert not discovery.catalog_complete
    assert len(discovery.items) == 3


@pytest.mark.asyncio
async def test_listing_waits_for_cards_inserted_after_domcontentloaded(tmp_path: Path) -> None:
    catalog, adapter = backend(tmp_path)
    page = DelayedListingPage(adapter)

    assert await catalog._wait_for_listing(page)  # type: ignore[arg-type]  # noqa: SLF001
    assert page.selector_checks == 3
    assert page.waits == 2
