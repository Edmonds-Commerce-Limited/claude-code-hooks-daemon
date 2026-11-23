# Fact check: NIGGLES.md diff (N595/N698/N700/N701 recurrences, N695-N701)

The diff edits `CLAUDE/Plan/00474-niggles-ledger-seventeen/NIGGLES.md`, not PLAN.md.
Paths below are relative to `src/claude_code_hooks_daemon/` unless they start with `tests/`.

## REFUTED or mis-cited

1. N595 recurrence: "`lint_on_edit` gates only on it (`lint_on_edit.py:258`, `:318`)". The file is `handlers/post_tool_use/lint_on_edit.py`. Line 258 is there. Line 318 is in `handlers/pre_tool_use/staged_lint_gate.py`, not in lint_on_edit. The behaviour claim holds; the attribution of `:318` is wrong.
2. N701: "`find_protected_mention_detail` with `context="content"` (`:1864`)". In `secret_file_guard.py` the `context="content"` argument is at line 1882, not 1864. The script-extension list starts at 325, and `".go"` is at 335, which is consistent with the plan.
3. N697: "`bash_safe_mode.py:65-68`" for `_DEFAULT_ONLY_WITH_MUTATOR`. The constant is at line 69. The gate at `:342` is correct.
4. N698: "`_search_reach`, `secret_file_guard.py:1753-1758`". The glob_unjudged advisory is at 1753-1755. Lines 1756-1758 are a separate no-index advisory. This is a minor drift.

## VERIFIED

- N595: `strategies/lint/go_strategy.py:85-86` returns `COMMON_SKIP_PATHS` alone, and no `testdata` appears in that file.
- N595: `strategies/tdd/go_strategy.py:20` has `_SKIP_DIRECTORIES = ("vendor/", "testdata/")`.
- N595: `tests/unit/strategies/lint/test_go_strategy.py:32-33` only asserts that `skip_paths` is a tuple.
- N595/N601: `### N601 — staged_lint_gate type-checks Go files under testdata/` exists at NIGGLES.md:7248, and `staged_lint_gate.py:318` uses `strategy.skip_paths`.
- N695: `plan_number_helper.py` has `matches` at 504, the `find` regex at 628, the `mkdir` branch that resolves against `_workspace_root` at 305-306, and `_workspace_root` at 146. No `cwd` appears in `tests/unit/handlers/pre_tool_use/test_plan_number_helper*.py`.
- N697: `only_with_mutator: true` is set at `.claude/hooks-daemon.yaml:616`.
- N698: `secret_file_guard.py:1668-1672` matches the claim.
- N698: `has_name_agnostic_glob` is at `utils/secret_file_matching.py:3519`.
- N698: `_overflow_mention` is at `utils/secret_file_matching.py:4992`.
- N698: `tests/unit/utils/test_secret_file_matching_default_globs.py` pins `ls **` as the plan describes. Lines 66-81 allow it. Lines 105-132 keep the denial for the globstar-on, dotglob-on, no-snapshot and unreadable-snapshot cases.
- N698: `test_secret_file_guard_glob_operands.py:83` holds the `ls */*` and `ls **/*` cases, and the file cites N220.
- N700: `strategies/error_hiding/go_strategy.py:24-28` holds `_BLANK_LAST_FROM_CALL`. Its leading `(?:_\s*,\s*)*` admits `_, x, _ :=`. `tests/unit/handlers/pre_tool_use/test_error_hiding_blocker_go.py:61` pins `a, b, _ := f()`.
- N701: `utils/resolution_failure.py` has `ProcessViewRefusedError` at 44, `_PLAIN_PROCESS_FILES` at 74 and `refuse_process_view` at 110. `tests/unit/utils/test_resolution_failure.py:74` lists `/proc/self/exe`. `secret_file_guard.py` has the `ResolutionFailedError` catch at 1440 and `_unresolved_finding` at 1502.
- N701: the guard also denied my own Bash commands that carried the literal, which matches the plan's remark.

## UNVERIFIED

- N696: the plan itself marks the cause as unconfirmed. The reported deny cannot be reproduced here.
- N698: `test_secret_file_guard_cwd_fail_closed.py:357` (`cat *` allowed from a clean cwd). Only lines 338-347 were seen.
- N698: `secret_file_matching.py:3506-3515` was not read.
- N701: that `exe` is absent from `_PLAIN_PROCESS_FILES` was not read directly. The test at line 74 implies it.
- N699: `sed_blocker.py` was not read. The exemption list in the plan matches the CLAUDE.md description.
