from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from shop_scout.config import Settings
from shop_scout.domain.models import ImageArtifact
from shop_scout.exceptions import ShopScoutError, VisionProviderError
from shop_scout.vision.factory import create_vision_provider
from shop_scout.vision.serpapi import SerpApiVisionProvider


def artifact(tmp_path: Path) -> ImageArtifact:
    image_path = tmp_path / "image.jpg"
    image_path.write_bytes(b"fixture")
    return ImageArtifact(
        source_url="https://img.example/source.jpg",
        raw_path=image_path,
        normalized_path=image_path,
        sha256="c" * 64,
        phash="0" * 16,
        width=400,
        height=400,
        file_size=7,
        content_type="image/jpeg",
    )


async def test_serpapi_maps_only_exact_matches_and_redacts_key(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["engine"] == "google_lens"
        assert request.url.params["type"] == "exact_matches"
        assert request.url.params["url"] == "https://img.example/source.jpg"
        assert request.url.params["api_key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "api_key": "must-not-be-written",
                "exact_matches": [
                    {
                        "title": "External product",
                        "link": "https://external.example/product/1",
                        "thumbnail": "https://images.example/match.jpg",
                    },
                    {
                        "title": "Duplicate page entry",
                        "link": "https://external.example/product/1",
                        "thumbnail": "https://images.example/match.jpg",
                    },
                ],
                "visual_matches": [
                    {
                        "link": "https://similar.example/not-exact",
                        "image": "https://images.example/similar.jpg",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = SerpApiVisionProvider(api_key="test-key", client=client)
        result = await provider.detect(
            artifact(tmp_path), run_id=uuid4(), output_dir=tmp_path / "vision"
        )

    assert result.provider == "serpapi"
    assert [page.url for page in result.pages_with_matching_images] == [
        "https://external.example/product/1"
    ]
    assert result.full_matching_images[0].url == "https://images.example/match.jpg"
    assert result.visually_similar_images == []
    assert "must-not-be-written" not in result.raw_response_path.read_text()


async def test_serpapi_classifies_auth_failure(tmp_path: Path) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "bad key"}))
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SerpApiVisionProvider(api_key="bad-key", client=client)
        with pytest.raises(VisionProviderError) as error:
            await provider.detect(
                artifact(tmp_path), run_id=uuid4(), output_dir=tmp_path / "vision"
            )
    assert error.value.code == "SERPAPI_AUTH_ERROR"


async def test_serpapi_classifies_exhausted_credits(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"error": "Your account has run out of searches"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SerpApiVisionProvider(api_key="test-key", client=client)
        with pytest.raises(VisionProviderError) as error:
            await provider.detect(
                artifact(tmp_path), run_id=uuid4(), output_dir=tmp_path / "vision"
            )
    assert error.value.code == "SERPAPI_CREDITS_EXHAUSTED"


async def test_serpapi_treats_lens_no_results_as_success(tmp_path: Path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"error": "Google Lens hasn't returned any results for this query."},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = SerpApiVisionProvider(api_key="test-key", client=client)
        result = await provider.detect(
            artifact(tmp_path), run_id=uuid4(), output_dir=tmp_path / "vision"
        )
    assert result.full_matching_images == []
    assert result.pages_with_matching_images == []


def test_serpapi_factory_requires_key() -> None:
    settings = Settings(
        _env_file=None,
        serpapi_api_key=None,
    )
    with pytest.raises(ShopScoutError, match="SERPAPI_API_KEY"):
        create_vision_provider(settings)
