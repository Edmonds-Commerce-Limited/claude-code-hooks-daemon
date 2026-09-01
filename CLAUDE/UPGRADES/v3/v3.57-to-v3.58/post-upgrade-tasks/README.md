# Post-Upgrade Tasks — v3.57 → v3.58

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from v3.57 to v3.58. They are advisory only — nothing runs them automatically.

## Task index

<!-- BEGIN TASK INDEX -->

| File                                         | Type             | Severity | Applies to                                                                                                                         | One-line summary                                                                                                                    |
| -------------------------------------------- | ---------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `01-migrate-monorepo-subproject-patterns.md` | config-migration | critical | any project setting `handlers.pre_tool_use.markdown_organization.options.monorepo_subproject_patterns` to a non-empty pattern list | The option is removed outright (hard config-validation error); migrate to declared `projects:` using the printed paste-ready block. |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip the task if your project never set `monorepo_subproject_patterns`, or it is `null`/empty (that shape is auto-cleaned and never blocks startup).
2. Otherwise open `01-migrate-monorepo-subproject-patterns.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user. This task is `critical` — the daemon will refuse to start with a non-empty legacy pattern list until it is migrated, so it should block the user's next step until acknowledged.
