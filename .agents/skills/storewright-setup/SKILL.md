---
name: storewright-setup
description: Install, upgrade, initialize, diagnose, repair, validate, or uninstall StoreWright tools for non-technical users. Use when a user asks an agent to set up StoreWright, Catalog Scout, a future StoreWright CLI, its prerequisites, workspace, configuration, browser profile, or offline smoke test, or says they want StoreWright ready without handling terminal commands themselves.
---

# StoreWright Setup

Set up the requested StoreWright tool end to end. Perform safe actions for the user; do not merely return a command list. Match the user's language and explain outcomes without assuming terminal knowledge.

## Load the right context

1. Locate the StoreWright repository when available.
2. Read the repository root `README.md` and the selected tool's package metadata, CLI entry point, `.env.example`, and README. Treat local code and `--help` output as the source of truth.
3. Read [tool-discovery.md](references/tool-discovery.md) before selecting or installing a tool.
4. Read the matching profile only after selecting a tool. For Catalog Scout, read [catalog-scout.md](references/catalog-scout.md).

If installed-package behavior differs from a bundled profile, follow the installed version and tell the user about the mismatch.

## Interaction contract

- Lead with what you can complete automatically.
- Ask at most one blocking question at a time. Use plain-language choices when multiple tools could satisfy the request.
- State assumptions before creating a workspace or choosing an install channel.
- Request approval through the active agent environment when a command installs software, changes shell configuration, opens a GUI, or needs elevated access.
- Explain an approval in one sentence: what changes, where, and why.
- Continue through diagnosis and safe repair until the success criteria pass or user input is genuinely required.
- Never ask a non-technical user to interpret raw logs. Summarize the cause and next action.

## Safety boundaries

- Never read, print, log, copy, or send API keys, passwords, cookies, browser profiles, or complete `.env` contents.
- Ask the user to enter secrets directly into the local configuration file or provider UI. Verify only whether a value is configured.
- Never overwrite an existing `.env`, database, browser profile, input file, or artifact directory. Preserve existing work and use idempotent commands where available.
- Do not run live shop access, paid APIs, mutations, purchases, publishing, or imports unless the user explicitly requested that action and confirmed authorization.
- Do not bypass login challenges, CAPTCHA, sliders, rate limits, or platform controls. Stop and hand control to the user.
- Treat uninstalling a package separately from deleting its workspace. Never delete workspaces or runtime data without explicit confirmation and an exact path.

## Setup workflow

### 1. Translate the request into success criteria

Determine whether the user wants a fresh install, upgrade, repair, configuration, validation, or uninstall. A fresh setup succeeds only when:

- the requested tool and supported runtime are installed;
- its CLI help command exits successfully;
- a dedicated workspace is initialized without overwriting data;
- prerequisites are detected or clearly marked as optional/blocked;
- an offline or no-cost smoke test passes when the tool provides one;
- the user receives one simple next action for any secret, login, or authorization gate.

### 2. Discover the tool

Follow [tool-discovery.md](references/tool-discovery.md). If only one released tool matches a vague request such as “安装 StoreWright,” select it, state the assumption, and proceed. If several materially different tools match, briefly describe their outcomes and ask the user which outcome they want.

Do not infer future tools from planned directory names. Install only a tool backed by package metadata or an explicit tool profile.

### 3. Run read-only preflight checks

Inspect:

- operating system, architecture, and active shell;
- required runtime and package manager versions;
- whether the CLI is already installed, its version, and its resolved executable path;
- tool-specific prerequisites such as Chrome;
- the proposed workspace and whether it contains existing data.

Prefer upgrading or repairing an existing compatible installation over creating duplicates. Do not expose unrelated environment variables or credentials in diagnostic output.

### 4. Install through the supported channel

Prefer the tool profile's released package channel for non-technical users. Use a source checkout only when the user explicitly wants development mode, the package is unavailable, or the profile requires it.

After installation:

1. Run the CLI help or version command.
2. If the command is missing, inspect the package manager's tool directory and PATH.
3. Apply the smallest supported PATH fix with approval, then open a fresh shell or invoke the absolute executable for validation.
4. Record the install channel and installed version for the final handoff.

### 5. Create and initialize a workspace

Use the user-provided directory. If none is provided, state that you will use a dedicated `StoreWright/<tool-name>` directory under the user's home directory and resolve it to an absolute path before writing.

Before initialization, inspect the exact target. Keep source repositories separate from user runtime workspaces unless the tool is intentionally running in development mode. Run the tool's initializer and verify each documented output exists.

When configuration requires secrets, create or preserve the template, point the user to the exact file, and pause only if the next validation truly requires the secret.

### 6. Validate safely

Run the cheapest deterministic validation first:

1. CLI help/version;
2. configuration and filesystem diagnosis;
3. offline/mock smoke test;
4. browser diagnosis while the user-controlled login window remains open, when applicable;
5. live validation only with explicit authorization.

Use a disposable input or clearly labeled example for smoke tests. Restore temporary validation settings afterward. Confirm expected reports or artifacts exist rather than trusting only exit code text.

### 7. Hand off in plain language

Report:

- whether setup passed, partially passed, or is blocked;
- installed tool, version, and install channel;
- executable path and workspace path;
- validation performed and the key artifact/report path;
- the user's single next action;
- how to start the tool next time;
- any optional prerequisites not configured.

Do not paste verbose logs unless the user asks.

## Upgrade, repair, and uninstall

- **Upgrade:** identify the existing channel, use its supported upgrade command, rerun help and offline validation, and preserve the workspace.
- **Repair:** reproduce the failure, check PATH/runtime/config/workspace/browser in that order, make the smallest safe change, and rerun the failing check.
- **Uninstall:** confirm the exact package and channel, uninstall only the executable environment, and explicitly state that workspace data remains. Ask separately before removing any data.

## Maintaining future tool support

Keep this core workflow tool-agnostic. When a new StoreWright tool ships, add one profile under `references/` following [tool-discovery.md](references/tool-discovery.md). Put tool-specific commands and gates in that profile rather than expanding the main workflow.
