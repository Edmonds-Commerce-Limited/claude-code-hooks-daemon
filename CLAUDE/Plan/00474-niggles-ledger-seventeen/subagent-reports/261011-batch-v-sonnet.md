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

## Round 2 (review: FIX FIRST)

The review found that `_starts_comment` trusts any `#` after a comment preceder, so with the new mode an escaped
word-break (`grep -rn issue\ #42 docs/ && git reset --hard`) or a `#` after a closed substitution swallowed the real
command, and six guards flipped from deny to allow.

Fix, all inside `split_unquoted_spans` and only in `comments_end_at_newline` mode (default mode untouched):

- `escaped_end` records where the last backslash escape ended; a `#` there continues a word (covers `\ #`, `\;#`,
  `\|#`, `\&#`, `\(#`, `\>#`, backslash-tab and backslash-newline).
- New `_Nesting` tracker: unquoted/double-quoted `$(`, `<(`, `>(`, `${`, and backtick bodies. A `#` is a swallowing
  comment only at depth zero, and not directly after a closer (`$(x)#`, `${x}#`, a closing backtick).
- Bias: openers always count and closers count only when unquoted, so a miscount keeps nesting (keeps splitting, the old
  behaviour). A doubtful `#` splits exactly as on main.

Tests: `TestDoubtfulHashIsNeverAComment` runs 16 doubtful prefixes x 6 real commands x 2 separators through
destructive_git, sudo_pip, pip_break_system, gh_issue_comments, github_auto_close_keywords and git_stash `matches()`,
plus per-guard deny, split-position and "real comment after a closed substitution still swallows" checks.

Probes (`/workspace/untracked/scratch/review-batch-v/`): `probe.py` output on this branch is byte-identical to the
reviewer's `main.json` (no row weaker than main, 0 diff). `probe2.py` and `probe3.py`: every row denies by its intended
guard (the data-head `\ #` rows that allowed in round 1 now deny).

Round 2 results: `tests/unit/utils` + `tests/unit/handlers/pre_tool_use` + corpus gate: 18489 passed, 1 skipped, 0
failed. black, ruff, mypy and pyright clean on the touched source files.

## Round 3

Review finding: a bare `(` counted only when already nested, so `(( 1 #x )); sudo pip install x` and
`(( 1 #x )) || ...` allowed. `_Nesting.observe` now counts every unquoted `(`, so a `#` inside an arithmetic command or
a plain subshell falls back to main's splitting. Test: `test_a_hash_inside_an_arithmetic_or_subshell_group_...` (3 heads
x 3 separators x all six guards, plus sudo_pip and pip_break_system by name).

Probes (all from `/workspace/untracked/scratch/review-batch-v/`, run against this branch and against `/workspace/src`):
`probe.py` byte-identical to `main.json`; `probe2.py` and `probe3.py` identical to main; `probe5.py` `(( 1 #x ))` rows
deny as on main. The only rows weaker than main are text bash really treats as a comment or a syntax error:
`let x=1 #y; ...` (probe5), `echo a\\ #c; ...` (escaped backslash, then a real comment), `echo ...; echo #c; git reset`,
`grep ... # note | sudo pip install x`, and `echo a)#c; ...` (unmatched `)`, a syntax error that never runs).
Round 3 results: 18498 passed, 1 skipped, 0 failed; black, ruff, mypy, pyright clean.

## Ledger

NIGGLES.md N407: both comment-splitting residual lines marked "cleared by batch V". The unrelated `git grep` quoted
pattern residual stays open and is now its own line.
