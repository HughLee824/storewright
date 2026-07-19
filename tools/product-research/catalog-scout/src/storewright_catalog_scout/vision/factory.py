from storewright_catalog_scout.config import Settings
from storewright_catalog_scout.domain.protocols import WebDetectionProvider
from storewright_catalog_scout.exceptions import CatalogScoutError
from storewright_catalog_scout.vision.serpapi import SerpApiVisionProvider


def create_vision_provider(settings: Settings) -> WebDetectionProvider:
    if not settings.serpapi_key_pool:
        raise CatalogScoutError("SERPAPI_API_KEYS is required for live image search")
    return SerpApiVisionProvider(
        api_keys=settings.serpapi_key_pool,
        timeout_seconds=settings.vision_timeout_seconds,
        concurrency=settings.vision_concurrency,
    )
