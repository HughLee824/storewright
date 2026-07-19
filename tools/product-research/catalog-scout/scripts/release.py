#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_DIR.parents[2]
PYPROJECT_PATH = PROJECT_DIR / "pyproject.toml"
CHANGELOG_PATH = PROJECT_DIR / "CHANGELOG.md"
LOCK_PATH = PROJECT_DIR / "uv.lock"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
TAG_PREFIX = "catalog-scout-v"


class ReleaseError(RuntimeError):
    pass


def parse_version(value: str) -> tuple[int, int, int]:
    if not VERSION_PATTERN.fullmatch(value):
        raise ReleaseError("version must use X.Y.Z format")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def current_version(pyproject: str) -> str:
    match = re.search(r'(?m)^version = "([^"]+)"$', pyproject)
    if not match:
        raise ReleaseError("project version was not found in pyproject.toml")
    return match.group(1)


def update_pyproject(pyproject: str, old_version: str, new_version: str) -> str:
    expected = f'version = "{old_version}"'
    if pyproject.count(expected) != 1:
        raise ReleaseError("pyproject.toml does not contain one unambiguous project version")
    return pyproject.replace(expected, f'version = "{new_version}"', 1)


def update_changelog(changelog: str, version: str, release_date: date) -> str:
    match = re.search(r"(?ms)^## Unreleased\s*\n(?P<body>.*?)(?=^## |\Z)", changelog)
    if not match:
        raise ReleaseError("CHANGELOG.md must contain an '## Unreleased' section")
    body = match.group("body").strip()
    if not body:
        raise ReleaseError("CHANGELOG.md 'Unreleased' section is empty")
    replacement = (
        f"## Unreleased\n\n"
        f"## {version} - {release_date.isoformat()}\n\n"
        f"{body}\n\n"
    )
    return changelog[: match.start()] + replacement + changelog[match.end() :].lstrip()


def run(
    command: list[str], *, capture: bool = False, cwd: Path = REPO_ROOT
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.strip() if capture else ""


def preflight(version: str) -> tuple[str, str, str]:
    old_pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")
    old_changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    old_lock = LOCK_PATH.read_text(encoding="utf-8")
    old_version = current_version(old_pyproject)
    if parse_version(version) <= parse_version(old_version):
        raise ReleaseError(f"new version must be greater than current version {old_version}")
    if run(["git", "branch", "--show-current"], capture=True) != "main":
        raise ReleaseError("releases must be created from main")
    if run(["git", "status", "--porcelain"], capture=True):
        raise ReleaseError("working tree must be clean before starting a release")
    tag = f"{TAG_PREFIX}{version}"
    if run(["git", "tag", "--list", tag], capture=True):
        raise ReleaseError(f"tag already exists: {tag}")
    update_changelog(old_changelog, version, date.today())
    return old_pyproject, old_changelog, old_lock


def release(version: str, *, push: bool, dry_run: bool) -> None:
    originals = preflight(version)
    old_pyproject, old_changelog, old_lock = originals
    old_version = current_version(old_pyproject)
    tag = f"{TAG_PREFIX}{version}"
    print(f"Catalog Scout {old_version} -> {version}")
    print(f"Tag: {tag}")
    print("Push: enabled" if push else "Push: disabled (local commit and tag only)")
    if dry_run:
        print("Dry run complete; no files or Git references were changed.")
        return

    committed = False
    try:
        PYPROJECT_PATH.write_text(
            update_pyproject(old_pyproject, old_version, version), encoding="utf-8"
        )
        CHANGELOG_PATH.write_text(
            update_changelog(old_changelog, version, date.today()), encoding="utf-8"
        )
        run(["uv", "lock"], cwd=PROJECT_DIR)
        run(["uv", "run", "--frozen", "ruff", "check", "."], cwd=PROJECT_DIR)
        run(["uv", "run", "--frozen", "pyright"], cwd=PROJECT_DIR)
        run(["uv", "run", "--frozen", "pytest", "-q"], cwd=PROJECT_DIR)
        changed = set(run(["git", "diff", "--name-only"], capture=True).splitlines())
        expected = {
            str(PYPROJECT_PATH.relative_to(REPO_ROOT)),
            str(CHANGELOG_PATH.relative_to(REPO_ROOT)),
            str(LOCK_PATH.relative_to(REPO_ROOT)),
        }
        if changed != expected:
            raise ReleaseError(
                "release changed unexpected files: " + ", ".join(sorted(changed - expected))
            )
        run(["git", "diff", "--check"])
        run(["git", "add", *sorted(expected)])
        run(["git", "commit", "-m", f"chore: release catalog scout {version}"])
        committed = True
        run(["git", "tag", "-a", tag, "-m", f"StoreWright Catalog Scout {version}"])
        if push:
            run(["git", "push", "--atomic", "origin", "main", tag])
    except (ReleaseError, subprocess.CalledProcessError):
        if not committed:
            PYPROJECT_PATH.write_text(old_pyproject, encoding="utf-8")
            CHANGELOG_PATH.write_text(old_changelog, encoding="utf-8")
            LOCK_PATH.write_text(old_lock, encoding="utf-8")
            run(
                [
                    "git",
                    "add",
                    str(PYPROJECT_PATH.relative_to(REPO_ROOT)),
                    str(CHANGELOG_PATH.relative_to(REPO_ROOT)),
                    str(LOCK_PATH.relative_to(REPO_ROOT)),
                ]
            )
        raise

    print(f"Created release commit and annotated tag {tag}.")
    if push:
        print("Pushed main and tag; the release workflow has been triggered.")
    else:
        print(f"Review locally, then publish with: git push --atomic origin main {tag}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Release StoreWright Catalog Scout")
    parser.add_argument("version", help="new semantic version in X.Y.Z format")
    parser.add_argument(
        "--push",
        action="store_true",
        help="atomically push main and the release tag to origin",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the release without changing files or Git references",
    )
    args = parser.parse_args()
    try:
        release(args.version, push=args.push, dry_run=args.dry_run)
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
