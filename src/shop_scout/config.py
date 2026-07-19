"""Central application settings."""

from pathlib import Path
from typing import Literal

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./runtime/shop_scout.db"
    artifacts_dir: Path = Path("runtime/artifacts")

    chrome_executable: Path | None = None
    chrome_user_data_dir: Path = Path("runtime/chrome-profile")
    chrome_remote_debugging_host: str = "127.0.0.1"
    chrome_remote_debugging_port: int = 9222
    chrome_headless: bool = False
    chrome_start_timeout_seconds: int = 20

    browser_use_api_key: str | None = None
    browser_use_provider: Literal["browser-use", "deepseek"] = "deepseek"
    browser_use_model: str | None = "deepseek-chat"
    browser_agent_max_steps: int = 20
    browser_use_vision_mode: Literal["auto", "true", "false"] = "false"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    serpapi_api_keys: str | None = None
    vision_timeout_seconds: int = 30
    vision_concurrency: int = 3

    max_pool_size: int = 2_000
    max_scroll_rounds: int = 50
    stable_scroll_rounds: int = 3
    page_action_delay_ms: int = 1200
    navigation_timeout_ms: int = 30_000
    max_image_bytes: int = 15_728_640
    min_image_width: int = 300
    min_image_height: int = 300

    max_qualified_products_per_category: int = 20
    shop_reject_rate_threshold: float = 0.60
    early_stop_min_searches: int = 10
    early_stop_confidence: float = 0.90
    max_search_error_rate: float = 0.20
    early_stop_on_reject: bool = True
    max_detail_products_per_batch: int = 0
    detail_page_interval_seconds: float = 30.0
    pause_after_screening: bool = False

    @computed_field
    @property
    def cdp_url(self) -> str:
        return f"http://{self.chrome_remote_debugging_host}:{self.chrome_remote_debugging_port}"

    @computed_field
    @property
    def browser_use_vision(self) -> bool | Literal["auto"]:
        if self.browser_use_provider == "deepseek":
            return False
        if self.browser_use_vision_mode == "auto":
            return "auto"
        return self.browser_use_vision_mode == "true"

    @computed_field
    @property
    def serpapi_key_pool(self) -> list[str]:
        keys = [
            key.strip()
            for key in (self.serpapi_api_keys or "").split(",")
            if key.strip()
        ]
        return list(dict.fromkeys(keys))

    def ensure_directories(self) -> None:
        for path in (
            self.artifacts_dir,
            self.chrome_user_data_dir,
            Path("runtime"),
        ):
            path.mkdir(parents=True, exist_ok=True)
