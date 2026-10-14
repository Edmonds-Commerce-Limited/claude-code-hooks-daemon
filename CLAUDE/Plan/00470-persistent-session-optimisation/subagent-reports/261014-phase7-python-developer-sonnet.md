# Plan 00470 Phase 7 (Tasks 7.1 and 7.2): report

## What was built

- `utils/workable_issues.py`: the cache (`workable-issues.json` in the daemon's untracked dir: numbers plus timestamp), `workable_numbers()` (eligible and not labelled `agent-needs-human`), `refresh_workable_cache()`, tolerant `read_workable()`, atomic `write_workable()`.
- `ValidityReport` gained a `labels` field, filled from the facts the single `gh issue list` call already returns, so there is no per-issue call.
- Task 7.2: `work-queue done NAME` closes, then makes one `gh issue list` call, refreshes the cache and prints `next workable issue: #N - start it now`, `no workable issue`, or `next issue is unknown: <why>`. A gh, config or write failure never fails the close and leaves the cache untouched. `issue-validity --list-eligible` writes the same cache from its own single listing.
- Task 7.1: new Stop handler `idle_workable_issue_stop_gate` (rule `R-STOP-IDLE-WITH-WORKABLE-ISSUE`, priority 4, non-terminal, MAIN scope, on by default, inert unless `issue-sdlc` is a declared job for this host and thread). Options: `job_id`, `max_cache_age_hours` (2), `marker_expiry_hours` (24). It reads local files only (a test forbids subprocesses).
- Registered in constants, `stop/__init__`, `init_config`, `.claude/hooks-daemon.yaml` and `.example`; regenerated `.claude/HOOKS-DAEMON.md`; band row updated in HANDLER_DEVELOPMENT.md, CONFIGURATION.md and CONTRIBUTING.md; release note 060; PLAN.md Tasks 7.1 and 7.2 ticked (nothing else touched).

## Stands aside (allow)

Sub-agent stop (MAIN scope); usage pause (`hook_is_usage_paused`); non-holder thread (Task 6.4 mixin); job not declared or not for this host; any `running` queue entry; unreadable queue; missing, stale, future-dated or empty cache; a valid awaiting-human marker for the session; the stop itself declaring `[awaiting-human]` (read from the transcript, because `auto_continue_stop` writes the marker AFTER this handler runs and the stop would otherwise be refused one step too early); `stop_hook_active` re-entry (the facts are those the first deny already named, so one deny per chain, as every other one-shot Stop block does).

## Deviations from the brief (reasons)

1. "Tree is clean" (PLAN.md Task 7.1 text) is not checked: a Stop hook that shells out to git is slow and the brief did not list it. Work in flight is the queue's `running` status.
2. The "usage-ceiling margin" in the PLAN text is not implemented beyond the live usage pause; Plan 00479's numbers would need a margin definition that does not exist yet. Worth an owner ruling if wanted.
3. Re-entry allows unconditionally rather than "re-entry that also carries the same blocker": the hook cannot read a blocker from the model's words, and the established convention is one deny per chain. The deny text does tell the model to stop again naming the blocker, but that second stop is not judged.
4. "Workable" follows the brief (eligible and not `agent-needs-human`). It does not model IssueSdlc Step 1's `agent-working` and not stalled exclusion, so an issue another session is working could be named. The deny is one-shot, so the cost is one wasted nudge; encoding stall detection in a cache is a separate decision.
5. Printed text uses `-` not an em dash, to stay safe on non-UTF-8 stdout.

## TDD evidence

Red output captured before implementation: `tests/unit/utils/test_workable_issues.py` collection error `ModuleNotFoundError: No module named 'claude_code_hooks_daemon.utils.workable_issues'`; `test_issue_validity_cli.py` `28 failed, 4 passed` (`TypeError: run_issue_validity() got an unexpected keyword argument 'workable_cache'`); `test_work_queue_cli.py` failed on `AttributeError` (no `_issue_service`). The handler test file was written before the handler but its red run was not captured separately (the import would have failed); it went `32 passed` on the first green run.

## QA

`./scripts/qa/llm_qa.py changed --allow-unmapped` (13 files reported too-broad unmapped, as the brief allows): `QA: 39/40 PASSED, 1/40 FAILED`, exit status 1. The single failure is `tests/acceptance/test_playbook_harness.py::...test_every_executable_probe_matches_its_expected_decision_and_reason`, probe `#116 WorktreeFileCopyHandler`, which is denied by `R-WRITE-OUTSIDE-PROJECT-ROOT` instead of the expected worktree-copy reason. It concerns a PreToolUse worktree handler and the location of this worktree; it is unrelated to this change, but I did not prove it fails on an untouched tree. Earlier runs in this session also fixed: pyright (test subclass instead of attribute assignment), error_hiding (`log_and_continue` plus three exclusion entries in `scripts/qa/error_hiding_exclusions.json`, matching `read_marker`'s precedent), generated_doc_drift (regenerated), quote-drift (CONTRIBUTING.md), and four integration tests (guidance verdict, scope list, release-note audience, priority band row).

Daemon restarted in the worktree; status RUNNING, 31/31 listeners. The restart made the daemon auto-commit the CLAUDE.md handler marker (`3f9693db3`), which sits under this work.
