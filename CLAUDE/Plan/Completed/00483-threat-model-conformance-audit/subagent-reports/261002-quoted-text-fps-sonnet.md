# Quoted-text false positives: N36, N49, N58, N60, N65, N97, N298

Branch `worktree-quoted-text-fps`. Tests: `tests/unit/handlers/pre_tool_use/test_quoted_text_false_positives.py`
(71 rows: each false positive must allow, each real shape must still match).

## Red, then green

First run, before any source change: 18 failed, 53 passed. Every real-shape row passed; only
false-positive rows failed.

| Entry     | Handler               | Red (false positives that denied) | Fix                                                                                                     |
| --------- | --------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------------- |
| N36       | destructive_git       | 0 of 4. Already fixed on main     | N241's `command_position_view`. Tests added only.                                                       |
| N58       | dangerous_permissions | 4 of 6                            | Pattern run per command segment of the command-position view (`command_position_segments`).             |
| N60, N97  | curl_pipe_shell       | 4 of 4                            | `_scannable` returns the command-position view (after the heredoc stage, which keeps its rules).        |
| N49       | daemon_location_guard | 3 of 3                            | New `is_plain_data_command` in `utils/command_position.py`; `matches` returns False for it.             |
| N65, N298 | plan_number_helper    | 7 of 8                            | `ls`/`find`/`grep` rules read the view; the `ls` glob rule runs per command (`_ls_globs_plan_folders`). |

After the fix the 71-row file is green, and so are `test_dangerous_permissions.py`, `test_curl_pipe_shell.py`,
`test_daemon_location_guard.py`, `test_plan_number_helper*.py`, `tests/unit/utils/test_command_position.py` (48),
`test_blocking_handler_evasion.py`, and all of `tests/unit/handlers/pre_tool_use` and `tests/unit/utils`.

## Decisions a reviewer should look at

- `daemon_location_guard` does NOT use the blanket data-head blanking. Its test matrix
  (`tests/support/inert_head_shapes.py`) pins about 60 shapes that must keep matching: a rebound `echo`, a wrapper
  before the head (`env echo`), fd redirects, globs. Most are out of scope under the threat model, but the ruling
  says code that catches them is kept while it causes no in-scope false positive. So the guard gets a stricter
  predicate, `is_plain_data_command`: one bare `echo`/`printf`/`grep`/`rg`, plain quoted or unquoted words, at most a
  `>`/`>>` to a plain path. Remaining false positive (cheap): `printf '...' >> f && echo done` is still judged.
- `curl_pipe_shell` applies the view only where the heredoc stage has not already withheld the exemption. The view
  alone lost `(cat <<'X' ... X) | bash`, which that handler's own pipe-into-interpreter check catches.
- `test_curl_pipe_shell.py::test_matches_echo_mentioning_pattern_returns_false` asserted True with the comment
  "better safe than sorry". It is exactly N60/N97, so it now asserts False.
- The acceptance tests of `curl_pipe_shell` and `dangerous_permissions` used `echo "<dangerous text>"` and expected a
  deny. That is the false positive. They now pipe the echo into `bash` (`... | bash`), which the guards still deny. If
  a guard failed, the text would run against a `.invalid` host or a nonexistent `/tmp` file.
- The `plan_number_helper` `ls` rule is now: a glob that starts `*`, `0*` or `[0-9]` denies, unless it carries two or
  more literal digits (a specific plan, `*464*`) or is followed by a path (`*/PLAN.md`), and the command does not also
  keep only the last entry (`tail -1`). `echo`/`printf` glob rule and the sort+tail rule still read the quote-blanked
  text, now with quoted heredoc bodies removed first.
- No corpus row changed: `scripts/qa/check_dangerous_invocation_corpus.py` passes unchanged.

## Static checks

ruff, black `--target-version py311`, mypy on the five touched sources, `run_pyright_check.py --json`
(0 errors), `audit_error_hiding.py`, `check_dangerous_invocation_corpus.py`: all clean.

## Unrelated failure on main

`tests/integration/test_handlers_do_not_match_prose.py` has 2 failures
(`a literal inside a quoted heredoc`, `a quoted heredoc body naming git stash`): `BashSafeModeHandler` denies the
probe because it has no `set` prelude. They fail identically in `/workspace` on main, so they are not from this
branch.

## Ledger

N36, N49, N58, N60, N65, N97 marked Fixed (branch, not yet merged) in `TRIAGE-ledger-466.md`; N298 in
`00474-niggles-ledger-seventeen/NIGGLES.md`.
