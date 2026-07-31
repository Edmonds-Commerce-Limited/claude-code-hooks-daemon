# Post-Upgrade Tasks — v3.49.1 → v3.50.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** — populate it with the tasks that ship for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from the source version to this target version. They are advisory only — nothing runs them automatically.

If no post-upgrade tasks apply to this release, delete this directory entirely before publishing the release. An empty `post-upgrade-tasks/` is worse than none — it suggests something is missing.

## Task index

<!-- BEGIN TASK INDEX — populate with the tasks moved in from UNRELEASED/ at release time -->

| File                              | Type            | Severity    | Applies to                                     | One-line summary                                                                                      |
| --------------------------------- | --------------- | ----------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `01-audit-plan-document-sizes.md` | workflow-change | recommended | `≤v3.49.1` (any project using `plan_workflow`) | Measure your plan tree against the new `plan-doc-size` tiers before the block tier applies to an edit |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
