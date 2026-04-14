# Post-Upgrade Tasks — v3.2 → v3.3

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** for the v3.2 → v3.3 upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from v3.2.x to v3.3.0. They are advisory only — nothing runs them automatically.

## Task index

| File                               | Type  | Severity    | Applies to       | One-line summary                                                                                      |
| ---------------------------------- | ----- | ----------- | ---------------- | ----------------------------------------------------------------------------------------------------- |
| `01-audit-markdown-frontmatter.md` | audit | recommended | `v3.0.0..v3.2.1` | Scan for `.md` files whose YAML frontmatter was mangled by the pre-v3.3.0 `markdown_table_formatter`. |

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
