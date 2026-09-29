# Plan 00463 fix round 10b + merge main

**Branch**: `worktree-plan-463-full-qa-gate`
**Merge SHA**: `d7827f2db714c13550533d4b381097030ec7ccab`
**Fix commit**: `3a989aeee`

## Task 1: `--noconftest` no longer drops the sink

`-p claude_code_hooks_daemon.qa.full_qa_gate` added to `pyproject.toml`'s
`addopts`, so the sink plugin loads even when `--noconftest` removes the
conftest-import route. `full_qa_gate.py`'s `_gate_anchor` now handles the
resulting double registration (both the forced `-p` route and a project's own
conftest import active at once): the conftest-registered anchor wins over the
sink module's own (test-file-less) directory, which previously produced a
false "unable to judge" refusal on every run once `-p` was added.

RED-proven against a `git archive` baseline copy before the fix (both new
test classes failed as expected), GREEN after
(`TestNoconftestNoLongerDropsTheSink`, `TestDoubleRegistrationIsANoOp` in
`tests/unit/qa/test_full_qa_gate.py`).

## Task 2: unrecognised interpreters running inline code are UNSEEN

`find_full_qa_invocation` now judges any program it does not otherwise
recognise (not python, a shell, a launcher, a project runner, or a declared
full-QA command) by SHAPE: run with one of the inline-code flags shared
across scripting interpreters (`-e`, `-E`, `-c`, `-r`, `--eval`), it is UNSEEN
(judged by `unseen_policy`, advisory by default) instead of a silent,
contextless `None`. `git` is exempted (`-c` there is a config override, not
inline code) — the one collision this small flag set creates with a program
this file already recognises elsewhere; that is a program-specific carve-out,
not a widened interpreter name list.

RED-proven for `perl -e`, `perl -E`, `node -e`, `ruby -e`, `php -r` and an
unnamed future interpreter with `--eval`
(`TestUnrecognisedInterpreterRunningInlineCode` in
`tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`); the
positive-deny corpus and the everyday-allow corpus (including `git status`
and `git -c core.pager=cat log`, both still fully unmatched) stayed green —
948 tests passed in that file, up from 938.

PLAN.md's "Second referral" removed and the "Owner referral (Round 10)" text
updated to record `--noconftest` as closed; a new "Round 10 M1 (fix round
10b)" section records both fixes.

## Task 3: merge main + gate

Merged `main` (`d025fbdc9`) into the branch. Ten conflicts, all resolved by
keeping both sides' intent (not picking one side):

- `.claude/HOOKS-DAEMON.md`, `CLAUDE.md`: auto-generated, took `main`'s copy
  (daemon restart regenerates on the next real change anyway).
- `src/claude_code_hooks_daemon/handlers/registry.py` +
  `src/claude_code_hooks_daemon/daemon/cli.py`: HEAD had added
  `apply_handler_config` (priority+scope+options, one call, used by
  `hooks-daemon check`'s full-QA-blocker probe, which needs scope); main had
  split this into `apply_handler_options` (options only, used by `register_all`
  and the other three `check` probes) plus a new `build_handler_config_mapping`
  (Plan 00466 N15/N17, already relied on elsewhere in `cli.py`). Kept all
  three: `apply_handler_config` now delegates to `apply_handler_options`
  internally. Caught and fixed a dropped `NpmCommandHandler` import in this
  resolution via the targeted test run (`test_cli_enforcement_status.py`).
- `scripts/qa/audit_error_hiding.py` + its test file: HEAD added
  generator-yield-awareness to `return-none-on-error`
  (`_names_the_failure`/`_is_empty_iterable`); main added an entirely
  separate `return-none-via-local` check (00466 N29). Kept both; the shared
  `visit`/`_check_function` call site now runs the yielded-tracking guard
  AND `self._check_fallback_returned_through_a_local(node)`.
- `tests/unit/handlers/test_registry_option_injection.py` +
  `tests/unit/qa/test_audit_error_hiding.py`: both sides added disjoint new
  test classes at the same location; concatenated.
- `docs/guides/HANDLER_REFERENCE.md`: main's table (newer wording,
  `plan_status_snapshot` row) plus HEAD's `subagent_full_qa_blocker` row,
  which main's copy was missing entirely (pre-existing doc gap, not touched
  further).
- `CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`: ledger table, kept
  every row at its most advanced status — main's table was a near-superset
  with more advanced statuses everywhere except N2, where HEAD's own
  "✅ Remedied by Plan 00463" is correct (this branch delivers it).
- `.../JOURNAL/00466-Journal-26-09-24.md`: reordered main's earlier
  (20:21) entries before HEAD's later (20:48) one; the re-append note about
  N2 itself was re-appended a further time via `mkplan.bash --journal`
  (`plan_journal_guard` refuses a hand-placed heading), landing in today's
  day-file instead.

Merging main's new `return-none-via-local` audit rule surfaced 3 real
findings in `subagent_full_qa_blocker.py` (`_resolved_code_path`,
`_symlink_declared_name`, `_path_substitution`) — pre-existing code in a
file this round touches, so fixed rather than left: each `except` handler's
`logger.debug` raised to `logger.warning`, which the audit's own
`_handler_surfaces_the_error` treats as "not hiding" (warning-or-above).

Targeted tests (both round-10b files, both merge-conflicted test files, the
daemon CLI enforcement-status suite): 3664 passed, 1 skipped (root-conditioned,
pre-existing). ruff, mypy, pyright, black all clean on every touched file.
Daemon restarted twice (post-fix, post-merge) and verified RUNNING both times.

Gate queued in the background: `bash /workspace/untracked/scratch/gate.sh worktree-plan-463-full-qa-gate` (not waited on).
