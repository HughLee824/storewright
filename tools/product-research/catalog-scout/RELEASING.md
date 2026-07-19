# Releasing StoreWright Catalog Scout

Releases are published from tags named `catalog-scout-v<version>`.

## One-time PyPI setup

Create a pending Trusted Publisher for:

- PyPI project: `storewright-catalog-scout`
- GitHub owner: `HughLee824`
- Repository: `storewright`
- Workflow: `catalog-scout-release.yml`
- Environment: `pypi`

Create a matching `pypi` environment in the GitHub repository. The release workflow uses
OpenID Connect and does not require a stored PyPI API token.

## Release

Add release notes under `## Unreleased` in `CHANGELOG.md`, merge them into `main`, and ensure
the working tree is clean. Then run:

```bash
./scripts/release.py 0.1.2 --dry-run
./scripts/release.py 0.1.2
```

The script updates `pyproject.toml`, `uv.lock`, and `CHANGELOG.md`; runs Ruff, Pyright, and
Pytest; creates the release commit; and creates an annotated `catalog-scout-v<version>` tag.
It does not push by default. After reviewing the local commit and tag, publish them atomically:

```bash
git push --atomic origin main catalog-scout-v0.1.2
```

Alternatively, pass `--push` to let the script perform that final push. This triggers the
release workflow, so use it only when the release should be published immediately.

The workflow verifies that the tag and package versions match, tests the package, builds the
source and wheel distributions, publishes them to PyPI, and creates the GitHub Release.
