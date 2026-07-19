# Catalog Scout operations

## Contents

- Workspace discovery
- Read-only preflight
- Shop input
- New Mock run
- New live run
- Resume and run selection
- Reports, archives, and review
- Failure handling

## Workspace discovery

All default paths are relative to the working directory. Run every command for a task from the same persistent workspace.

Accept an explicit workspace path from the user. Otherwise:

1. Check the current directory for `.env` and `runtime/storewright_catalog_scout.db`.
2. Check only nearby paths already named in the conversation or recent command context.
3. Do not recursively scan the entire home directory.
4. If no workspace is found, use `storewright-setup` to initialize one.
5. If several workspaces are plausible, show their human-readable paths and ask which one to use.

Resolve the chosen workspace to an absolute path before writing. Keep it separate from the source checkout for a normal PyPI installation.

## Read-only preflight

From the workspace:

1. Run `storewright-scout --help` and `storewright-scout run --help`.
2. Confirm `.env`, `runtime/storewright_catalog_scout.db`, `runtime/chrome-profile/`, and `runtime/artifacts/` exist.
3. Run `storewright-scout browser diagnose`. Use only its redacted configured/not-configured results.
4. Confirm the selected CSV exists and has the exact `shop_url` header.
5. For live work, confirm Chrome is found and at least one SerpApi key is reported configured.

Diagnosis after Chrome closes will show CDP, Playwright, and Browser Use as inactive or unchecked. For a full browser connection test, keep `browser login` waiting for Enter and run diagnosis from a second terminal in the same workspace.

## Shop input

Accept only shop URLs the user says are owned, controlled, or explicitly authorized. Current live adapters support Taobao and Tmall.

Create UTF-8 CSV in this shape:

```csv
shop_url
https://shop-a.taobao.com/
https://shop-b.tmall.com/
```

Trim whitespace, reject empty entries, and remove exact duplicates. Do not silently replace an existing file. Reuse it only when its shops match the request; otherwise create a new descriptive filename and state it before writing.

Do not put shop names, keys, credentials, notes, or unrelated columns into the input unless the installed CLI explicitly supports them.

## New Mock run

Use Mock only for installation/workflow validation. It does not visit shops, start Chrome, call SerpApi, or require live authorization.

1. Run:

```bash
storewright-scout run --shops <shops.csv> --seed 20260718 --mock-vision
```

2. Capture the printed `run_id` and report path.
3. Require exit code 0 and verify `runtime/artifacts/<run_id>/report.html` plus `summary.json` exist.

Do not present Mock product results as real research findings.

## New live run

Before live access, require an explicit statement that every URL in the selected CSV is authorized. Then:

1. Confirm SerpApi is configured through redacted diagnosis.
2. Run `storewright-scout browser login` when the dedicated profile is not already authenticated. Let the user log in manually.
3. Stop if login, verification, or blocking remains unresolved.
4. Run:

```bash
storewright-scout run --shops <shops.csv> --seed 20260718 --confirm-authorized
```

Keep early stopping enabled unless the user explicitly asks to disable it and understands that doing so may increase page visits and API use. Use `--no-early-stop` only for that explicit choice.

The command launches and later stops its dedicated Chrome process. Record the `run_id` immediately from output. Do not start a second live run merely because the first is slow.

## Resume and run selection

Resume uses the stored configuration snapshot and only unfinished work:

```bash
storewright-scout resume --run-id <run_id> --confirm-authorized
```

Omit `--confirm-authorized` only when the stored run is Mock. Require fresh explicit authorization for a live resume.

When no run ID is provided:

1. List direct child directories under `runtime/artifacts/` that are valid UUIDs, ordered by modification time.
2. Read only `summary.json` from the newest plausible candidates.
3. Compare `run_status`, `generated_at`, report presence, and the user's described shops/time.
4. Select automatically only when one candidate clearly matches; otherwise ask the user to choose between concise candidates.
5. Never infer the run ID from a product or shop subdirectory.

If the summary is missing but the UUID is known, run `report` once to regenerate it. Do not modify SQLite manually.

## Reports, archives, and review

```bash
storewright-scout report --run-id <run_id>
storewright-scout rebuild-archives --run-id <run_id>
storewright-scout review list --run-id <run_id>
```

- `report` is offline and deterministically regenerates `shops.csv`, `products.csv`, `summary.json`, and `report.html`.
- `rebuild-archives` is offline and only reparses saved HTML, fills supported structured fields, and rebuilds clean flat product archives.
- `review list` displays shops requiring review or having insufficient data.

Verify generated files under `runtime/artifacts/<run_id>/`. Do not claim success from terminal text alone.

## Failure handling

- **CLI missing or workspace uninitialized:** hand off to `storewright-setup`, then return to the requested operation.
- **SerpApi missing/exhausted/rate-limited:** pause; ask the user to update `.env` locally. Never request the key in chat.
- **Login/verification/blocked page:** pause and let the user resolve it manually; never bypass it.
- **Run paused:** identify and explain the pause reason before offering resume.
- **Run failed:** preserve all artifacts, summarize the last error without secrets, correct only the proven cause, then ask before live retry if authorization or cost is involved.
- **Unwritable `tldextract` cache warning:** if snapshot fallback is reported and the command otherwise succeeds with expected artifacts, treat it as non-fatal.
- **Ambiguous workspace or run:** stop and ask one concrete path/run selection question.
