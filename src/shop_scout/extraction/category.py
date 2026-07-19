from __future__ import annotations

from shop_scout.images.processor import safe_segment

_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("earrings", ("耳环", "耳饰", "耳钉", "耳坠", "耳线", "earring")),
    ("necklaces", ("项链", "吊坠", "锁骨链", "necklace", "pendant")),
    ("rings", ("戒指", "指环", "尾戒", "ring")),
    ("bracelets", ("手链", "手镯", "臂环", "bracelet", "bangle")),
    ("brooches", ("胸针", "brooch")),
    ("hair-accessories", ("发夹", "发饰", "发簪", "hair clip", "hairpin")),
)


def provisional_category(title: str | None) -> str:
    normalized = (title or "").casefold()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "uncategorized"


def detail_category(category_path: list[str], fallback: str) -> str:
    if not category_path:
        return fallback
    return safe_segment(category_path[-1].casefold())
