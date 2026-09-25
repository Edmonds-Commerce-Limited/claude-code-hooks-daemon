# Pre-Upgrade Tasks — Convention

This directory holds **changes a project must hear about BEFORE the next release is deployed into it**: a renamed CLI key its tooling parses, a removed command its scripts call, a config shape the new version refuses. A post-upgrade task arrives after the damage; a pre-upgrade task arrives while nothing has been deployed and the upgrade can still stop.

Pre- and post-upgrade tasks share **one schema and one loader** (`src/claude_code_hooks_daemon/install/upgrade_tasks.py`). The schema, the section guidance and the file naming are written down once, in [`../post-upgrade-tasks/README.md`](../post-upgrade-tasks/README.md); this file states only what a pre-upgrade task adds to it.

## What reads these tasks

The upgrade gate (`src/claude_code_hooks_daemon/install/upgrade_gate.py`). Every upgrade runs it (through Layer 1, or with Layer 2 run directly) in `run_pre_deploy_phase` (`scripts/upgrade_version.sh`), once the daemon checkout sits on the target and before anything is deployed into the project. For every guide the upgrade crosses (and this holding area, on a branch install) it runs each task's detection over the project and names the affected lines at `file:line`. A task that detects nothing is not shown, so a project the change does not touch hears nothing.

The gate then stops the upgrade until it is acknowledged. Nothing is deployed, and the daemon checkout goes back to the installed version when that version can be told (the venv stamp, `.claude/HOOKS-DAEMON.md`, or the commit Layer 1 moved from); otherwise, or when the reset fails, the stop prints the command that puts it back. See `CLAUDE/LLM-UPDATE.md` ("The pre-deploy gate") for the stop, the `--skip-reading-confirmation=<digest>` re-run, and the owner's approval that a `critical` task with hits requires.

## The detection contract (what a pre-upgrade task adds)

A pre-upgrade task MUST declare how to find the call sites it affects, in its header block:

```markdown
# Task: [Short human title]

**Type**: audit | config-migration | data-migration | workflow-change | notification | other
**Severity**: critical | recommended | optional
**Applies to**: [which prior versions and projects]
**Idempotent**: yes | no
**Detect**: `python-regex`
**Detect in**: `*.py`, `*.sh`, `.github/workflows/*`
```

- **`**Detect**`** — required. One Python regular expression in backticks (the schema rejects it without them), matched against the first 4096 characters of each line of each file. Keep it narrow: every hit is shown to the upgrading agent, a pattern that matches ordinary prose trains it to skim, and a false hit on a `critical` task costs the owner an approval. `plan-qa[^\n]*--json` is a good pattern; `level` is not. No nested quantifier (`(x+)+`, `(a*)*`, `(a+){2,}`): the schema rejects it, because it can backtrack for ever on one long line.
- **`**Detect in**`** — optional. Backticked `fnmatch` globs over the project-relative POSIX path; `*` crosses `/`, so `*.py` means every Python file. Omitted, every file is scanned.
- In a git work tree the scan reads the files git lists (tracked, plus untracked files `.gitignore` does not exclude). It never enters `.git/`, `node_modules/` or tool caches at any depth, nor the top-level `untracked/`, `venv/`, `.venv/`, `vendor/`, `dist/`, `build/` and `target/`, nor the daemon's own clone (`.claude/hooks-daemon/`), and skips symlinks, binary files and files over 1 MiB. At most 20 hits per task are listed, with a count of the rest.

The body then carries the four sections every task has: `## Why`, `## How to detect if this applies to you`, `## How to handle`, `## How to confirm`. `## How to detect if this applies to you` is still prose: the pattern finds candidates, and the agent decides which of them really are call sites.

## Severity decides who may proceed

- `recommended` / `optional` — the gate lists the task; the upgrading agent may acknowledge it (`--skip-reading-confirmation=<digest>`) and continue.
- `critical` — when its detection finds anything in the project, the change breaks that project on deploy, so the gate **escalates**: the upgrade also needs the owner's one-shot approval, which only the owner can give, in their own terminal. Reserve `critical` for a change that breaks a detected call site outright.

A task that cannot stop anything belongs in `post-upgrade-tasks/`.

## Task index

<!-- BEGIN TASK INDEX — regenerate when adding/removing tasks -->

| File | Type | Severity | Applies to | One-line summary |
| ---- | ---- | -------- | ---------- | ---------------- |

<!-- END TASK INDEX -->

## When the release happens

The `/release` skill moves every task file in this directory into the versioned upgrade guide (e.g. `CLAUDE/UPGRADES/v3/v3.2-to-v3.3/pre-upgrade-tasks/`), regenerates that guide's task index, and leaves this directory empty apart from this README. `tests/integration/test_upgrade_task_schema.py` checks every task here and in every released guide against the schema; `tests/integration/test_post_upgrade_tasks_are_reachable.py` checks that the gate reaches each one.
