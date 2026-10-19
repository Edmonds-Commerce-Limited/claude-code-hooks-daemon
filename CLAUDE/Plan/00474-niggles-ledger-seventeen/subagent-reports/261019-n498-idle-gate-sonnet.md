# N498 report: idle-stop gate in-flight sources

Branch `worktree-n498-idle-gate-inflight`.

## Change

- `utils/stop_hook_helpers.py`: new `reported_background_tasks` (absent or malformed gives `[]`) and `has_running_background_task` (an entry with `status == "running"`).
- `handlers/stop/teammate_reap_advisor.py`: `_background_task_count` now reads through `reported_background_tasks`, so the two handlers share one reading rather than a copy.
- `handlers/stop/idle_workable_issue_stop_gate.py`: a running background task, or a present `release-state.json` in the state directory, allows the stop, as does the existing work queue check. Deny text, rule `verbose`, `get_claude_md` and the first acceptance test now name all three sources.
- Ledger 00474: N498 marked fixed in NIGGLES.md and STATUS-INDEX.md; open count 35 to 34 in PLAN.md.

## Disagreement with the brief (evidence)

The brief says to reuse the release_in_progress handler's constant. That handler is the project handler `.claude/project-handlers/stop/release_blocker.py` (`RELEASE_STATE_PARTS = ("untracked", "release-state.json")`); nothing under `src/` defines it and the package cannot import from `.claude/`. So `RELEASE_STATE_FILENAME` is declared in the gate with a comment naming that source. The gate reads it from `daemon_untracked_dir()` (the same directory it reads the queue and cache from), which is the project's `untracked/` directory.

## TDD red

Tests were written first (`TestOtherInFlightSources`, plus a guidance test). First run:

`ImportError: cannot import name 'RELEASE_STATE_FILENAME' from 'claude_code_hooks_daemon.handlers.stop.idle_workable_issue_stop_gate'`

Green after implementation: 57 passed (gate and teammate_reap_advisor unit tests).

## QA

`./scripts/qa/llm_qa.py changed`: 37 of 40 passed; `format` failed (2 files, the tree changed during the run); the two NOT MEANINGFUL rows (`project_handlers`, `changed_tests`) were so only because of `format`, and both reported 0 failed (238 and 2619 passed). `run_autofix.sh` was then run and `black --check` on the four files is clean. A re-run of the full `changed` was not repeated.
