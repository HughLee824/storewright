from __future__ import annotations

from shop_scout.domain.protocols import SourceAdapter


class AdapterRegistry:
    def __init__(self, adapters: list[SourceAdapter]) -> None:
        self._adapters = adapters

    def for_url(self, url: str) -> SourceAdapter:
        for adapter in self._adapters:
            try:
                adapter.identify_shop_url(url)
            except ValueError:
                continue
            return adapter
        raise ValueError(f"No source adapter supports {url!r}")
