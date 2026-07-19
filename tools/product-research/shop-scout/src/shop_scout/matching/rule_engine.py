from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from shop_scout.domain.enums import EvidenceKind, ProductVerdict, UrlRelation
from shop_scout.domain.models import (
    MatchEvidence,
    ProductDecisionResult,
    WebDetectionResult,
)

RelationClassifier = Callable[[str], UrlRelation]


def decide_product(
    result: WebDetectionResult | None,
    classify_relation: RelationClassifier,
    *,
    source_image_url: str,
    error_code: str | None = None,
    local_cross_shop_url: str | None = None,
) -> ProductDecisionResult:
    if local_cross_shop_url:
        local_evidence = MatchEvidence(
            kind=EvidenceKind.LOCAL_SHA256_MATCH,
            url=local_cross_shop_url,
            relation=UrlRelation.EXTERNAL,
            reason="Identical normalized image SHA-256 belongs to another shop",
        )
        return ProductDecisionResult(
            verdict=ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH,
            reason_code="LOCAL_CROSS_SHOP_SHA256_MATCH",
            summary="发现另一店铺使用完全相同的规范化主图。",
            evidence=[local_evidence],
            confidence=Decimal("1.00"),
        )
    if error_code or result is None:
        return ProductDecisionResult(
            verdict=ProductVerdict.SEARCH_ERROR,
            reason_code=error_code or "SEARCH_RESULT_MISSING",
            summary="图片检索未成功完成，不能视为未发现匹配。",
            evidence=[],
            confidence=Decimal("0"),
        )

    evidence: list[MatchEvidence] = []
    external_full = False
    external_partial = False
    for page in result.pages_with_matching_images:
        relation = classify_relation(page.url)
        if page.full_matching_images:
            evidence.append(
                MatchEvidence(
                    kind=EvidenceKind.FULL_MATCH_PAGE,
                    url=page.url,
                    page_url=page.url,
                    page_title=page.title,
                    relation=relation,
                    reason="Page contains a full matching image",
                )
            )
            external_full |= relation == UrlRelation.EXTERNAL
        if page.partial_matching_images:
            evidence.append(
                MatchEvidence(
                    kind=EvidenceKind.PARTIAL_MATCH_PAGE,
                    url=page.url,
                    page_url=page.url,
                    page_title=page.title,
                    relation=relation,
                    reason="Page contains a partial matching image",
                )
            )
            external_partial |= relation == UrlRelation.EXTERNAL
    if external_full:
        return ProductDecisionResult(
            verdict=ProductVerdict.EXACT_EXTERNAL_IMAGE_MATCH,
            reason_code="EXTERNAL_PAGE_FULL_MATCH",
            summary="发现外部网页包含完整匹配图片。",
            evidence=evidence,
            confidence=Decimal("0.99"),
        )

    remaining_full = []
    for image in result.full_matching_images:
        if image.url == source_image_url:
            continue
        relation = classify_relation(image.url)
        evidence.append(
            MatchEvidence(
                kind=EvidenceKind.FULL_MATCH_IMAGE,
                url=image.url,
                relation=relation,
                reason="Top-level full match has no reliable external page mapping",
            )
        )
        remaining_full.append(image)
    if remaining_full:
        return ProductDecisionResult(
            verdict=ProductVerdict.FULL_IMAGE_UNMAPPED,
            reason_code="FULL_MATCH_WITHOUT_PAGE_EVIDENCE",
            summary="发现完整匹配图片，但无法可靠映射到外部网页。",
            evidence=evidence,
            confidence=Decimal("0.70"),
        )

    if external_partial or result.partial_matching_images:
        for image in result.partial_matching_images:
            evidence.append(
                MatchEvidence(
                    kind=EvidenceKind.PARTIAL_MATCH_IMAGE,
                    url=image.url,
                    relation=classify_relation(image.url),
                    reason="Partial image match",
                )
            )
        return ProductDecisionResult(
            verdict=ProductVerdict.PARTIAL_EXTERNAL_IMAGE_MATCH,
            reason_code="EXTERNAL_PARTIAL_MATCH",
            summary="发现外部局部图片匹配，需要人工复核。",
            evidence=evidence,
            confidence=Decimal("0.75"),
        )
    if result.visually_similar_images:
        evidence.extend(
            MatchEvidence(
                kind=EvidenceKind.VISUALLY_SIMILAR_IMAGE,
                url=image.url,
                relation=classify_relation(image.url),
                reason="Visual similarity is not exact-match evidence",
            )
            for image in result.visually_similar_images
        )
        return ProductDecisionResult(
            verdict=ProductVerdict.NO_INDEXED_MATCH_FOUND,
            reason_code="VISUAL_SIMILAR_ONLY_NO_EXACT",
            summary="仅发现视觉相似图片，未发现已索引的完整或局部匹配。",
            evidence=evidence,
            confidence=Decimal("0.80"),
        )
    return ProductDecisionResult(
        verdict=ProductVerdict.NO_INDEXED_MATCH_FOUND,
        reason_code="NO_FULL_OR_PARTIAL_MATCH",
        summary=f"{result.provider} 当前索引中未发现完整或局部图片匹配。",
        evidence=evidence,
        confidence=Decimal("0.90"),
    )
