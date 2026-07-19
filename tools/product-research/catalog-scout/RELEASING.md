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

1. Update `version` in `pyproject.toml` and `CHANGELOG.md`.
2. Run the local quality checks documented in `README.md`.
3. Merge the release commit into `main`.
4. Create and push an annotated tag:

   ```bash
   git tag -a catalog-scout-v0.1.0 -m "StoreWright Catalog Scout 0.1.0"
   git push origin catalog-scout-v0.1.0
   ```

The workflow verifies that the tag and package versions match, tests the package, builds the
source and wheel distributions, publishes them to PyPI, and creates the GitHub Release.
