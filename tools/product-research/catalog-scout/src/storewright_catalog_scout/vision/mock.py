from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from storewright_catalog_scout.domain.models import ImageArtifact, WebDetectionResult
from storewright_catalog_scout.exceptions import VisionProviderError
from storewright_catalog_scout.vision.parser import parse_web_detection


class MockVisionProvider:
    name = "mock"

    def __init__(self, scenarios_by_sha256: dict[str, str] | None = None) -> None:
        self.scenarios_by_sha256 = scenarios_by_sha256 or {}
        self.call_count = 0

    def _scenario(self, image: ImageArtifact) -> str:
        if image.sha256 in self.scenarios_by_sha256:
            return self.scenarios_by_sha256[image.sha256]
        return parse_qs(urlsplit(image.source_url).query).get("scenario", ["empty"])[0]

    async def detect(
        self, image: ImageArtifact, *, run_id: UUID, output_dir: Path
    ) -> WebDetectionResult:
        self.call_count += 1
        scenario = self._scenario(image)
        if scenario == "error":
            raise VisionProviderError("MOCK_SEARCH_ERROR", "Configured mock failure")
        payload = _scenario_payload(scenario)
        raw_path = output_dir / f"{image.sha256}.json"
        await asyncio.to_thread(_write_payload, raw_path, payload)
        return parse_web_detection(
            payload, provider=self.name, image_sha256=image.sha256, raw_response_path=raw_path
        )


def _scenario_payload(scenario: str) -> dict[str, object]:
    external_image = "https://images.example.net/matched.jpg"
    scenarios: dict[str, dict[str, object]] = {
        "external_full": {
            "fullMatchingImages": [{"url": external_image}],
            "pagesWithMatchingImages": [
                {
                    "url": "https://catalog.example.net/product/42",
                    "pageTitle": "External catalog",
                    "fullMatchingImages": [{"url": external_image}],
                }
            ],
        },
        "self_only_full": {
            "fullMatchingImages": [{"url": "https://img.alicdn.com/self.jpg"}],
            "pagesWithMatchingImages": [],
        },
        "partial": {
            "partialMatchingImages": [{"url": external_image}],
            "pagesWithMatchingImages": [
                {
                    "url": "https://blog.example.net/post",
                    "partialMatchingImages": [{"url": external_image}],
                }
            ],
        },
        "unmapped_full": {"fullMatchingImages": [{"url": external_image}]},
        "visual_only": {"visuallySimilarImages": [{"url": external_image}]},
        "empty": {},
    }
    if scenario not in scenarios:
        raise VisionProviderError("MOCK_SCENARIO_UNKNOWN", f"Unknown mock scenario {scenario}")
    return {"webDetection": scenarios[scenario]}


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
