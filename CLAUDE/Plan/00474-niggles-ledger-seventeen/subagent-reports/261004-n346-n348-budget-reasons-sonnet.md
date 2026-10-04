# N346 and N348: budget-exhausted denies get their own rule and reason

Branch `worktree-n346-capmsg`, based on main 0bde607c4.

## What changed

- `run_git` (`src/claude_code_hooks_daemon/utils/git_repo.py`) reports `subprocess.TimeoutExpired` as `GIT_TIMED_OUT` (124), distinct from an absent git (127). The timeout value is unchanged.
- `conflict_marker_commit_gate`: a git timeout in `git grep`, `diff`, `check-attr`, `cat-file` or `ls-files` raises `_GitTimedOut` and is denied as new rule `R-CONFLICT-MARKER-SCAN-TIMED-OUT`. The reason names the 5 s limit, says no marker was found and the content needs no edit, and says to retry. Other git failures and real findings keep `R-CONFLICT-MARKER-COMMIT`.
- `secret_file_guard`: `TooManyToEnumerateError` and `TimeoutError` now take a new route and rule, `R-SECRET-SCAN-INCOMPLETE`, instead of the `read` rule with a placeholder glob. The reason states what ran out (the cap of examined paths, carried by a new `limit` on `TooManyToEnumerateError`; or the 5 s scan deadline), that no protected path was found, and the remedy (narrow the glob or search root, name the files, or retry after a deadline). The exception text is never echoed. Real findings keep `R-SECRET-BASH-MENTION` and `R-SECRET-READ`.
- Rule IDs are declared in `constants/rule_ids.py` and surfaced through each handler's `get_rules()` and `get_claude_md()`, the way the existing rules are. The generated CLAUDE.md table is rebuilt on daemon restart, which was not done.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/015-budget-exhausted-denies-have-their-own-reason.md`.

## Findings that bound the scope

- `utils/recursive_search.py` has no deny past its cap. `directory_contains_protected` answers `None` past `DIRECTORY_SCAN_MAX_ENTRIES` (a documented residual limit), so there was no "mentions a protected path" deny to relabel there. Left as is; making it fail closed would be a behaviour change outside this task.
- Sibling commit gates checked for a fixed timeout that maps to a deny: `sensitive_content` staged-diff reads and `staged_lint_gate` stand down (allow) on a timeout; `docs_qa_commit_gate`, `plan_qa_commit_gate` and `remote_docs_commit_gate` deny with `SimulationIncompleteError`'s own message ("could not be simulated completely"), which is already distinct from a finding. None changed.
- N348 stays Open for the pattern-versus-glob redesign. N346 is marked fixed.

## Tests

- `tests/unit/handlers/pre_tool_use/test_conflict_marker_commit_gate.py::TestATimedOutScanIsNotAFinding`: `subprocess.run` patched to raise `TimeoutExpired` for `grep`, `diff` and `check-attr`; reason content; a real finding and a non-timeout git failure keep the old rule ID.
- `tests/unit/utils/test_git_repo.py`: a timeout is told apart from an absent git.
- `tests/unit/handlers/pre_tool_use/test_secret_file_guard_glob_operands.py::TestAScanThatRanOutOfBudgetIsNotAFinding`: synthetic tree over a patched cap of 2, a patched deadline, a cap with no stated limit, no exception text echoed, a real finding keeps its rule, the rule is declared.
- Existing tests that pinned the old shape (`test_secret_file_guard.py` rule count and ids, deadline reason; the hostile-input performance test) were updated to the new rule.
- The red phase was shown by the new symbols not existing (`GIT_TIMED_OUT`, `RuleID.SECRET_SCAN_INCOMPLETE`), not by a separate failing run.
