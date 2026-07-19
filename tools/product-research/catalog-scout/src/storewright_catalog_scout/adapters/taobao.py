from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import tldextract

from storewright_catalog_scout.domain.enums import PageKind, UrlRelation
from storewright_catalog_scout.domain.models import ProductDetail, ProductRef, ShopIdentity
from storewright_catalog_scout.extraction.image_url import largest_srcset_url
from storewright_catalog_scout.extraction.url_normalizer import (
    canonical_url_hash,
    normalize_http_url,
    query_value,
)

_ITEM_HOSTS = {"item.taobao.com", "detail.tmall.com", "h5.m.taobao.com", "m.intl.taobao.com"}
_IMAGE_HOST_SUFFIXES = ("alicdn.com", "tbcdn.cn", "taobaocdn.com")
_LOGIN_MARKERS = ("login.taobao.com", "/member/login", "password")
_VERIFY_MARKERS = ("/punish", "/challenge", "/verify", "captcha", "nc_1_n1z", "滑块")
_ALICDN_RESIZE_SUFFIX = re.compile(
    r"_(?:\d{2,4}x\d{2,4}|\d{2,4}x\d{2,4}q\d{1,3})\.(?:jpe?g|png|webp)$",
    re.I,
)


def extract_item_id(url: str) -> str | None:
    return query_value(url, "id", "item_id", "itemId")


def extract_shop_id(url: str) -> str | None:
    return query_value(url, "shop_id", "shopId", "user_number_id", "seller_id")


def canonical_product_url(url: str, base_url: str | None = None) -> str:
    normalized = normalize_http_url(url, base_url)
    item_id = extract_item_id(normalized)
    if not item_id:
        raise ValueError(f"URL has no stable item id: {url!r}")
    host = (urlsplit(normalized).hostname or "").lower()
    if host not in _ITEM_HOSTS and not host.endswith((".taobao.com", ".tmall.com")):
        raise ValueError(f"Not a supported product URL: {url!r}")
    canonical_host = "detail.tmall.com" if "tmall" in host else "item.taobao.com"
    return f"https://{canonical_host}/item.htm?id={item_id}"


class _ShopHtmlParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self.json_ld: list[str] = []
        self.images: list[str] = []
        self._anchor: dict[str, str] | None = None
        self._anchor_text: list[str] = []
        self._json_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key.lower()] = values["content"]
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._json_parts = []
        elif tag == "a" and values.get("href"):
            self._anchor = values.copy()
            self._anchor_text = []
        elif tag == "img":
            image_value = next(
                (
                    values.get(key)
                    for key in ("data-src", "data-ks-lazyload", "data-lazyload-src", "src")
                    if values.get(key)
                ),
                None,
            )
            if image_value:
                self.images.append(image_value)
            if self._anchor is None:
                return
            for key in (
                "src",
                "data-src",
                "data-ks-lazyload",
                "data-lazyload-src",
                "srcset",
                "alt",
            ):
                if values.get(key) and not self._anchor.get(key):
                    self._anchor[key] = values[key]

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join("".join(self._anchor_text).split())
            self.links.append(self._anchor)
            self._anchor = None
        elif tag == "script" and self._json_parts is not None:
            self.json_ld.append("".join(self._json_parts))
            self._json_parts = None

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor_text.append(data)
        if self._json_parts is not None:
            self._json_parts.append(data)


def _iter_json_products(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        types = value.get("@type")
        if types == "Product" or isinstance(types, list) and "Product" in types:
            found.append(value)
        for child in value.values():
            found.extend(_iter_json_products(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_json_products(child))
    return found


def _extract_ice_detail_state(html: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\bvar\s+b\s*=\s*", html):
        try:
            context, _ = decoder.raw_decode(html, match.end())
        except json.JSONDecodeError:
            continue
        if not isinstance(context, dict):
            continue
        loader_data = context.get("loaderData")
        if not isinstance(loader_data, dict):
            continue
        home = loader_data.get("home")
        if not isinstance(home, dict):
            continue
        data = home.get("data")
        if not isinstance(data, dict):
            continue
        result = data.get("res")
        if isinstance(result, dict):
            return result
    return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _price_text(value: Any) -> str | None:
    text = str(_mapping(value).get("priceText") or "").strip()
    return text or None


def _tmall_structured_detail(state: dict[str, Any]) -> dict[str, Any]:
    item = _mapping(state.get("item"))
    components = _mapping(state.get("componentsVO"))
    head_images = _sequence(_mapping(components.get("headImageVO")).get("images"))
    gallery = [str(value) for value in head_images if value]
    if not gallery:
        gallery = [str(value) for value in _sequence(item.get("images")) if value]

    sku_base = _mapping(state.get("skuBase"))
    sku_core = _mapping(state.get("skuCore"))
    sku2info = _mapping(sku_core.get("sku2info"))
    value_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    sku_images: list[str] = []
    for prop in _sequence(sku_base.get("props")):
        prop_map = _mapping(prop)
        property_id = str(prop_map.get("pid") or "")
        property_name = str(prop_map.get("name") or "")
        for value in _sequence(prop_map.get("values")):
            value_map = _mapping(value)
            value_id = str(value_map.get("vid") or "")
            image = str(value_map.get("image") or "").strip() or None
            value_lookup[(property_id, value_id)] = {
                "property": property_name,
                "value": str(value_map.get("name") or ""),
                "image": image,
            }
            if image and image not in sku_images:
                sku_images.append(image)

    variants: list[dict[str, Any]] = []
    for sku in _sequence(sku_base.get("skus")):
        sku_map = _mapping(sku)
        sku_id = str(sku_map.get("skuId") or "")
        options: dict[str, str] = {}
        image: str | None = None
        for part in str(sku_map.get("propPath") or "").split(";"):
            property_id, separator, value_id = part.partition(":")
            if not separator:
                continue
            selected = value_lookup.get((property_id, value_id), {})
            if selected.get("property") and selected.get("value"):
                options[str(selected["property"])] = str(selected["value"])
            image = image or selected.get("image")
        info = _mapping(sku2info.get(sku_id))
        variants.append(
            {
                "sku_id": sku_id,
                "options": options,
                "image_url": image,
                "price": _price_text(info.get("price")),
                "discounted_price": _price_text(info.get("subPrice")),
                "quantity": info.get("quantity"),
            }
        )

    attributes: dict[str, str] = {}
    industry = _mapping(_mapping(state.get("plusViewVO")).get("industryParamVO"))
    for key in ("enhanceParamList", "basicParamList"):
        for parameter in _sequence(industry.get(key)):
            parameter_map = _mapping(parameter)
            name = str(parameter_map.get("propertyName") or "").strip()
            value = str(parameter_map.get("valueName") or "").strip()
            if name and value:
                attributes[name] = value

    price_vo = _mapping(_mapping(components).get("priceVO"))
    display_price = _price_text(price_vo.get("extraPrice")) or _price_text(
        price_vo.get("price")
    )
    list_price = _price_text(price_vo.get("price"))
    sku_prices = [
        value
        for value in (_price_text(_mapping(info).get("price")) for info in sku2info.values())
        if value
    ]
    numeric_prices: list[tuple[float, str]] = []
    for value in sku_prices:
        try:
            numeric_prices.append((float(value), value))
        except ValueError:
            continue
    price_details = {
        "display_price": display_price,
        "display_label": str(_mapping(price_vo.get("extraPrice")).get("priceTitle") or "")
        or str(_mapping(price_vo.get("price")).get("priceTitle") or "")
        or None,
        "list_price": list_price,
        "sku_min_price": min(numeric_prices)[1] if numeric_prices else None,
        "sku_max_price": max(numeric_prices)[1] if numeric_prices else None,
    }
    return {
        "title": str(item.get("title") or "").strip() or None,
        "gallery": gallery,
        "sku_images": sku_images,
        "attributes": attributes,
        "materials": [
            value
            for name, value in attributes.items()
            if "材质" in name or "material" in name.lower()
        ],
        "variants": variants,
        "price": display_price,
        "currency": "CNY" if display_price or list_price else None,
        "price_details": price_details,
        "description_url": str(item.get("pcADescUrl") or "").strip() or None,
    }


class TaobaoAdapter:
    source_name = "taobao"

    def product_listing_url(self, shop_url: str) -> str:
        normalized = normalize_http_url(shop_url)
        parts = urlsplit(normalized)
        return urlunsplit((parts.scheme, parts.netloc, "/search.htm", "search=y", ""))

    @property
    def browser_listing_selector(self) -> str:
        return (
            'dl.item[data-id], '
            'a[href*="item.taobao.com/item.htm"], '
            'a[href*="detail.tmall.com/item.htm"], '
            'a[href*="item.htm?id="], '
            '[class*="cardContainer"]'
        )

    @property
    def browser_listing_extraction_script(self) -> str:
        return """els => els.map((element, position) => {
            if (element.matches('dl.item[data-id]')) {
                const link = element.querySelector(
                  'a[href*="item.taobao.com/item.htm"], '
                  + 'a[href*="detail.tmall.com/item.htm"], a[href*="item.htm?id="]');
                const img = element.querySelector('img');
                const title = element.querySelector('.item-name');
                const lazy = img?.dataset.src || img?.dataset.ksLazyload;
                return link ? {href: link.href, title: title?.innerText || link.title ||
                  img?.alt || '', image: lazy || img?.dataset.lazyloadSrc || img?.src || '',
                  position} : null;
            }
            if (element.tagName === 'A') {
                const img = element.querySelector('img');
                const lazy = img?.dataset.src || img?.dataset.ksLazyload;
                return {href: element.href, title: element.title || element.innerText ||
                  img?.alt || '', image: lazy || img?.dataset.lazyloadSrc || img?.src || '',
                  position};
            }
            const fiberKey = Object.keys(element).find(key => key.startsWith('__reactFiber'));
            let fiber = fiberKey ? element[fiberKey] : null;
            while (fiber && !fiber.memoizedProps?.itemCardData) fiber = fiber.return;
            const data = fiber?.memoizedProps?.itemCardData;
            return data ? {href: data.itemUrl, title: data.title || '', image: data.image || '',
              position} : null;
        }).filter(Boolean)"""

    @property
    def browser_legacy_listing_selector(self) -> str:
        return "dl.item[data-id]"

    @property
    def browser_next_page_selector(self) -> str:
        return "a.ui-page-s-next[href], a.ui-page-next[href]"

    def normalize_listing_image_url(self, image_url: str, base_url: str) -> str:
        normalized = normalize_http_url(image_url, base_url)
        host = (urlsplit(normalized).hostname or "").lower()
        if host.endswith(_IMAGE_HOST_SUFFIXES):
            parts = urlsplit(normalized)
            path = _ALICDN_RESIZE_SUFFIX.sub("", parts.path)
            normalized = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
        return normalized

    def identify_shop_url(self, input_url: str, display_name: str | None = None) -> ShopIdentity:
        canonical = normalize_http_url(input_url)
        host = urlsplit(canonical).hostname or ""
        registrable = tldextract.extract(host).top_domain_under_public_suffix
        if registrable not in {"taobao.com", "tmall.com"}:
            raise ValueError("Not a Taobao/Tmall URL")
        shop_id = extract_shop_id(canonical)
        subdomain = host.removesuffix(f".{registrable}") if host != registrable else None
        source = "tmall" if registrable == "tmall.com" else "taobao"
        if shop_id:
            key = f"{source}:{shop_id}"
        elif subdomain and subdomain not in {"www", "shop", "m", "h5", "item", "detail"}:
            key = f"host:{subdomain}.{registrable}"
        else:
            key = f"url:{canonical_url_hash(canonical)}"
        return ShopIdentity(
            original_url=input_url,
            canonical_url=canonical,
            host=host,
            registrable_domain=registrable,
            canonical_key=key,
            external_shop_id=shop_id,
            shop_subdomain=subdomain,
            display_name=display_name,
        )

    def classify_url(self, url: str) -> PageKind:
        lowered = url.lower()
        if any(marker in lowered for marker in _LOGIN_MARKERS):
            return PageKind.LOGIN
        if any(marker in lowered for marker in _VERIFY_MARKERS):
            return PageKind.VERIFICATION
        if extract_item_id(url):
            return PageKind.PRODUCT_DETAIL
        if any(marker in lowered for marker in ("search.htm", "all-items", "category")):
            return PageKind.PRODUCT_LISTING
        return PageKind.SHOP_HOME

    def collect_product_pool_html(self, html: str, base_url: str) -> list[ProductRef]:
        parser = _ShopHtmlParser(base_url)
        parser.feed(html)
        result: dict[str, ProductRef] = {}
        for link in parser.links:
            try:
                canonical = canonical_product_url(link["href"], base_url)
            except ValueError:
                continue
            item_id = extract_item_id(canonical)
            assert item_id is not None
            if item_id in result:
                continue
            image = next(
                (
                    link.get(key)
                    for key in ("data-src", "data-ks-lazyload", "data-lazyload-src", "src")
                    if link.get(key)
                ),
                None,
            )
            if link.get("srcset"):
                image = largest_srcset_url(link["srcset"], base_url) or image
            if image:
                try:
                    image = self.normalize_listing_image_url(image, base_url)
                except ValueError:
                    image = None
            result[item_id] = ProductRef(
                external_item_id=item_id,
                canonical_url=canonical,
                title=link.get("title") or link.get("text") or link.get("alt") or None,
                listing_image_url=image,
                source_position=len(result),
            )
        return list(result.values())

    def extract_product_detail_html(
        self, html: str, product: ProductRef, base_url: str
    ) -> ProductDetail:
        parser = _ShopHtmlParser(base_url)
        parser.feed(html)
        title = parser.meta.get("og:title")
        og_image = parser.meta.get("og:image")
        image: str | None = None
        json_ld_image: str | None = None
        state_image: str | None = None
        description = parser.meta.get("description") or parser.meta.get("og:description")
        category = parser.meta.get("product:category")
        image_values: list[str] = [og_image] if og_image else []
        image_roles: dict[str, str] = {}
        if product.listing_image_url:
            image_values.append(product.listing_image_url)
        materials: list[str] = []
        attributes: dict[str, str] = {}
        variants: list[dict[str, Any]] = []
        price: str | None = parser.meta.get("product:price:amount")
        currency: str | None = parser.meta.get("product:price:currency")
        price_details: dict[str, Any] = {}
        raw_json_products: list[dict[str, Any]] = []
        source: Literal[
            "structured_state", "og_image", "json_ld", "visible_image", "listing_fallback"
        ]
        ice_state = _extract_ice_detail_state(html)
        structured = _tmall_structured_detail(ice_state) if ice_state else None
        if structured:
            title = structured["title"] or title
            attributes.update(structured["attributes"])
            materials.extend(structured["materials"])
            variants.extend(structured["variants"])
            price = structured["price"] or price
            currency = structured["currency"] or currency
            price_details = structured["price_details"]
            for index, value in enumerate(structured["gallery"]):
                image_values.append(value)
                image_roles[value] = "main" if index == 0 else "gallery"
                state_image = state_image or value
            for value in structured["sku_images"]:
                image_values.append(value)
                image_roles[value] = "sku"
        for text in parser.json_ld:
            try:
                values = _iter_json_products(json.loads(text))
            except json.JSONDecodeError:
                continue
            if not values:
                continue
            raw_json_products.extend(values)
            candidate = values[0]
            title = title or str(candidate.get("name") or "")
            description = description or str(candidate.get("description") or "") or None
            category = category or str(candidate.get("category") or "") or None
            material = candidate.get("material")
            if isinstance(material, list):
                materials.extend(str(item) for item in material if item)
            elif material:
                materials.append(str(material))
            brand = candidate.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            if brand:
                attributes["brand"] = str(brand)
            properties = candidate.get("additionalProperty")
            if isinstance(properties, list):
                for prop in properties:
                    if not isinstance(prop, dict):
                        continue
                    name = str(prop.get("name") or "").strip()
                    value = str(prop.get("value") or "").strip()
                    if name and value:
                        attributes[name] = value
            images = candidate.get("image")
            if isinstance(images, list):
                structured_images = [str(item) for item in images if item]
                image_values.extend(structured_images)
                json_ld_image = json_ld_image or next(iter(structured_images), None)
            elif images:
                json_ld_image = json_ld_image or str(images)
                image_values.append(str(images))
            offers = candidate.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict):
                price = price or str(offer.get("price") or "") or None
                currency = currency or str(offer.get("priceCurrency") or "") or None
            sku = candidate.get("sku")
            if sku:
                variants.append({"sku": str(sku), "offers": offers})
        if not materials:
            material_match = re.search(r"(?:材质|material)\s*[:：]\s*([^<\n]{1,80})", html, re.I)
            if material_match:
                materials.append(" ".join(material_match.group(1).split()))
        if not state_image:
            image_values.extend(parser.images)
        if state_image:
            image = state_image
            source = "structured_state"
        elif json_ld_image:
            image = json_ld_image
            source = "json_ld"
        elif product.listing_image_url:
            image = product.listing_image_url
            source = "listing_fallback"
        elif og_image:
            image = og_image
            source = "og_image"
        else:
            image = next(iter(parser.images), None)
            source = "visible_image"
        if not image:
            raise ValueError("DETAIL_MAIN_IMAGE_NOT_FOUND")
        normalized_image = normalize_http_url(image, base_url)
        normalized_images: list[str] = []
        for value in image_values:
            try:
                normalized = normalize_http_url(value, base_url)
            except ValueError:
                continue
            host = urlsplit(normalized).hostname or ""
            if host.endswith(_IMAGE_HOST_SUFFIXES) and normalized not in normalized_images:
                normalized_images.append(normalized)
                role = image_roles.get(value)
                if role:
                    image_roles[normalized] = role
        if normalized_image in normalized_images:
            normalized_images.remove(normalized_image)
        normalized_images.insert(0, normalized_image)
        category_path = [
            part.strip()
            for part in re.split(r"\s*[>/|]\s*", category or "")
            if part.strip()
        ]
        return ProductDetail(
            external_item_id=product.external_item_id,
            canonical_url=product.canonical_url,
            title=title or product.title or f"Item {product.external_item_id}",
            main_image_url=normalized_image,
            image_urls=normalized_images,
            image_roles={
                url: image_roles.get(url, "main" if url == normalized_image else "gallery")
                for url in normalized_images
            },
            description=description,
            category_path=category_path,
            materials=list(dict.fromkeys(materials)),
            attributes=attributes,
            variants=variants,
            price=price,
            currency=currency,
            price_details=price_details,
            source=source,
            raw_html=html,
            metadata={
                "json_ld_products": raw_json_products,
                "description_url": structured.get("description_url") if structured else None,
            },
        )

    def has_product_detail_evidence(self, html: str) -> bool:
        """Require product-specific structured evidence before accepting a detail page."""
        if _extract_ice_detail_state(html):
            return True
        parser = _ShopHtmlParser("https://item.taobao.com/")
        parser.feed(html)
        if parser.meta.get("og:title") and parser.meta.get("og:image"):
            return True
        for text in parser.json_ld:
            try:
                if _iter_json_products(json.loads(text)):
                    return True
            except json.JSONDecodeError:
                continue
        return False

    def classify_relation(
        self, shop: ShopIdentity, product: ProductRef, candidate_url: str
    ) -> UrlRelation:
        try:
            normalized = normalize_http_url(candidate_url)
        except ValueError:
            return UrlRelation.UNKNOWN
        host = urlsplit(normalized).hostname or ""
        if host.endswith(_IMAGE_HOST_SUFFIXES) or re.search(
            r"\.(?:jpe?g|png|webp|gif)$", urlsplit(normalized).path, re.I
        ):
            return UrlRelation.IMAGE_HOST_ONLY
        item_id = extract_item_id(normalized)
        if item_id == product.external_item_id:
            return UrlRelation.SELF_ITEM
        candidate_shop_id = extract_shop_id(normalized)
        if shop.external_shop_id and candidate_shop_id == shop.external_shop_id:
            return UrlRelation.SELF_SHOP
        if shop.shop_subdomain and host == shop.host:
            return UrlRelation.SELF_SHOP
        return UrlRelation.EXTERNAL
