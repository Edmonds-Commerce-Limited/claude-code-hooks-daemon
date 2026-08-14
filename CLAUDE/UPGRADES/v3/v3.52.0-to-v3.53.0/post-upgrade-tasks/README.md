# Post-Upgrade Tasks — v3.52.0 → v3.53.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** for the v3.52.0 → v3.53.0 upgrade.
>
> **Read `04` first.** It is the only `recommended` task here and it is a security one: every runtime file your daemon has already written is group- and world-writable, and upgrading does not fix them.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from the source version to this target version. They are advisory only — nothing runs them automatically.

If no post-upgrade tasks apply to this release, delete this directory entirely before publishing the release. An empty `post-upgrade-tasks/` is worse than none — it suggests something is missing.

## Task index

<!-- BEGIN TASK INDEX — populate with the tasks moved in from UNRELEASED/ at release time -->

| File                                      | Type         | Severity    | Applies to                                  | One-line summary                                                                                                                   |
| ----------------------------------------- | ------------ | ----------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `02-review-daemon-owned-file-banners.md`  | notification | optional    | all                                         | Expect a large comment-only diff in committed daemon-owned files — every one now opens with a DAEMON-OWNED banner.                 |
| `03-plan-dedupe-scout-agent.md`           | notification | optional    | projects with `plan_workflow.enabled: true` | A new `hooks-daemon-plan-dedupe-scout` agent is deployed into `.claude/agents/`; commit it, and try it once before trusting it.    |
| `04-audit-world-writable-daemon-files.md` | audit        | recommended | every project whose daemon has ever run     | Every file your daemon created before this release is world-writable. Run `hooks-daemon check-permissions` and `--fix` to tighten. |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
