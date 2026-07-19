from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from shop_scout.domain.models import (
    ImageArtifact,
    WebDetectionResult,
    WebImageMatch,
    WebPageMatch,
)
from shop_scout.exceptions import VisionProviderError


class SerpApiVisionProvider:
    """Google Lens exact-match search through SerpApi."""

    name = "serpapi"
    endpoint = "https://serpapi.com/search.json"

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 30,
        concurrency: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.semaphore = asyncio.Semaphore(concurrency)
        self.client = client

    async def detect(
        self, image: ImageArtifact, *, run_id: UUID, output_dir: Path
    ) -> WebDetectionResult:
        del run_id
        payload = await self._search(image.source_url)
        raw_path = output_dir / f"{image.sha256}.json"
        await asyncio.to_thread(_write_payload, raw_path, payload)
        return _parse_exact_matches(
            payload,
            image_sha256=image.sha256,
            source_image_url=image.source_url,
            raw_response_path=raw_path,
        )

    async def _search(self, image_url: str) -> dict[str, Any]:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        owned_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            async with self.semaphore:
                for attempt in range(1, 4):
                    try:
                        response = await client.get(
                            self.endpoint,
                            params={
                                "engine": "google_lens",
                                "type": "exact_matches",
                                "url": image_url,
                                "api_key": self.api_key,
                            },
                        )
                    except httpx.HTTPError as error:
                        if attempt == 3:
                            raise VisionProviderError(
                                "SERPAPI_NETWORK_ERROR", str(error), retryable=True
                            ) from error
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    if response.status_code in {401, 403}:
                        raise VisionProviderError("SERPAPI_AUTH_ERROR", "SerpApi rejected the key")
                    if response.status_code == 429:
                        raise VisionProviderError(
                            "SERPAPI_RATE_LIMITED", "SerpApi rate limit reached", retryable=True
                        )
                    if response.status_code >= 500:
                        if attempt == 3:
                            raise VisionProviderError(
                                "SERPAPI_TEMPORARY_ERROR",
                                f"SerpApi returned HTTP {response.status_code}",
                                retryable=True,
                            )
                        await asyncio.sleep(2 ** (attempt - 1))
                        continue
                    if response.status_code >= 400:
                        raise VisionProviderError(
                            "SERPAPI_API_ERROR", f"SerpApi returned HTTP {response.status_code}"
                        )
                    try:
                        payload: dict[str, Any] = response.json()
                    except ValueError as error:
                        raise VisionProviderError(
                            "SERPAPI_INVALID_RESPONSE", "SerpApi returned invalid JSON"
                        ) from error
                    error_message = str(payload.get("error") or "")
                    if error_message:
                        lowered_error = error_message.lower()
                        if (
                            "no results" in lowered_error
                            or "hasn't returned any results" in lowered_error
                        ):
                            payload.pop("error", None)
                            payload.pop("api_key", None)
                            payload["exact_matches"] = []
                            return payload
                        if any(
                            marker in lowered_error for marker in ("credit", "searches", "plan")
                        ):
                            code = "SERPAPI_CREDITS_EXHAUSTED"
                        elif "key" in lowered_error or "authentication" in lowered_error:
                            code = "SERPAPI_AUTH_ERROR"
                        else:
                            code = "SERPAPI_API_ERROR"
                        raise VisionProviderError(code, error_message)
                    payload.pop("api_key", None)
                    return payload
        finally:
            if owned_client:
                await client.aclose()
        raise AssertionError("retry loop exhausted")


def _parse_exact_matches(
    payload: dict[str, Any],
    *,
    image_sha256: str,
    source_image_url: str,
    raw_response_path: Path,
) -> WebDetectionResult:
    pages: list[WebPageMatch] = []
    images: list[WebImageMatch] = []
    seen_pages: set[str] = set()
    seen_images: set[str] = set()
    for match in payload.get("exact_matches", []) or []:
        if not isinstance(match, dict):
            continue
        page_url = str(match.get("link") or "")
        image_url = str(match.get("image") or match.get("thumbnail") or source_image_url)
        image_match = WebImageMatch(url=image_url)
        if image_url not in seen_images:
            seen_images.add(image_url)
            images.append(image_match)
        if page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            pages.append(
                WebPageMatch(
                    url=page_url,
                    title=str(match.get("title") or "") or None,
                    full_matching_images=[image_match],
                )
            )
    return WebDetectionResult(
        provider="serpapi",
        image_sha256=image_sha256,
        full_matching_images=images,
        pages_with_matching_images=pages,
        raw_response_path=raw_response_path,
    )


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
