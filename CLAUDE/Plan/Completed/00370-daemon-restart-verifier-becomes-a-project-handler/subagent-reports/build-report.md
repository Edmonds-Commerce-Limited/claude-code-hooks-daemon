# Plan 00370 build report

## Summary

`daemon_restart_verifier` is removed from the built-in handler library and
re-homed as a project-level handler in this repository's own
`.claude/project-handlers/pre_tool_use/`, per the owner's ruling that a
handler whose `matches()` only ever fired inside the hooks-daemon repository
itself should never have shipped in the shared, cross-project library.

## What changed

**New project handler** (Phase 1):

- `.claude/project-handlers/pre_tool_use/daemon_restart_verifier.py` —
  reproduces the built-in's one-line advisory on `git commit` in this
  repository. Replaces the built-in's `is_hooks_daemon_repo` git-remote
  fork (memoised per Plan 00155) with a cheap filesystem check: this
  module's own path, resolved relative to its known location under
  `.claude/project-handlers/pre_tool_use/`, checked against a marker file
  (`src/claude_code_hooks_daemon/version.py`). Priority 24 (not the
  built-in's 10 — every 10-23 slot is already taken by a built-in safety
  handler in this project's real config; verified by
  `tests/integration/test_project_handler_priority_collisions.py`, not
  guessed).
- `.claude/project-handlers/pre_tool_use/test_daemon_restart_verifier.py` —
  written first (TDD). 8 tests covering identity, `matches()` positive and
  negative cases, `handle()` content, `get_claude_md()`, acceptance tests.

**Built-in removal** (Phase 2):

- Deleted `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_restart_verifier.py`
  and its unit test file.
- Removed `HandlerID.DAEMON_RESTART_VERIFIER`, `Priority.DAEMON_RESTART_VERIFIER`,
  the `HandlerKey` Literal entry, and the `handler_profiles.py` strict-only
  list entry.
- Added `"daemon_restart_verifier"` to `RETIRED_HANDLERS`
  (`constants/handlers.py`) with a reason — this is the existing Plan 00233
  mechanism that lets a client's leftover config key validate silently
  instead of putting the daemon into degraded mode. Covered by two new
  regression tests in `tests/unit/config/test_handler_name_validation.py`.
- Removed the shipped config key from `.claude/hooks-daemon.yaml`,
  `.claude/hooks-daemon.yaml.example`, and the scaffold text in
  `daemon/init_config.py`.
- Updated every doc mention (`docs/guides/HANDLER_REFERENCE.md` — two
  places, `CLAUDE/LLM-INSTALL.md` — two places, `CLAUDE/Performance/BASELINE.md`,
  `README.md`) and the two comments in `daemon/validation.py` that named the
  handler as the hot per-event caller of `is_hooks_daemon_repo` (that
  caller is now gone; the sole remaining caller is `daemon/cli.py`'s
  one-shot install-time check).
- Regenerated `.claude/HOOKS-DAEMON.md` and the `CLAUDE.md` `<hooksdaemon>`
  block via `bin/hooks-daemon regenerate-docs`.
- Updated four test files that named the removed class in per-handler
  exemption/rationale maps (none of them actually exercised the class):
  `test_blocking_handler_evasion.py`, `test_claude_md_guidance_coverage.py`,
  `test_doc_truth_check.py`, `test_validation.py`.

**A real bug found and fixed along the way**: `scripts/qa/check_repo_hygiene.py`'s
`orphaned-handler-guidance` rule already looked for project-handler modules
(added when the other three project handlers were built), but matched only
by exact module **stem** (snake_case filename). Every project handler until
now shipped `get_claude_md() -> None`, so nothing had ever exercised the
case where a project handler's `handler_id` (kebab-case, matching the
built-in display-name convention — the spelling the CLAUDE.md injector
actually writes as the marker) differs from its filename (snake_case,
Python convention). The new handler is the first case. Fixed
`_known_handler_identities` to also register the hyphenated form of each
project-handler module stem, with a regression test in
`tests/integration/test_repo_hygiene_check.py`
(`test_a_project_handler_with_a_kebab_case_id_is_not_an_orphan`, written
first, confirmed RED, then GREEN after the fix).

**Upgrade path + release notes** (Phase 3):

- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml` — this worktree
  branched from `main` before Plans 00367/00368 landed this file there, so
  it did not exist yet in this checkout; written fresh with only a
  `removed:` entry for `handlers.pre_tool_use.daemon_restart_verifier`,
  `breaking: false`. That value follows the v3.53.0 precedent (sixteen
  handlers removed in one release, `breaking` stayed false, because
  `RETIRED_HANDLERS` makes a leftover key a silent accept rather than a
  validation error) rather than the v2.11.0/v3.58.0 precedent (`breaking: true`)
  — confirmed against the historical manifests and the validator's actual
  behaviour before deciding, not assumed. No versioned upgrade guide under
  `CLAUDE/UPGRADES/v3/` for the same reason: Step 9 of `RELEASING.md`
  requires one only when the CHANGELOG entry is flagged breaking. Written
  purely additively so it merges cleanly with whatever the other two
  in-flight plans land in their own copies of the same file.
- Release-notes callout 22 (`CLAUDE/UPGRADES/UNRELEASED/release-notes/`)
  `git mv`'d from `22-optimise-no-longer-asks-a-client-for-the-dogfood-handler.md`
  to `22-daemon-restart-verifier-becomes-a-project-handler.md` and rewritten
  to describe the removal and re-home, keeping `**Plan**: 00370` and the
  file number.
- A dogfooding pointer added to `CLAUDE/PROJECT_HANDLERS.md`'s Overview
  section, naming this repository's `.claude/project-handlers/` (now four
  handlers) as the reference example — chosen over `CLAUDE/SELF_INSTALL.md`
  because a reader already in the project-handlers guide, building their
  first one, is the one served by "see this repo's own examples".

## QA

`./scripts/qa/llm_qa.py all` — first run: 24/26 tools passed. `format`
flagged one file, but black auto-fixes by default in this pipeline and the
fix was already applied (`black --check` confirmed unchanged afterward).
`tests` showed 2 failures in `tests/integration/test_daemon_smoke.py`
(`test_daemon_processes_session_start_hook`,
`test_daemon_handles_invalid_hook_input`) — neither test references this
handler, project handlers, or handler counts at all; they spin up a
throwaway daemon subprocess and assert the hook response is a dict.
Investigated rather than dismissed: ran the file alone (10/10 passed), ran
the full test suite standalone via `run_tests.sh` (21731 passed, 0
failed), then reran the full `llm_qa.py all` pipeline a second time (26/26,
21731 passed, 0 failed). The two failures did not reproduce twice, which
is the basis for calling them transient resource contention under the full
pipeline's concurrent tool load rather than a regression, not a single
lucky rerun.

`bin/hooks-daemon test-project-handlers --verbose`: 97/97 passed
(includes the pre-existing `enforce_llm_qa`, `plan_done_requires_holding_area`,
`release_blocker` suites plus the 8 new tests).

Worktree daemon restarted, confirmed RUNNING. The delivery commit
(`4c5bb582`) was made FROM the worktree, and its own PreToolUse hook
printed `💡 RECOMMENDED: Verify daemon restart before committing` — the
live advisory from the new PROJECT handler, verifying the plan's primary
success criterion with the actual commit that delivers it, not a separate
probe.

## Plan status

`PLAN.md` is fully ticked (all tasks, all Success Criteria) but `**Status**`
was deliberately left at `In Progress`, not flipped to `Complete`. This
repository's plan workflow (`CLAUDE/core/PlanWorkflow.core.md`) requires a
terminal-status flip to move the plan folder into `Completed/` and update
the README row/statistics in the SAME commit; the daemon's own `plan-qa --check-staged` gate enforces this and blocked the first attempt at
committing with `**Status**: Complete` while the folder stayed under the
active root. Per the assigning instructions, that archival step (git mv,
README row, statistics) is reserved for whoever merges this branch back to
`main`, not done from this worktree.

## Commits

- `main` @ `85ed8bd0` — `Plan 00370: filed` (PLAN.md, README index row,
  statistics, JOURNAL scaffold)
- `worktree-plan-00370` @ `4c5bb582` — `Plan 00370: daemon_restart_verifier becomes a project handler` (the implementation: 27 files changed)
- `worktree-plan-00370` @ `ee7d56a6` — `Plan 00370: journal + task tracking for the completed implementation`

Branch pushed: `origin/worktree-plan-00370`.

## Files touched

Project handler (new):

- `.claude/project-handlers/pre_tool_use/daemon_restart_verifier.py`
- `.claude/project-handlers/pre_tool_use/test_daemon_restart_verifier.py`

Built-in removal:

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_restart_verifier.py` (deleted)
- `tests/unit/handlers/pre_tool_use/test_daemon_restart_verifier.py` (deleted)
- `src/claude_code_hooks_daemon/constants/handlers.py`
- `src/claude_code_hooks_daemon/constants/priority.py`
- `src/claude_code_hooks_daemon/install/handler_profiles.py`
- `src/claude_code_hooks_daemon/daemon/init_config.py`
- `src/claude_code_hooks_daemon/daemon/validation.py`
- `.claude/hooks-daemon.yaml`
- `.claude/hooks-daemon.yaml.example`
- `.claude/HOOKS-DAEMON.md` (regenerated)
- `CLAUDE.md` (regenerated `<hooksdaemon>` block)
- `docs/guides/HANDLER_REFERENCE.md`
- `CLAUDE/LLM-INSTALL.md`
- `CLAUDE/Performance/BASELINE.md`
- `README.md`
- `tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py`
- `tests/integration/test_claude_md_guidance_coverage.py`
- `tests/integration/test_doc_truth_check.py`
- `tests/unit/daemon/test_validation.py`
- `tests/unit/config/test_handler_name_validation.py`

Repo-hygiene bug fix:

- `scripts/qa/check_repo_hygiene.py`
- `tests/integration/test_repo_hygiene_check.py`

Upgrade path:

- `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml` (new)
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/22-daemon-restart-verifier-becomes-a-project-handler.md`
  (renamed + rewritten from `22-optimise-no-longer-asks-a-client-for-the-dogfood-handler.md`)
- `CLAUDE/PROJECT_HANDLERS.md`

Plan tracking:

- `CLAUDE/Plan/00370-daemon-restart-verifier-becomes-a-project-handler/PLAN.md`
- `CLAUDE/Plan/00370-daemon-restart-verifier-becomes-a-project-handler/JOURNAL/00370-Journal-26-09-10.md`
