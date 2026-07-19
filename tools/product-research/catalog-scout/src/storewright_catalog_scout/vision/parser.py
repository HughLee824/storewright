from __future__ import annotations

from pathlib import Path
from typing import Any

from storewright_catalog_scout.domain.models import (
    WebDetectionResult,
    WebImageMatch,
    WebPageMatch,
)


def _image(value: dict[str, Any]) -> WebImageMatch:
    return WebImageMatch(url=str(value.get("url", "")), score=value.get("score"))


def parse_web_detection(
    payload: dict[str, Any], *, provider: str, image_sha256: str, raw_response_path: Path
) -> WebDetectionResult:
    web = payload.get("webDetection") or payload.get("web_detection") or payload
    pages: list[WebPageMatch] = []
    for page in web.get("pagesWithMatchingImages", web.get("pages_with_matching_images", [])) or []:
        pages.append(
            WebPageMatch(
                url=str(page.get("url", "")),
                title=page.get("pageTitle") or page.get("page_title"),
                full_matching_images=[
                    _image(item)
                    for item in page.get("fullMatchingImages", page.get("full_matching_images", []))
                    or []
                ],
                partial_matching_images=[
                    _image(item)
                    for item in page.get(
                        "partialMatchingImages", page.get("partial_matching_images", [])
                    )
                    or []
                ],
            )
        )
    labels = web.get("bestGuessLabels", web.get("best_guess_labels", [])) or []
    return WebDetectionResult(
        provider=provider,
        image_sha256=image_sha256,
        full_matching_images=[
            _image(item)
            for item in web.get("fullMatchingImages", web.get("full_matching_images", [])) or []
        ],
        partial_matching_images=[
            _image(item)
            for item in web.get("partialMatchingImages", web.get("partial_matching_images", []))
            or []
        ],
        pages_with_matching_images=pages,
        visually_similar_images=[
            _image(item)
            for item in web.get("visuallySimilarImages", web.get("visually_similar_images", []))
            or []
        ],
        best_guess_labels=[
            str(item.get("label", "")) if isinstance(item, dict) else str(item) for item in labels
        ],
        web_entities=list(web.get("webEntities", web.get("web_entities", [])) or []),
        raw_response_path=raw_response_path,
    )
