from pathlib import Path

from click.utils import strip_ansi
from typer.testing import CliRunner

from storewright_catalog_scout.cli import _load_shops, _write_env_template, app


def test_cli_exposes_required_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "init",
        "browser",
        "run",
        "resume",
        "report",
        "rebuild-archives",
        "review",
    ):
        assert command in result.stdout


def test_live_run_requires_authorization_flag(tmp_path: Path) -> None:
    shops = tmp_path / "shops.csv"
    shops.write_text("shop_url\nhttps://authorized.taobao.com/\n")
    result = CliRunner().invoke(
        app,
        ["run", "--shops", str(shops)],
        terminal_width=120,
    )
    assert result.exit_code != 0
    assert "--confirm-authorized" in strip_ansi(result.output)


def test_shop_csv_only_requires_url_and_deduplicates(tmp_path: Path) -> None:
    shops = tmp_path / "shops.csv"
    shops.write_text(
        "shop_url\nhttps://one.taobao.com/\nhttps://two.tmall.com/\nhttps://one.taobao.com/\n"
    )
    loaded = _load_shops(shops)
    assert [str(item.shop_url) for item in loaded] == [
        "https://one.taobao.com/",
        "https://two.tmall.com/",
    ]


def test_init_env_template_is_created_without_overwriting(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    assert _write_env_template(env_path) is True
    assert "SERPAPI_API_KEYS=" in env_path.read_text()

    env_path.write_text("SERPAPI_API_KEYS=keep-this-key\n")
    assert _write_env_template(env_path) is False
    assert env_path.read_text() == "SERPAPI_API_KEYS=keep-this-key\n"
