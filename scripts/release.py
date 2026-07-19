#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "release-tools.toml"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolConfig:
    name: str
    path: Path
    display_name: str
    tag_prefix: str
    version_file: Path
    version_pattern: str
    version_replacement: str
    changelog_file: Path
    managed_files: tuple[Path, ...]
    prepare_commands: tuple[tuple[str, ...], ...]
    check_commands: tuple[tuple[str, ...], ...]


def parse_version(value: str) -> tuple[int, int, int]:
    if not VERSION_PATTERN.fullmatch(value):
        raise ReleaseError("version must use X.Y.Z format")
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"release registry field must be a non-empty string: {field}")
    return value


def _commands(value: object, field: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise ReleaseError(f"release registry field must be an array: {field}")
    commands: list[tuple[str, ...]] = []
    for command in value:
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ReleaseError(f"release registry command is invalid: {field}")
        commands.append(tuple(command))
    return tuple(commands)


def tool_config_from_mapping(
    name: str, value: dict[str, Any], *, repo_root: Path = REPO_ROOT
) -> ToolConfig:
    relative_path = Path(_string(value.get("path"), f"tools.{name}.path"))
    tool_path = (repo_root / relative_path).resolve()
    if not tool_path.is_relative_to(repo_root.resolve()):
        raise ReleaseError(f"tool path escapes the repository: {name}")
    managed_value = value.get("managed_files")
    if not isinstance(managed_value, list) or not managed_value:
        raise ReleaseError(f"managed_files must be a non-empty array: {name}")

    def tool_file(raw: object, field: str) -> Path:
        path = (tool_path / _string(raw, field)).resolve()
        if not path.is_relative_to(tool_path):
            raise ReleaseError(f"tool file escapes its directory: {field}")
        return path

    managed_files = tuple(
        tool_file(item, f"tools.{name}.managed_files") for item in managed_value
    )
    version_file = tool_file(value.get("version_file"), f"tools.{name}.version_file")
    changelog_file = tool_file(
        value.get("changelog_file"), f"tools.{name}.changelog_file"
    )
    if version_file not in managed_files or changelog_file not in managed_files:
        raise ReleaseError(f"version and changelog files must be managed: {name}")
    version_pattern = _string(value.get("version_pattern"), f"tools.{name}.version_pattern")
    try:
        re.compile(version_pattern)
    except re.error as error:
        raise ReleaseError(f"invalid version pattern: {name}") from error
    version_replacement = _string(
        value.get("version_replacement"), f"tools.{name}.version_replacement"
    )
    if "{version}" not in version_replacement:
        raise ReleaseError(f"version replacement must contain '{{version}}': {name}")
    return ToolConfig(
        name=name,
        path=tool_path,
        display_name=_string(value.get("display_name"), f"tools.{name}.display_name"),
        tag_prefix=_string(value.get("tag_prefix"), f"tools.{name}.tag_prefix"),
        version_file=version_file,
        version_pattern=version_pattern,
        version_replacement=version_replacement,
        changelog_file=changelog_file,
        managed_files=managed_files,
        prepare_commands=_commands(value.get("prepare_commands", []), "prepare_commands"),
        check_commands=_commands(value.get("check_commands", []), "check_commands"),
    )


def load_tools(path: Path = REGISTRY_PATH) -> dict[str, ToolConfig]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ReleaseError(f"cannot read release registry: {path}") from error
    tools = raw.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise ReleaseError("release registry does not define any tools")
    result: dict[str, ToolConfig] = {}
    for name, value in tools.items():
        if not isinstance(name, str) or not isinstance(value, dict):
            raise ReleaseError("release registry contains an invalid tool entry")
        result[name] = tool_config_from_mapping(name, value)
    return result


def current_version(config: ToolConfig, content: str) -> str:
    matches = list(re.finditer(config.version_pattern, content))
    if len(matches) != 1 or len(matches[0].groups()) != 1:
        raise ReleaseError(f"version pattern must produce exactly one capture: {config.name}")
    return matches[0].group(1)


def update_version(config: ToolConfig, content: str, version: str) -> str:
    matches = list(re.finditer(config.version_pattern, content))
    if len(matches) != 1:
        raise ReleaseError(f"version pattern did not match exactly once: {config.name}")
    replacement = config.version_replacement.format(version=version)
    return re.sub(config.version_pattern, lambda _match: replacement, content, count=1)


def update_changelog(changelog: str, version: str, release_date: date) -> str:
    match = re.search(r"(?ms)^## Unreleased\s*\n(?P<body>.*?)(?=^## |\Z)", changelog)
    if not match:
        raise ReleaseError("changelog must contain an '## Unreleased' section")
    body = match.group("body").strip()
    if not body:
        raise ReleaseError("changelog 'Unreleased' section is empty")
    replacement = (
        f"## Unreleased\n\n"
        f"## {version} - {release_date.isoformat()}\n\n"
        f"{body}\n\n"
    )
    return changelog[: match.start()] + replacement + changelog[match.end() :].lstrip()


def run(
    command: list[str] | tuple[str, ...], *, capture: bool = False, cwd: Path = REPO_ROOT
) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout.rstrip("\r\n") if capture else ""


def porcelain_paths(output: str) -> set[str]:
    return {
        line[3:].split(" -> ")[-1]
        for line in output.splitlines()
        if len(line) > 3
    }


def preflight(config: ToolConfig, version: str) -> tuple[dict[Path, str], str]:
    originals: dict[Path, str] = {}
    for path in config.managed_files:
        try:
            originals[path] = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ReleaseError(f"cannot read managed file: {path}") from error
    old_version = current_version(config, originals[config.version_file])
    if parse_version(version) <= parse_version(old_version):
        raise ReleaseError(f"new version must be greater than current version {old_version}")
    if run(["git", "branch", "--show-current"], capture=True) != "main":
        raise ReleaseError("releases must be created from main")
    if run(["git", "status", "--porcelain"], capture=True):
        raise ReleaseError("working tree must be clean before starting a release")
    tag = f"{config.tag_prefix}{version}"
    if run(["git", "tag", "--list", tag], capture=True):
        raise ReleaseError(f"tag already exists: {tag}")
    update_changelog(originals[config.changelog_file], version, date.today())
    return originals, old_version


def release(config: ToolConfig, version: str, *, push: bool, dry_run: bool) -> None:
    originals, old_version = preflight(config, version)
    tag = f"{config.tag_prefix}{version}"
    print(f"{config.display_name} {old_version} -> {version}")
    print(f"Tag: {tag}")
    print("Push: enabled" if push else "Push: disabled (local commit and tag only)")
    if dry_run:
        print("Dry run complete; no files or Git references were changed.")
        return

    allowed = {str(path.relative_to(REPO_ROOT)) for path in config.managed_files}
    required = {
        str(config.version_file.relative_to(REPO_ROOT)),
        str(config.changelog_file.relative_to(REPO_ROOT)),
    }
    committed = False
    try:
        config.version_file.write_text(
            update_version(config, originals[config.version_file], version), encoding="utf-8"
        )
        config.changelog_file.write_text(
            update_changelog(originals[config.changelog_file], version, date.today()),
            encoding="utf-8",
        )
        for command in config.prepare_commands:
            run(command, cwd=config.path)
        for command in config.check_commands:
            run(command, cwd=config.path)
        status = run(["git", "status", "--porcelain", "--untracked-files=all"], capture=True)
        changed = porcelain_paths(status)
        unexpected = changed - allowed
        missing = required - changed
        if unexpected:
            raise ReleaseError("release changed unexpected files: " + ", ".join(sorted(unexpected)))
        if missing:
            raise ReleaseError(
                "release did not update required files: " + ", ".join(sorted(missing))
            )
        run(["git", "diff", "--check"])
        run(["git", "add", *sorted(changed)])
        run(["git", "commit", "-m", f"chore: release {config.name} {version}"])
        committed = True
        run(["git", "tag", "-a", tag, "-m", f"{config.display_name} {version}"])
        if push:
            run(["git", "push", "--atomic", "origin", "main", tag])
    except (ReleaseError, subprocess.CalledProcessError):
        if not committed:
            for path, content in originals.items():
                path.write_text(content, encoding="utf-8")
            run(["git", "add", *sorted(allowed)])
        raise

    print(f"Created release commit and annotated tag {tag}.")
    if push:
        print("Pushed main and tag; the release workflow has been triggered.")
    else:
        print(f"Review locally, then publish with: git push --atomic origin main {tag}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Release a StoreWright tool")
    parser.add_argument("tool", nargs="?", help="tool name from release-tools.toml")
    parser.add_argument("version", nargs="?", help="new semantic version in X.Y.Z format")
    parser.add_argument("--list", action="store_true", help="list registered tools")
    parser.add_argument(
        "--push", action="store_true", help="atomically push main and the release tag to origin"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the release without changing files or Git references",
    )
    args = parser.parse_args()
    try:
        tools = load_tools()
        if args.list:
            for name, config in sorted(tools.items()):
                print(f"{name}\t{config.display_name}\t{config.tag_prefix}<version>")
            return 0
        if not args.tool or not args.version:
            parser.error("tool and version are required unless --list is used")
        config = tools.get(args.tool)
        if config is None:
            raise ReleaseError(f"unknown tool: {args.tool}; use --list to inspect choices")
        release(config, args.version, push=args.push, dry_run=args.dry_run)
    except (ReleaseError, subprocess.CalledProcessError) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
