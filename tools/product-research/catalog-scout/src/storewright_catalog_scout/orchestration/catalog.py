from __future__ import annotations

from io import BytesIO
from typing import Protocol

from PIL import Image

from storewright_catalog_scout.adapters.taobao import TaobaoAdapter
from storewright_catalog_scout.domain.models import ProductDetail, ProductRef, ShopIdentity


class CatalogBackend(Protocol):
    async def collect_pool(self, shop: ShopIdentity, max_items: int) -> list[ProductRef]: ...

    async def extract_detail(self, shop: ShopIdentity, product: ProductRef) -> ProductDetail: ...

    async def fetch_image_url(self, image_url: str, referer_url: str) -> tuple[bytes, str]: ...


class FixtureCatalogBackend:
    """Deterministic local catalog used by the complete offline flow."""

    def __init__(self, product_count: int = 6, scenarios: list[str] | None = None) -> None:
        self.product_count = product_count
        self.scenarios = scenarios or ["empty"] * product_count
        self.adapter = TaobaoAdapter()

    async def collect_pool(self, shop: ShopIdentity, max_items: int) -> list[ProductRef]:
        count = min(self.product_count, max_items)
        prefix = sum(shop.canonical_key.encode()) % 10_000
        cards = "".join(
            f'<a href="//item.taobao.com/item.htm?id={prefix}{index + 1:03d}" '
            f'title="Fixture {"earrings" if index % 2 == 0 else "necklaces"} '
            f'product {index + 1}"><img '
            f'data-ks-lazyload="//fixtures.invalid/images/{prefix}{index + 1:03d}.png'
            f'?scenario={self.scenarios[index % len(self.scenarios)]}"></a>'
            for index in range(count)
        )
        return self.adapter.collect_product_pool_html(
            f"<!doctype html><html><body>{cards}</body></html>", shop.canonical_url
        )

    async def extract_detail(self, shop: ShopIdentity, product: ProductRef) -> ProductDetail:
        try:
            index = (int(product.external_item_id[-3:]) - 1) % len(self.scenarios)
        except ValueError:
            index = product.source_position % len(self.scenarios)
        scenario = self.scenarios[index]
        image_url = (
            f"https://fixtures.invalid/images/{product.external_item_id}.png?scenario={scenario}"
        )
        category = "earrings" if index % 2 == 0 else "necklaces"
        html = (
            '<!doctype html><html><head><meta property="og:title" '
            f'content="{product.title or product.external_item_id}">'
            f'<meta property="og:image" content="{image_url}">'
            f'<meta property="product:category" content="Jewelry &gt; {category}">'
            '<meta name="description" content="Fixture description">'
            '</head><body>材质：Sterling silver</body></html>'
        )
        return self.adapter.extract_product_detail_html(html, product, product.canonical_url)

    async def fetch_image_url(self, image_url: str, referer_url: str) -> tuple[bytes, str]:
        del referer_url
        item_id = image_url.split("/")[-1].split(".")[0]
        seed = sum(item_id.encode())
        image = Image.new(
            "RGB",
            (420, 420),
            ((seed * 17) % 255, (seed * 31) % 255, (seed * 47) % 255),
        )
        buffer = BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue(), "image/png"
