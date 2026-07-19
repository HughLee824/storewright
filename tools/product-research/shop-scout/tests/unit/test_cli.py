from pathlib import Path

from typer.testing import CliRunner

from shop_scout.cli import _load_shops, app


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
    result = CliRunner().invoke(app, ["run", "--shops", str(shops)])
    assert result.exit_code != 0
    assert "--confirm-authorized" in result.output


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
