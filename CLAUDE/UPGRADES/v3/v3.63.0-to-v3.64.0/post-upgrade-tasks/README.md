# Post-Upgrade Tasks — v3.63.0 → v3.64.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after
upgrading** from v3.63.0 to v3.64.0. They are advisory only — nothing runs
them automatically.

## Task index

<!-- BEGIN TASK INDEX -->

| File                                           | Type            | Severity | Applies to                                              | One-line summary                                                                             |
| ---------------------------------------------- | --------------- | -------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `01-rewrite-plan-qa-json-level-to-severity.md` | workflow-change | critical | all (any project whose tooling parses `plan-qa --json`) | `plan-qa --json` now emits `severity` instead of `level` — rewrite every consuming call site |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not
   cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance,
   then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks
   should block the user's next step until acknowledged; `recommended` and
   `optional` tasks can be reported without blocking.
