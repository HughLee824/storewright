from typing import Any

from storewright_catalog_scout.config import Settings
from storewright_catalog_scout.exceptions import CatalogScoutError


def create_navigation_llm(settings: Settings) -> Any:
    if settings.browser_use_provider == "deepseek":
        from browser_use.llm.deepseek.chat import ChatDeepSeek

        if not settings.deepseek_api_key:
            raise CatalogScoutError(
                "DEEPSEEK_API_KEY is required when BROWSER_USE_PROVIDER=deepseek"
            )
        return ChatDeepSeek(
            model=settings.browser_use_model or "deepseek-chat",
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            temperature=0.0,
        )
    from browser_use import ChatBrowserUse

    if settings.browser_use_model:
        return ChatBrowserUse(model=settings.browser_use_model)
    return ChatBrowserUse()
