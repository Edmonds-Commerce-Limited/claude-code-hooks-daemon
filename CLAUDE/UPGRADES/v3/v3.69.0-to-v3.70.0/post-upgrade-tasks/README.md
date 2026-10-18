# Post-Upgrade Tasks — v3.69.0 → v3.70.0

> Convention and schema live in `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/README.md`. This file is the **per-release index** — populate it with the tasks that ship for this specific upgrade.

## About this directory

Task files here are **instructions for an LLM/human to follow after upgrading** from the source version to this target version. They are advisory only — nothing runs them automatically.

## Task index

<!-- BEGIN TASK INDEX — populate with the tasks moved in from UNRELEASED/ at release time -->

| File                                                 | Type            | Severity    | Applies to | One-line summary                                                                                                            |
| ---------------------------------------------------- | --------------- | ----------- | ---------- | --------------------------------------------------------------------------------------------------------------------------- |
| `01-clear-unproven-venvs.md`                         | other           | recommended | all        | List venvs with `list-venvs`, investigate each UNPROVEN one, remove it with `prune-venvs --unproven` once confirmed safe.   |
| `02-commit-the-expected-version-and-provision-sh.md` | workflow-change | recommended | all        | Commit `daemon.expected_version` and `.claude/provision.sh`, so a fresh clone provisions and a pulled upgrade syncs itself. |
| `03-tune-the-plan-fact-checker.md`                   | workflow-change | optional    | all        | Copy the generic fact-checker to a project-owned tuned agent, record its derived-from version, set `tuned_agent`.           |

<!-- END TASK INDEX -->

## How an upgrading LLM should read this directory

1. Read this index first; skip any tasks whose **Applies to** does not cover the project's prior version.
2. For each remaining task, open its `.md`, follow the detection guidance, then act on the handling guidance.
3. Report a summary back to the user grouped by severity. `critical` tasks should block the user's next step until acknowledged; `recommended` and `optional` tasks can be reported without blocking.
