# Catalog Scout setup profile

## Identity

- Purpose: auditably screen authorized Taobao/Tmall product catalogs using SerpApi Google Lens and save qualified product archives locally.
- Package: `storewright-catalog-scout`
- Executable: `storewright-scout`
- Release maturity: alpha
- Python: `>=3.12,<3.14`
- Preferred user install: `uv tool install --python 3.13 storewright-catalog-scout`
- Upgrade: `uv tool upgrade storewright-catalog-scout`
- Uninstall executable only: `uv tool uninstall storewright-catalog-scout`
- Help validation: `storewright-scout --help`

Use the local `pyproject.toml`, README, and CLI help to confirm these facts before acting.

## Prerequisites

- `uv`: required for the preferred install path.
- Chrome/Chromium: required only for live catalog runs and manual login.
- `SERPAPI_API_KEYS`: required only for live image search; comma-separated keys are supported.
- `DEEPSEEK_API_KEY`: optional navigation fallback; not used for per-product decisions.

Do not print secret values. Verify only configured/not configured.

## Workspace and initialization

Use a dedicated persistent workspace outside the source checkout for a normal PyPI install. Initialize from that directory:

```bash
storewright-scout init
```

The initializer preserves an existing `.env` and creates or upgrades:

- `.env`
- `runtime/storewright_catalog_scout.db`
- `runtime/chrome-profile/`
- `runtime/artifacts/`

All default paths are relative to the current working directory. Run future commands from the same workspace.

Create `shops.csv` without overwriting an existing file:

```csv
shop_url
https://authorized-shop.taobao.com/
```

The example URL is for offline validation only. Replace it with explicitly authorized shop URLs before live use.

## Offline acceptance

Mock mode does not open a shop, start Chrome, use SerpApi, or require `--confirm-authorized`.

1. Preserve the existing `DETAIL_PAGE_INTERVAL_SECONDS` value.
2. Temporarily set `DETAIL_PAGE_INTERVAL_SECONDS=0` in `.env` so the fixture does not wait 30 seconds per detail.
3. Run:

```bash
storewright-scout run --shops shops.csv --seed 20260718 --mock-vision
```

4. Require exit code 0 and verify `runtime/artifacts/<run_id>/report.html` exists.
5. Restore the previous detail interval; use `30` when there was no prior value.

Warnings about an unwritable `tldextract` cache do not invalidate a successful run when the bundled snapshot fallback is used and the report exists.

## Browser login and diagnosis

Run from the workspace:

```bash
storewright-scout browser login
```

The user must log in manually. While this command is still waiting for Enter and its Chrome window remains open, use a second terminal in the same workspace for a full connection check:

```bash
storewright-scout browser diagnose
```

After Enter closes Chrome, diagnosis can still check paths, storage, database, and configured providers, but CDP/Playwright/Browser Use will appear inactive or unchecked.

## Live gate

Do not run this merely as installation validation. Require the user to confirm every input shop is owned, controlled, or explicitly authorized, then run:

```bash
storewright-scout run --shops shops.csv --seed 20260718 --confirm-authorized
```

Stop on login challenges, CAPTCHA, sliders, or blocking pages. Never bypass them.

Resume a live run only with the original workspace and explicit authorization:

```bash
storewright-scout resume --run-id <run_id> --confirm-authorized
```

Offline follow-up commands:

```bash
storewright-scout report --run-id <run_id>
storewright-scout rebuild-archives --run-id <run_id>
storewright-scout review list --run-id <run_id>
```

## Common setup failures

- Command missing after install: run `uv tool update-shell` with approval, restart the shell, or validate using the resolved absolute executable.
- Chrome missing: install Chrome with approval or set `CHROME_EXECUTABLE` to an existing absolute path.
- `SERPAPI_API_KEYS is required`: expected for live mode; configure `.env` locally or use Mock mode for setup validation.
- Existing workspace: preserve it, inspect current state, and rerun the idempotent initializer. Do not recreate or delete it.
