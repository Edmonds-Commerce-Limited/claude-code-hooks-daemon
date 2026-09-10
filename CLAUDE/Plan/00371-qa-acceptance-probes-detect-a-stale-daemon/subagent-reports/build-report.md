# Plan 00371 — build report

## Summary

The acceptance harness dispatches every probe through the live daemon socket, so it silently graded whatever code the daemon had loaded at startup rather than the working tree — the exact shape of the reported incident (`SelfMatchingProcessProbeHandler` denied for a reason nothing named, because the daemon still held pre-merge code; `bin/hooks-daemon restart` fixed it with no code change).

Fix: a content fingerprint of the code a daemon loaded at startup (its own package directory plus, when enabled, the project's `.claude/project-handlers/`), computed once in `DaemonController.initialise()` and reported over the existing `_system`/`health` socket action. Every acceptance test that dispatches through a live daemon socket now compares that fingerprint against the working tree and fails loudly, by name (`STALE DAEMON: ...`), before any probe-specific assertion can produce a confusing symptom instead. A new `bin/hooks-daemon check-source-fresh` CLI verb reuses the same comparison; `scripts/qa/run_smoke_test.sh` now runs it before its own 3 fixed probes, closing the gap in that script's own header claim to catch "daemon running stale code" (none of its 3 probes covered the handler that actually broke).

Design decision (documented in PLAN.md): detect-and-fail, not auto-restart — QA stays read-only, and the daemon a QA run would restart is very often the same one gating the live agent session running that QA.

## What changed

- `src/claude_code_hooks_daemon/daemon/source_fingerprint.py` (new): `daemon_package_root`, `compute_source_fingerprint`, `compute_daemon_identity_fingerprint`, `compute_current_project_fingerprint` (config-aware, for callers with no live controller), `describe_fingerprint_mismatch`.
- `src/claude_code_hooks_daemon/daemon/controller.py`: computes `self._source_fingerprint` once in `initialise()` (best-effort, fail-open, matching the `_sync_agent_assets` sibling contract), reports it from `get_health()`.
- `src/claude_code_hooks_daemon/utils/repo_relative_path.py`: extracted `resolve_repo_relative_path()` so the fingerprint code and `_load_project_handlers` share one `{REPO_ROOT}`-token resolution instead of two copies.
- `src/claude_code_hooks_daemon/daemon/cli.py`: new `check-source-fresh` subcommand.
- `tests/acceptance/conftest.py`: centralised the `_socket_is_alive`/`_discover_socket` helpers that were independently byte-identical-duplicated across four acceptance files, added `assert_daemon_source_fresh()` once, folded into shared `daemon_running`/`daemon_socket` fixtures (both module-scoped, required by `test_playbook_harness.py`'s own module-scoped `playbook` fixture).
- `tests/acceptance/test_playbook_harness.py`, `test_absolute_path_socket_deny.py`, `test_stop_hook_hard_block.py`, `test_tool_use_error_recovery.py`: removed each file's local duplicate of the above; no other change.
- `tests/acceptance/test_daemon_source_freshness.py` (new): the regression reproduction — proves the mechanism against a REAL daemon-reported fingerprint, not just hand-written strings.
- `scripts/qa/run_smoke_test.sh`: calls `check-source-fresh` before its 3 probes.
- `scripts/qa/error_hiding_exclusions.json`: one new entry for `_compute_startup_source_fingerprint`'s `return-none-on-error` shape (fail-open, logged, matches the `_sync_agent_assets` contract two entries above it in the same file).
- Unit tests: `tests/unit/daemon/test_source_fingerprint.py`, `test_cli_check_source_fresh.py`, plus additions to `test_controller.py` and `test_controller_project_handlers.py`.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/24-a-stale-daemon-can-no-longer-pass-or-fail-qa-silently.md`.

## TDD

Every source file was preceded by a failing test (collection/import error confirmed RED before the source module/function existed), per the mandate.

## Live verification (not just unit tests)

Restarted this worktree's own daemon; `check-source-fresh` reported fresh. Appended a throwaway comment to `controller.py` without restarting; `check-source-fresh` correctly reported `STALE DAEMON` naming both fingerprints, and `test_playbook_harness.py` failed every test in the module with that named reason instead of a probe-specific symptom — the literal incident, reproduced and now caught by name. Same live-fire directly against `run_smoke_test.sh`. Reverted each probe edit, restarted clean, reran all 5 acceptance files green.

## QA

`./scripts/qa/llm_qa.py all` (daemon restarted first): 26/27 stages pass. `tests`: 22115 passed, 0 failed, 0 errored. `smoke_test`: 3/3. The sole failure is `pyright`'s pre-existing 10 whole-repo errors — individually checked against every file this plan touches, none match; they live in `core/result_types.py` and three test files unrelated to this work (likely residue from concurrent plans merged into `main` before this worktree branched). Every file this plan touches is pyright-clean (verified separately, 0 errors/0 warnings).

First full QA attempt found 4 failures (`format`, `pyright`, `tests`, `smoke_test`), all traced to one cause: the `format` stage's `black` auto-fixed two just-written files mid-run, mutating the working tree after the daemon had already been restarted at the start of the run — a live demonstration of the exact class of drift this plan's check exists to catch, firing correctly on itself. Restarting once more against the now-formatted files resolved all four.

## Plan status

All tasks and Success Criteria in `PLAN.md` are checked. `**Status**` is held at "In Progress" rather than "Complete": the plan-qa `terminal-state-atomic`/`location-status-coherence` commit gates require the `git mv` into `Completed/` plus the README row and stats update in the *same* commit, which per the coordinator's own instructions is the coordinator's job on `main`, not this worktree's. The plan is functionally complete and ready to be flipped to Complete and archived in that single atomic commit.

## Notable process finding (not code)

Filing the plan on `main` (before this worktree existed) collided twice with other agents' concurrent commits sharing the same working tree: once my staged plan-filing files were silently swept into another agent's unrelated archival commit (content landed correctly on `main`, just without its own commit message/attribution), and once a `git commit` was blocked by `plan-qa` on another agent's in-flight, uncommitted archival work. Both resolved on their own without intervention; logged in the plan's `JOURNAL/` for anyone filing a plan on `main` concurrently with other agents in the future.
