from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).parents[1]
SCRIPT = REPO_ROOT / "scripts" / "release.py"
SPEC = importlib.util.spec_from_file_location("storewright_release", SCRIPT)
assert SPEC and SPEC.loader
release_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_script
SPEC.loader.exec_module(release_script)


class ReleaseScriptTests(unittest.TestCase):
    def catalog_config(self):
        return release_script.load_tools()["catalog-scout"]

    def test_registry_exposes_independent_catalog_scout_release(self) -> None:
        config = self.catalog_config()
        self.assertEqual(config.tag_prefix, "catalog-scout-v")
        self.assertEqual(config.path.name, "catalog-scout")
        self.assertEqual(config.version_file.name, "pyproject.toml")

    def test_relative_version_bumps_are_resolved_from_current_manifest(self) -> None:
        self.assertEqual(release_script.resolve_version("0.1.1", "patch"), "0.1.2")
        self.assertEqual(release_script.resolve_version("0.1.1", "minor"), "0.2.0")
        self.assertEqual(release_script.resolve_version("0.1.1", "major"), "1.0.0")
        self.assertEqual(release_script.resolve_version("0.1.1", "0.3.0"), "0.3.0")

    def test_version_updater_supports_other_tool_manifests(self) -> None:
        tool = release_script.tool_config_from_mapping(
            "future-tool",
            {
                "path": "future-tool",
                "display_name": "Future Tool",
                "tag_prefix": "future-tool-v",
                "version_file": "package.json",
                "version_pattern": r'(?m)^  "version": "([^"]+)",$',
                "version_replacement": '  "version": "{version}",',
                "changelog_file": "CHANGELOG.md",
                "managed_files": ["package.json", "CHANGELOG.md", "lockfile"],
                "prepare_commands": [["package-manager", "lock"]],
                "check_commands": [["package-manager", "test"]],
            },
            repo_root=Path("/tmp/storewright-release-test"),
        )
        manifest = '{\n  "version": "1.2.3",\n}\n'

        self.assertEqual(release_script.current_version(tool, manifest), "1.2.3")
        self.assertIn(
            '"version": "1.2.4"',
            release_script.update_version(tool, manifest, "1.2.4"),
        )
        self.assertEqual(tool.tag_prefix, "future-tool-v")

    def test_project_and_changelog_updates_are_targeted(self) -> None:
        config = self.catalog_config()
        pyproject = '[project]\nname = "example"\nversion = "0.1.1"\n'
        changelog = """# Changelog

## Unreleased

- Add release automation.

## 0.1.1 - 2026-07-19

- Previous release.
"""
        updated_project = release_script.update_version(config, pyproject, "0.1.2")
        updated_changelog = release_script.update_changelog(
            changelog, "0.1.2", date(2026, 7, 20)
        )

        self.assertIn('version = "0.1.2"', updated_project)
        self.assertIn("## Unreleased\n\n## 0.1.2 - 2026-07-20", updated_changelog)
        self.assertIn("- Add release automation.", updated_changelog)
        self.assertIn("## 0.1.1 - 2026-07-19", updated_changelog)

    def test_empty_unreleased_section_is_rejected(self) -> None:
        with self.assertRaises(release_script.ReleaseError):
            release_script.update_changelog(
                "# Changelog\n\n## Unreleased\n\n## 0.1.1 - 2026-07-19\n",
                "0.1.2",
                date(2026, 7, 20),
            )

    def test_porcelain_status_preserves_first_path_character(self) -> None:
        output = (
            " M tools/product-research/catalog-scout/CHANGELOG.md\n"
            "?? generated.txt\n"
        )
        self.assertEqual(
            release_script.porcelain_paths(output),
            {
                "tools/product-research/catalog-scout/CHANGELOG.md",
                "generated.txt",
            },
        )

    def test_captured_command_output_keeps_leading_status_space(self) -> None:
        completed = SimpleNamespace(stdout=" M tools/file.txt\n")
        with patch.object(release_script.subprocess, "run", return_value=completed):
            output = release_script.run(["git", "status"], capture=True)
        self.assertEqual(output, " M tools/file.txt")


if __name__ == "__main__":
    unittest.main()
