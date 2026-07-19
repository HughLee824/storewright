import pytest

from storewright_catalog_scout.browser.llm_factory import create_navigation_llm
from storewright_catalog_scout.config import Settings
from storewright_catalog_scout.exceptions import CatalogScoutError


def test_deepseek_factory_requires_key() -> None:
    settings = Settings.model_validate(
        {
            "browser_use_provider": "deepseek",
            "browser_use_model": "deepseek-chat",
            "deepseek_api_key": None,
        }
    )
    with pytest.raises(CatalogScoutError, match="DEEPSEEK_API_KEY"):
        create_navigation_llm(settings)


def test_deepseek_factory_and_vision_mode() -> None:
    settings = Settings.model_validate(
        {
            "browser_use_provider": "deepseek",
            "browser_use_model": "deepseek-chat",
            "deepseek_api_key": "test-key",
            "browser_use_vision_mode": "auto",
        }
    )
    llm = create_navigation_llm(settings)
    assert llm.provider == "deepseek"
    assert llm.model == "deepseek-chat"
    assert settings.browser_use_vision is False


def test_browser_use_vision_setting() -> None:
    automatic = Settings.model_validate(
        {"browser_use_provider": "browser-use", "browser_use_vision_mode": "auto"}
    )
    enabled = Settings.model_validate(
        {"browser_use_provider": "browser-use", "browser_use_vision_mode": "true"}
    )
    disabled = Settings.model_validate(
        {"browser_use_provider": "browser-use", "browser_use_vision_mode": "false"}
    )
    assert automatic.browser_use_vision == "auto"
    assert enabled.browser_use_vision is True
    assert disabled.browser_use_vision is False
