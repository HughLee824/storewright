# Tool discovery and profile contract

Use this order to discover supported StoreWright tools:

1. Inspect `tools/**/pyproject.toml`, `package.json`, `Cargo.toml`, or equivalent package metadata.
2. Confirm a user-facing CLI entry point and read its `--help` output.
3. Read the tool README and configuration example.
4. Match a profile in this directory.
5. Treat the repository metadata and installed CLI as authoritative when a profile is stale.

Do not treat an empty or planned directory as an installable tool.

## Current profiles

| User outcome | Tool | Profile |
| --- | --- | --- |
| Screen authorized Taobao/Tmall catalogs using image-match evidence | Catalog Scout | `catalog-scout.md` |

## Profile format for future tools

Create `references/<tool-slug>.md` containing only operational facts:

- user-facing purpose and common aliases;
- release maturity and supported platforms/runtimes;
- package name, install channel, executable, help/version commands;
- required and optional external prerequisites;
- safe initializer and outputs, including overwrite behavior;
- workspace and configuration paths;
- secret names without example secret values;
- minimal input template;
- deterministic offline/no-cost acceptance command and expected artifact;
- live-action authorization gates;
- resume, upgrade, repair, and uninstall commands;
- known failure signatures that change the setup workflow.

Update the current profiles table when adding a profile. Keep general interaction and safety rules in `SKILL.md`, not in individual profiles.
