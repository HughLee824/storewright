import pytest

from shop_scout.browser.llm_factory import create_navigation_llm
from shop_scout.config import Settings
from shop_scout.exceptions import ShopScoutError


def test_deepseek_factory_requires_key() -> None:
    settings = Settings(
        _env_file=None,
        browser_use_provider="deepseek",
        browser_use_model="deepseek-chat",
        deepseek_api_key=None,
    )
    with pytest.raises(ShopScoutError, match="DEEPSEEK_API_KEY"):
        create_navigation_llm(settings)


def test_deepseek_factory_and_vision_mode() -> None:
    settings = Settings(
        _env_file=None,
        browser_use_provider="deepseek",
        browser_use_model="deepseek-chat",
        deepseek_api_key="test-key",
        browser_use_vision_mode="auto",
    )
    llm = create_navigation_llm(settings)
    assert llm.provider == "deepseek"
    assert llm.model == "deepseek-chat"
    assert settings.browser_use_vision is False


def test_browser_use_vision_setting() -> None:
    automatic = Settings(
        _env_file=None,
        browser_use_provider="browser-use",
        browser_use_vision_mode="auto",
    )
    enabled = Settings(
        _env_file=None,
        browser_use_provider="browser-use",
        browser_use_vision_mode="true",
    )
    disabled = Settings(
        _env_file=None,
        browser_use_provider="browser-use",
        browser_use_vision_mode="false",
    )
    assert automatic.browser_use_vision == "auto"
    assert enabled.browser_use_vision is True
    assert disabled.browser_use_vision is False
