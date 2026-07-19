import json
from pathlib import Path

import pytest

from storewright_catalog_scout.adapters.taobao import (
    TaobaoAdapter,
    canonical_product_url,
    extract_item_id,
    extract_shop_id,
)
from storewright_catalog_scout.domain.enums import PageKind, UrlRelation
from storewright_catalog_scout.domain.models import ProductRef
from storewright_catalog_scout.extraction.url_normalizer import normalize_http_url

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://item.taobao.com/item.htm?spm=a&id=42", "https://item.taobao.com/item.htm?id=42"),
        (
            "https://detail.tmall.com/item.htm?id=42&utm_source=x",
            "https://detail.tmall.com/item.htm?id=42",
        ),
        ("//item.taobao.com/item.htm?id=42", "https://item.taobao.com/item.htm?id=42"),
        (
            "https://h5.m.taobao.com/awp/core/detail.htm?id=42",
            "https://item.taobao.com/item.htm?id=42",
        ),
    ],
)
def test_canonical_product_urls(url: str, expected: str) -> None:
    assert canonical_product_url(url) == expected


def test_normalizer_rejects_unsafe_protocols() -> None:
    with pytest.raises(ValueError):
        normalize_http_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        normalize_http_url("data:text/plain,x")


def test_extract_ids_and_identity() -> None:
    adapter = TaobaoAdapter()
    identity = adapter.identify_shop_url(
        "https://shop.m.taobao.com/shop/shop_index.htm?shop_id=123", "Shop"
    )
    assert extract_shop_id(identity.canonical_url) == "123"
    assert identity.canonical_key == "taobao:123"
    assert extract_item_id("https://item.taobao.com/item.htm?id=9") == "9"
    assert (
        adapter.identify_shop_url("https://acme.tmall.com/").canonical_key == "host:acme.tmall.com"
    )
    with pytest.raises(ValueError):
        adapter.identify_shop_url("https://example.com/")


def test_taobao_listing_url_and_modern_card_hook() -> None:
    adapter = TaobaoAdapter()
    assert (
        adapter.product_listing_url("https://seller.taobao.com/?spm=ignored")
        == "https://seller.taobao.com/search.htm?search=y"
    )
    assert "cardContainer" in adapter.browser_listing_selector
    assert "itemCardData" in adapter.browser_listing_extraction_script


def test_listing_fixture_deduplicates_and_reads_lazy_images() -> None:
    adapter = TaobaoAdapter()
    html = (FIXTURES / "listing" / "lazy_listing.html").read_text()
    items = adapter.collect_product_pool_html(html, "https://seller.taobao.com/search.htm")
    assert [item.external_item_id for item in items] == ["1002", "1001"]
    assert items[0].listing_image_url == "https://img.alicdn.com/2.jpg"
    assert items[1].listing_image_url == "https://img.alicdn.com/l.jpg"


def test_detail_priority_og_jsonld_and_fallback() -> None:
    adapter = TaobaoAdapter()
    product = ProductRef(
        external_item_id="1",
        canonical_url="https://item.taobao.com/item.htm?id=1",
        title="fallback title",
        listing_image_url="https://img.alicdn.com/fallback.jpg",
        source_position=0,
    )
    og = adapter.extract_product_detail_html(
        (FIXTURES / "detail" / "og.html").read_text(), product, product.canonical_url
    )
    assert (og.title, og.source) == ("OG 商品", "listing_fallback")
    assert og.main_image_url == product.listing_image_url
    jsonld = adapter.extract_product_detail_html(
        (FIXTURES / "detail" / "json_ld.html").read_text(), product, product.canonical_url
    )
    assert (jsonld.title, jsonld.source) == ("JSON 商品", "json_ld")
    fallback = adapter.extract_product_detail_html("<html></html>", product, product.canonical_url)
    assert fallback.source == "listing_fallback"


def test_tmall_structured_state_extracts_price_parameters_skus_and_images() -> None:
    adapter = TaobaoAdapter()
    product = ProductRef(
        external_item_id="42",
        canonical_url="https://detail.tmall.com/item.htm?id=42",
        listing_image_url="https://img.alicdn.com/listing.jpg",
        source_position=0,
    )
    state = {
        "loaderData": {
            "home": {
                "data": {
                    "res": {
                        "item": {"title": "结构化商品"},
                        "componentsVO": {
                            "headImageVO": {
                                "images": [
                                    "https://img.alicdn.com/main.jpg",
                                    "https://img.alicdn.com/gallery.jpg",
                                ]
                            },
                            "priceVO": {
                                "extraPrice": {"priceText": "543.2", "priceTitle": "券后"},
                                "price": {"priceText": "690", "priceTitle": "优惠前"},
                            },
                        },
                        "plusViewVO": {
                            "industryParamVO": {
                                "basicParamList": [
                                    {"propertyName": "链子材质", "valueName": "竹"},
                                    {"propertyName": "品牌", "valueName": "寻逸"},
                                ]
                            }
                        },
                        "skuBase": {
                            "props": [
                                {
                                    "pid": "1",
                                    "name": "款式",
                                    "values": [
                                        {
                                            "vid": "2",
                                            "name": "绿檀款",
                                            "image": "https://img.alicdn.com/sku.jpg",
                                        }
                                    ],
                                }
                            ],
                            "skus": [{"skuId": "9", "propPath": "1:2"}],
                        },
                        "skuCore": {
                            "sku2info": {
                                "9": {"price": {"priceText": "720"}, "quantity": 6}
                            }
                        },
                    }
                }
            }
        }
    }
    html = f"<script>var a = {{}};var b = {json.dumps(state)};for (var k in a) {{}}</script>"
    detail = adapter.extract_product_detail_html(html, product, product.canonical_url)
    assert detail.source == "structured_state"
    assert detail.main_image_url == "https://img.alicdn.com/main.jpg"
    assert detail.image_urls == [
        "https://img.alicdn.com/main.jpg",
        "https://img.alicdn.com/listing.jpg",
        "https://img.alicdn.com/gallery.jpg",
        "https://img.alicdn.com/sku.jpg",
    ]
    assert detail.image_roles["https://img.alicdn.com/sku.jpg"] == "sku"
    assert detail.price == "543.2"
    assert detail.currency == "CNY"
    assert detail.price_details == {
        "display_price": "543.2",
        "display_label": "券后",
        "list_price": "690",
        "sku_min_price": "720",
        "sku_max_price": "720",
    }
    assert detail.attributes == {"链子材质": "竹", "品牌": "寻逸"}
    assert detail.materials == ["竹"]
    assert detail.variants[0]["options"] == {"款式": "绿檀款"}


def test_page_and_relation_classification() -> None:
    adapter = TaobaoAdapter()
    shop = adapter.identify_shop_url("https://acme.taobao.com/?shop_id=77")
    product = ProductRef(
        external_item_id="42",
        canonical_url="https://item.taobao.com/item.htm?id=42",
        source_position=0,
    )
    assert adapter.classify_url("https://login.taobao.com/") == PageKind.LOGIN
    assert adapter.classify_url("https://x.taobao.com/punish") == PageKind.VERIFICATION
    assert adapter.classify_url(product.canonical_url) == PageKind.PRODUCT_DETAIL
    assert (
        adapter.classify_relation(shop, product, "https://h5.m.taobao.com/x?id=42")
        == UrlRelation.SELF_ITEM
    )
    assert (
        adapter.classify_relation(shop, product, "https://x.taobao.com/?shop_id=77")
        == UrlRelation.SELF_SHOP
    )
    assert (
        adapter.classify_relation(shop, product, "https://img.alicdn.com/x.jpg")
        == UrlRelation.IMAGE_HOST_ONLY
    )
    assert adapter.classify_relation(shop, product, "https://example.org/a") == UrlRelation.EXTERNAL
    assert adapter.classify_relation(shop, product, "ftp://example.org/a") == UrlRelation.UNKNOWN
