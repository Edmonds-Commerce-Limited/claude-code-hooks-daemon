# Post-Upgrade Tasks — v3.18.3 → v3.19.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** — populate it with the tasks that ship for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from v3.18.3 to v3.19.0. They are advisory only — nothing runs them automatically.

## Task index

<!-- BEGIN TASK INDEX — populated from UNRELEASED/ at release time -->

| File                                               | Type             | Severity    | Applies to                    | One-line summary                                                                                                                            |
| -------------------------------------------------- | ---------------- | ----------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `01-migrate-allowed-markdown-paths-to-additive.md` | config-migration | recommended | sets `allowed_markdown_paths` | Migrate the markdown_organization full override to the additive `extra_allowed_markdown_paths` so upstream defaults are kept automatically. |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
