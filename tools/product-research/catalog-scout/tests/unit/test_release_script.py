from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("catalog_scout_release", SCRIPT)
assert SPEC and SPEC.loader
release_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_script)


def test_version_must_be_strictly_newer_semver() -> None:
    assert release_script.parse_version("1.2.3") == (1, 2, 3)
    with pytest.raises(release_script.ReleaseError):
        release_script.parse_version("v1.2.3")


def test_project_and_changelog_updates_are_targeted() -> None:
    pyproject = '[project]\nname = "example"\nversion = "0.1.1"\n'
    changelog = """# Changelog

## Unreleased

- Add release automation.

## 0.1.1 - 2026-07-19

- Previous release.
"""

    updated_project = release_script.update_pyproject(pyproject, "0.1.1", "0.1.2")
    updated_changelog = release_script.update_changelog(
        changelog, "0.1.2", date(2026, 7, 20)
    )

    assert 'version = "0.1.2"' in updated_project
    assert "## Unreleased\n\n## 0.1.2 - 2026-07-20" in updated_changelog
    assert "- Add release automation." in updated_changelog
    assert "## 0.1.1 - 2026-07-19" in updated_changelog


def test_empty_unreleased_section_is_rejected() -> None:
    with pytest.raises(release_script.ReleaseError):
        release_script.update_changelog(
            "# Changelog\n\n## Unreleased\n\n## 0.1.1 - 2026-07-19\n",
            "0.1.2",
            date(2026, 7, 20),
        )
