# N241 / N200: git_stash and destructive_git judge command position

Branch `worktree-n241-stash`.

## What changed

- New `src/claude_code_hooks_daemon/utils/command_position.py`:
  `command_position_view` and `command_position_segments`. On top of the existing
  `strip_inert_spans` it blanks the arguments of data heads (`echo`, `printf`,
  `grep`, `egrep`, `fgrep`, `rg`) unless the segment carries an expansion or its
  pipeline feeds an executor (`bash`, `sh`, `xargs`, `eval`, `env`, `sudo`...), the
  title/body/notes values of `gh pr|issue|release`, and it reads a literal
  `bash -c '<body>'` body as commands of its own (recursively, depth 3).
  Segments split on `&&`, `||`, `|`, `&`, `;` and newline, quote-aware.
- `destructive_git._scan_target` uses the view.
- `git_stash.matches` judges each segment on its own (N200); the escape hatch still
  reads the raw command.
- `shell_segmentation._MESSAGE_BODY_PATTERN`: a single-quoted value ends at the next
  quote (backslash is literal in single quotes), which un-hides
  `git commit -m 'x\' ; git reset --hard ; echo 'y'`.
- Acceptance tests of both handlers embed the command in `bash -c '...'` instead of
  `echo "..."`, since `echo` is now prose.

## Tests that pinned the old over-wide behaviour (changed, with reason)

- `test_git_stash.py::test_matches_git_stash_in_echo_quotes` became
  `test_does_not_match_git_stash_in_echo_quotes` plus a `bash -c` positive;
  `test_blocks_all_creation_variants` swapped its two `echo` rows for `bash -c`.
- `test_destructive_git.py::test_matches_comment_mentioning_git_returns_false` now
  asserts False (it asserted True and said so as "acceptable").
- `test_handlers_do_not_match_prose.py`: `GitStashHandler` exemption removed, and the
  `DestructiveGitHandler` exemption too (its stated reason, acceptance tests embedding
  in a string, no longer holds); the teeth test uses `bash -c`; six N241 prose rows
  added to `_NON_EXECUTING_TEXT`.

Plan 00228 Decision 2 is superseded by the threat-model ruling for these two handlers.
`SedBlockerHandler` and the others keep their exemptions.

## Red / green

New tests `test_git_guards_command_position.py`: 19 failed on main (all N241 prose
rows, the N200 rows, the `x\'` row, the nested `bash -c` message). After the fix all
pass; the new util tests (`test_command_position.py`) pass.

## Not changed

No handling for variables, `eval` of a variable or ANSI-C quoting (out of scope per
the ruling). `bash -c` with an expanding double-quoted body is left as written.
