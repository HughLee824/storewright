from shop_scout.config import Settings
from shop_scout.domain.protocols import WebDetectionProvider
from shop_scout.exceptions import ShopScoutError
from shop_scout.vision.serpapi import SerpApiVisionProvider


def create_vision_provider(settings: Settings) -> WebDetectionProvider:
    if not settings.serpapi_key_pool:
        raise ShopScoutError("SERPAPI_API_KEYS is required for live image search")
    return SerpApiVisionProvider(
        api_keys=settings.serpapi_key_pool,
        timeout_seconds=settings.vision_timeout_seconds,
        concurrency=settings.vision_concurrency,
    )
