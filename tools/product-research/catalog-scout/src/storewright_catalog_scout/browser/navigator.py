from __future__ import annotations

from typing import Any

from storewright_catalog_scout.browser.llm_factory import create_navigation_llm
from storewright_catalog_scout.browser.prompts import NAVIGATION_SYSTEM_EXTENSION, NAVIGATION_TASK
from storewright_catalog_scout.config import Settings
from storewright_catalog_scout.domain.enums import PageKind
from storewright_catalog_scout.domain.models import NavigationResult


class BrowserUseNavigator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def ensure_product_listing(
        self, shop_url: str, listing_url: str | None = None
    ) -> NavigationResult:
        from browser_use import Agent, Browser

        browser: Any = Browser(
            cdp_url=self.settings.cdp_url,
            keep_alive=True,
            allowed_domains=["*.taobao.com", "*.tmall.com"],
        )
        agent: Any = Agent(
            task=NAVIGATION_TASK.format(
                shop_url=shop_url,
                listing_url=listing_url or shop_url,
            ),
            llm=create_navigation_llm(self.settings),
            browser=browser,
            output_model_schema=NavigationResult,
            use_vision=self.settings.browser_use_vision,
            use_judge=False,
            extend_system_message=NAVIGATION_SYSTEM_EXTENSION,
            calculate_cost=True,
        )
        try:
            history: Any = await agent.run(max_steps=self.settings.browser_agent_max_steps)
        finally:
            await browser.stop()
        structured = getattr(history, "structured_output", None)
        if callable(structured):
            structured = structured()
        if structured:
            return NavigationResult.model_validate(structured)
        final_url = history.final_result() if hasattr(history, "final_result") else None
        return NavigationResult(
            success=False,
            final_url=final_url if isinstance(final_url, str) else None,
            page_kind=PageKind.UNKNOWN,
            requires_human=False,
            reason="Browser Use returned no structured navigation result",
        )
