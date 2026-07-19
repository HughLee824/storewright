---
name: storewright-scout
description: Operate StoreWright Catalog Scout end to end for non-technical users. Use when a user wants to prepare a shop list, run an offline test or authorized Taobao/Tmall screening, continue a paused run, regenerate or open a report, rebuild archives, inspect review items, find a run ID, understand product/shop decisions, or troubleshoot an existing Scout task without handling CLI commands themselves.
---

# StoreWright Scout

Operate Catalog Scout for the user. Perform safe local actions instead of returning a command tutorial. Match the user's language, keep explanations plain, and ask for intervention only at a genuine login, secret, authorization, verification, or ambiguous-run boundary.

## Load task-specific guidance

- Read [operations.md](references/operations.md) before running, resuming, diagnosing, or changing a Scout task.
- Read [results.md](references/results.md) before summarizing a report, shop decision, product status, error, or review queue.
- When the CLI is missing, the workspace is not initialized, or installation is broken, invoke `storewright-setup` first. If the companion Skill is unavailable, explain that it must be installed from the same StoreWright source and offer to install it with approval. Return here after setup passes.

Treat the installed CLI's `--help`, local package metadata, and generated report as authoritative when bundled instructions differ.

## Interaction contract

- Begin by identifying the user's outcome: new screening, test, resume, report, archive rebuild, review, or explanation.
- Ask at most one blocking question at a time. Do not ask for technical choices the tool can determine safely.
- State which workspace and input file will be used before writing or running.
- Preserve existing files. Create a new clearly named shop CSV when the requested inputs differ from an existing one.
- Give concise progress updates during long runs, including the current phase and whether user action is needed.
- Never make the user interpret raw stack traces or database rows. Explain the cause and the next safe action.

## Safety boundaries

- Never read, print, log, copy, transmit, or expose API keys, passwords, cookies, browser profiles, or complete `.env` contents. Use the CLI's redacted diagnosis to check configured/not configured state.
- Never place secrets in chat, shell arguments, CSV files, reports, or source control. Ask the user to enter them directly into the local `.env` file.
- Require explicit confirmation that every shop is owned, controlled, or authorized before adding `--confirm-authorized` to a live `run` or `resume`.
- Do not treat a prior authorization for different shop inputs as authorization for a new live run.
- Never bypass login challenges, CAPTCHA, sliders, blocking pages, rate limits, or platform controls. Pause and hand control to the user.
- Do not delete or overwrite `.env`, SQLite data, Chrome profiles, input files, reports, evidence, or product archives.
- Do not run purchases, favorites, seller contact, Shopify imports, publishing, or any unrelated mutation.

## Route the request

### Start a new task

1. Locate or establish the persistent workspace following [operations.md](references/operations.md).
2. Gather the authorized Taobao/Tmall shop URLs. If the user has not provided any, ask for them in plain language.
3. Create or validate the shop CSV without overwriting existing input.
4. Run the preflight checks.
5. If the user asks to test the installation, use Mock mode only.
6. If the user asks for real screening, obtain explicit shop authorization, ensure login and SerpApi configuration are ready, then run live.
7. Capture the `run_id`, status, and report path. Verify the report exists.
8. Explain the outcome using [results.md](references/results.md).

### Continue or recover a task

1. Use the user-provided `run_id`. If absent, identify candidate runs in the workspace as described in [operations.md](references/operations.md); ask the user only when more than one plausible run remains.
2. Inspect the generated summary/report and determine whether the run is mock or live without exposing configuration secrets.
3. Resolve login, verification, missing configuration, or other blocking conditions before resuming.
4. Require renewed explicit authorization for live resume.
5. Run `resume`, regenerate the report, verify artifacts, and explain the new status.

### Inspect results

Regenerate the report when needed, then use the HTML/JSON/CSV artifacts instead of querying or editing the database directly. Summarize decisions, counts, caveats, and manual actions following [results.md](references/results.md). Open a local HTML report only when the user asks and the environment grants GUI approval; otherwise provide its absolute path.

### Rebuild or review

- Use `rebuild-archives` only for offline reparsing of already saved HTML and archive cleanup.
- Use `review list` to surface stores needing human judgment or having insufficient data.
- Explain that neither command re-runs live shop discovery or proves product uniqueness.

## Completion criteria

Do not call the request complete until:

- the exact workspace and input/run ID are known;
- the requested CLI command exits or pauses in a understood state;
- expected report or archive artifacts are verified on disk;
- temporary Mock settings are restored;
- the user receives the run status, report path, key findings, caveats, and one next action if any.
