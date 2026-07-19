from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from storewright_catalog_scout.domain.enums import ProductVerdict, UrlRelation
from storewright_catalog_scout.domain.models import ImageArtifact, WebDetectionResult
from storewright_catalog_scout.exceptions import VisionProviderError
from storewright_catalog_scout.matching.rule_engine import decide_product
from storewright_catalog_scout.vision.mock import MockVisionProvider


def artifact(tmp_path: Path, scenario: str = "empty") -> ImageArtifact:
    path = tmp_path / "x.jpg"
    path.write_bytes(b"x")
    return ImageArtifact(
        source_url=f"https://source/image.jpg?scenario={scenario}",
        raw_path=path,
        normalized_path=path,
        sha256="a" * 64,
        phash="0" * 16,
        width=400,
        height=400,
        file_size=1,
        content_type="image/jpeg",
    )


def relation(url: str) -> UrlRelation:
    if "self" in url:
        return UrlRelation.SELF_ITEM
    if "alicdn" in url or url.endswith(".jpg"):
        return UrlRelation.IMAGE_HOST_ONLY
    return UrlRelation.EXTERNAL


@pytest.mark.parametrize(
    ("scenario", "verdict", "reason"),
    [
        ("external_full", ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH, "EXTERNAL_PAGE_FULL_MATCH"),
        ("partial", ProductVerdict.PARTIAL_EXTERNAL_IMAGE_MATCH, "EXTERNAL_PARTIAL_MATCH"),
        ("unmapped_full", ProductVerdict.FULL_IMAGE_UNMAPPED, "FULL_MATCH_WITHOUT_PAGE_EVIDENCE"),
        ("visual_only", ProductVerdict.NO_INDEXED_MATCH_FOUND, "VISUAL_SIMILAR_ONLY_NO_EXACT"),
        ("empty", ProductVerdict.NO_INDEXED_MATCH_FOUND, "NO_FULL_OR_PARTIAL_MATCH"),
    ],
)
async def test_mock_scenarios_and_rule_matrix(
    tmp_path: Path, scenario: str, verdict: ProductVerdict, reason: str
) -> None:
    image = artifact(tmp_path, scenario)
    result = await MockVisionProvider().detect(
        image, run_id=uuid4(), output_dir=tmp_path / "vision"
    )
    decision = decide_product(result, relation, source_image_url=image.source_url)
    assert (decision.verdict, decision.reason_code) == (verdict, reason)
    assert result.raw_response_path.is_file()


async def test_mock_error_and_unknown(tmp_path: Path) -> None:
    with pytest.raises(VisionProviderError) as error:
        await MockVisionProvider().detect(
            artifact(tmp_path, "error"), run_id=uuid4(), output_dir=tmp_path
        )
    assert error.value.code == "MOCK_SEARCH_ERROR"
    with pytest.raises(VisionProviderError, match="Unknown"):
        await MockVisionProvider().detect(
            artifact(tmp_path, "wat"), run_id=uuid4(), output_dir=tmp_path
        )


def test_search_error_and_local_duplicate_are_not_no_match() -> None:
    search = decide_product(None, relation, source_image_url="x", error_code="TIMEOUT")
    assert search.verdict == ProductVerdict.SEARCH_ERROR
    assert search.confidence == Decimal("0")
    local = decide_product(
        None,
        relation,
        source_image_url="x",
        local_cross_shop_url="https://other/item",
    )
    assert local.verdict == ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH
    assert local.confidence == Decimal("1.00")


def test_self_page_full_is_excluded_from_exact(tmp_path: Path) -> None:
    result = WebDetectionResult(
        provider="mock",
        image_sha256="a" * 64,
        full_matching_images=[],
        pages_with_matching_images=[
            {
                "url": "https://self/item",
                "full_matching_images": [{"url": "https://images/m.jpg"}],
            }
        ],
        raw_response_path=tmp_path / "x.json",
    )
    decision = decide_product(result, relation, source_image_url="x")
    assert decision.verdict == ProductVerdict.NO_INDEXED_MATCH_FOUND
