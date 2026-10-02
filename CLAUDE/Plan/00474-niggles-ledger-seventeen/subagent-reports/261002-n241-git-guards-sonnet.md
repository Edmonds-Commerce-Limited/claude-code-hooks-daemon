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

## Round 2 (Opus review fixes M1-M4, S1-S3)

Red first: the new rows in `test_git_guards_command_position.py` gave
`34 failed, 70 passed` on the round 1 code (22 receiver rows, 10 redirect rows,
2 `rg --pre` rows). After the fix the file and `test_command_position.py` gave
`124 passed`; the wider targeted set (touched tests, destructive_git, git_stash,
prose, `test_shell_segmentation*`) gave `1459 passed`.

- **M1**: `_EXECUTORS` is deleted. A data head is blanked only when every
  downstream `|` stage satisfies `is_inert_pipeline_stage`, a new public
  wrapper in `shell_segmentation.py` over the existing `_stage_is_inert_sink`
  (no second list; fds assumed able to reach a process). Fish, busybox, su,
  `(bash)`, at, parallel, ssh, docker/kubectl exec and `tee >(bash)` deny on
  both handlers; `| wc -l`, `| tee log`, `| sort` stay allowed.
- **M2**: `command_position._segment_spans` masks the `&` of `>&`, `<&`, `&>`,
  `&>>` (same length) before splitting. `2>&1 | bash` denies; `git status 2>&1`
  allowed; `a & b` still splits.
- **M3**: every `bash -c` acceptance command in both handlers is now
  `bash -n -c '...'`. Verified in-process that both guards still deny every
  DENY row in that form (all 12 destructive_git rows, both git_stash rows; the
  tag `-f` ALLOW row does not match). The `[[ ... $(git push --force) ... ]]`
  row also executed its substitution for real, so it is now
  `bash -n -c 'git commit -m "$(git push --force)"'` (still denied). False
  safety notes ("guard denies it before it executes", "only clears stash")
  replaced. GENERATING.md Layer 1, its example and the `command` field are
  updated. A new unit test asserts every wrapped acceptance command is `bash -n -c`.
- **M4**: the teeth test now uses `SedBlockerHandler` on an `echo "sed -i ..."`
  input; the SedBlocker exemption reason is restated in its own words.
- **S1**: an `rg` segment with `--pre`/`--pre=` (or an unreadable word) is not
  a data head. **S2**: `_head` strips a trailing `)`. **S3**: HANDLER_REFERENCE.md
  wording updated.

## Not changed

No handling for variables, `eval` of a variable or ANSI-C quoting (out of scope per
the ruling). `bash -c` with an expanding double-quoted body is left as written.
