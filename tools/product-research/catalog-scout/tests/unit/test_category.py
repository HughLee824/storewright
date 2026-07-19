from storewright_catalog_scout.extraction.category import detail_category, provisional_category


def test_provisional_category_uses_deterministic_title_keywords() -> None:
    assert provisional_category("天然玛瑙耳环") == "earrings"
    assert provisional_category("Silver necklace") == "necklaces"
    assert provisional_category("开口戒指") == "rings"
    assert provisional_category("unknown product") == "uncategorized"


def test_detail_category_prefers_source_path_and_falls_back() -> None:
    assert detail_category(["饰品", "耳饰"], "earrings") == "耳饰"
    assert detail_category([], "earrings") == "earrings"
