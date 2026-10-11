# Plan 00483 Task 3.2: FP batch 2

Branch: worktree-p483-fp-batch2 (not merged).

## Fixes

1. Brace reader. `_parameter_end` in `utils/shell_expansion.py` now reads the word of
   `${name:-word}`, `=`, `+`, `?` (and the `:` forms) through `_default_word_end`: backslash,
   `'...'` (literal inside double quotes), `"..."`, nested `${}`, `$()` and backticks. Covered:
   `x=${P:-"/usr"}`, `${X:-'a'}`, `"${X:-"/a b"}"`, `"${X:+"$Y"}"`. `_double_quote_end` now
   passes `in_double=True` to a nested `${`.
2. FP-A. `core/utils.py` gains public `is_device_path` (the test `_resolve_write_target` already
   used); `project_containment._resolve_targets` skips a device path on the curl/wget/etc.
   destination route.
3. FP-B (in-scope part). `core/utils.py` gains `substitute_cwd_expansions`: `$PWD`, `${PWD}`,
   `$(pwd)` read as the hook cwd, `$(git rev-parse --show-toplevel)` as the nearest enclosing
   directory holding `.git`. Applied on both write-target routes (the shared
   `scan_bash_write_targets` and project_containment's destination route) before known-variable
   substitution; the resolved path is judged normally. Not applied when the command contains
   `cd`/`pushd`/`popd`/`PWD=`, when cwd is not absolute, or when no repository encloses cwd.

## Tests

RED first: 5 quoted-default cases, 4 null-device cases, 6 cwd-expansion cases failed before the
fix. Existing fixtures that used `${x:-'a'}` / `"${x:-"a"}"` as the "unresolvable" prefix
(test_shell_expansion.py, test_secret_file_guard.py N113 group) were switched to the still
unreadable `${x#'a'}` so they keep testing fail-closed. New: unit file
`tests/unit/core/test_utils_cwd_expansions.py`.

Results: 4546 passed over secret_file_guard (+text_fed_heredoc), project_containment,
shell_expansion, shell_segmentation (4 files), do_not_match_prose, blocking_handler_evasion and
tests/unit/core. One failure, `test_the_polluter_and_a_victim_pass_together_in_one_process`: its
subprocess pytest lacks `-o pythonpath=src` and aborts in the source-tree guard (imports
/workspace/src); an environment effect of the targeted invocation, not of this change.
ruff, black --check (py311), mypy on the three touched src files: clean.
`check_dangerous_invocation_corpus.py`: every recorded verdict holds (29 rows).

## Still denies (tested)

- `curl -o /tmp/x`, `wget -O /tmp/x`, `curl -o /devious/x`
- `echo x > "$PWD/../../outside"`, `"$(pwd)/../../outside"`,
  `"$(git rev-parse --show-toplevel)/../outside"`, `curl -o "$PWD/../../outside"`
- `cd /tmp && echo x > "$PWD/x"`, `PWD=/tmp; ... "$PWD/x"`, `"$PWDX/x"`, `"$TMPDIR/x"`,
  `"$(git rev-parse --git-dir)/x"`, toplevel with no enclosing repo
- Unreadable brace shapes (R-SECRET-COMMAND-UNREADABLE): `${x#'a'}`, `${x:-'a}` (unterminated),
  `${x:-{a}` (bare brace in word), each followed by a real quoted brace group.
