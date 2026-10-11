# Batch V (Sonnet): N407 comment-splitting residual

## Defect

`command_position._segment_spans` used the shared `split_unquoted_spans`, which deliberately keeps splitting at
`|`, `;`, `&&`, `&` inside a `# comment`. So `ls # note | sudo pip install x` and
`true # export PIP_BREAK_SYSTEM_PACKAGES=1 && pip install x` produced a second "command" from comment text, and the pip
guards denied.

## Fix

- `utils/shell_segmentation.py`: `split_unquoted_spans` gains a keyword-only `comments_end_at_newline: bool = False`.
  When true, inside a comment only a newline separates. The default is unchanged, so every other caller
  (curl_pipe_shell, root_recursion_guard, sed_blocker, secret_file_matching, recursive_search, the internal users) is
  byte-identical.
- `utils/command_position.py`: `_segment_spans` passes `True`. That one function feeds `segment_spans`,
  `command_position_view`, `command_position_segments`, `command_position_code_segments`,
  `command_position_code_segments_with_separators`, `command_position_argument_segments`, and so every caller listed
  below.
- Comment detection is the existing `_starts_comment` (`#` at word start, unquoted; so `$#`, `${#x}`, `a#b`, `'#'` and
  `\#` are not comments). A newline ends the comment and starts a new command.

## Callers of the changed splitter (all tests run)

dangerous_permissions, curl_pipe_shell (view), git_stash, destructive_git, ancestry_preserving_merge,
github_auto_close_keywords (`segment_spans`), plan_number_helper, worktree_file_copy, pip_break_system, sudo_pip,
`utils/gh_view_comments`.

Behaviour change for the guards that judge comment text (git_stash, destructive_git, worktree_file_copy and others):
comment text on a line is now one segment with its command, instead of several. A real command can only precede the
`#`, so a real command is never lost; text after the `#` on the same line is no longer judged as a command.

## Tests

- New `tests/unit/utils/test_command_position_comment_splitting.py` (operators in a comment do not split for each of
  `| ; && || &`; newline ends the comment; `echo '#' && sudo pip install x`, `$#`, `${#x}`, `a#b`, `\#` still deny;
  quoted and unquoted heredoc bodies; shared splitter unchanged by default).
- Parity: for every corpus row with no `#`, `segment_spans` equals the comment-blind shared splitter (over 100 rows).
  For every row with a `#`, each new boundary is an old boundary (the new splitter only removes splits).
- `test_command_position_comments.py`: one old test asserted the fixed behaviour (`true # note; sudo pip install x`
  yielding a `sudo` segment); it now puts the real command on the next line.
- Corpus rows `n407-comment-pipe-then-sudo-pip`, `-andand-then-export-pip`, `-semicolon-then-break-flag`,
  `-line-then-next-line-comment`.

## Results

- `tests/unit/utils` + all of `tests/unit/handlers/pre_tool_use` + the corpus gate
  (`tests/integration/test_ordinary_command_regression_gate.py`): 18263 passed, 1 skipped (pre-existing permissions
  skip), 0 failed.
- black, ruff, mypy: clean on the four touched Python files. pyright: 0 errors on the two source files; on the new test
  file it only reports `pytest` unresolved because the worktree has no `untracked/lsp-venv` (environmental, same for any
  test file).
- Full suite not run, per instruction.

## Ledger

NIGGLES.md N407: both comment-splitting residual lines marked "cleared by batch V". The unrelated `git grep` quoted
pattern residual stays open and is now its own line.
