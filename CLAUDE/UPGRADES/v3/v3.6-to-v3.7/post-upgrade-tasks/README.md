# Post-Upgrade Tasks — v3.6 → v3.7

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** — populated with the tasks that ship for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from the source version to this target version. They are advisory only — nothing runs them automatically.

## Task index

| File                      | Type            | Severity    | Applies to              | One-line summary                                                                          |
| ------------------------- | --------------- | ----------- | ----------------------- | ----------------------------------------------------------------------------------------- |
| `01-prune-legacy-venv.md` | workflow-change | recommended | all pre-v3.7.0 installs | Verify legacy `untracked/venv/` is removed after the fingerprint-keyed venv is installed. |

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
