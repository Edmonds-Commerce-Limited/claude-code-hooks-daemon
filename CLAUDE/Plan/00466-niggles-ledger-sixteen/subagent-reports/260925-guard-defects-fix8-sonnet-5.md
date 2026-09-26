# Plan 00466: guard-defects fix round after review 8 (Sonnet 5)

Worktree: `worktree-n466-guard-defects`. Started at `ff071be8d`. Review 8
report (`260925-guard-defects-review8-opus-5-5.md`) committed as-is first
(`d7faa511c`).

## Scope done

All six in-scope items, one commit each, TDD (RED proven against a
`git archive` copy of the pre-fix code for every item, never `git stash`):

1. **MAJOR-A** (`c63c276f0`) — the grep exemption's `-f`/`--file` handling
   treated their VALUE as search-pattern content; GNU grep 3.8's own
   `--help` shows only `-f`/`--file`/`--exclude-from` read a file. Rewrote
   the option walk (proper short-cluster classification matching GNU
   getopt, `-f`/`--file`/`--exclude-from` values routed into the same
   file-target check every other positional word gets, non-file value
   options like `-A`/`-B`/`-C` properly consumed).
2. **MAJOR-B** (`d8da4686f`) — `_decode_span`'s two backtick branches used
   a plain `text.find("`", i+1)`, which finds an ESCAPED inner backtick first and cuts the outer body short. Added `\_close_backtick\`, which
   skips backslash-escaped characters and un-escapes the body per bash's
   own backtick rules before the recursive re-parse.
3. **MAJOR-C** (`c5ab4b82e`) — the interpreter one-liner option walk
   stopped at the first word not starting with `-`, so a value-taking
   option's own separate-word value (`python3 -W ignore -c ...`) ended the
   walk before the real code flag. Added a per-family `value_flags` table
   (verified against each interpreter's real getopt behaviour, not just
   `--help` text) and a `"value"` classification checked first; an
   unrecognised word no longer breaks the walk (keeps walking instead), so
   it never silently stops and allows.
4. **L1** (`56ee338c6`) — threaded `_evaluate`'s deadline through
   `is_grep_pattern_only_mention`, `is_exempt_invocation` (via
   `_paths_only_in_flag_position` and `find_protected_mention`) and
   `is_encrypted_target_invocation`. RED proven deterministically
   (`deadline=monotonic()-1` must raise `TimeoutError`), not via a clock.
5. **L9** (`7770ebe20`) — renamed
   `test_one_megabyte_bash_command_completes_well_under_a_second` to
   `test_ordinary_vocabulary_bash_command_scan_cost_scales_linearly` (the
   class asserts a cost RATIO now, not a wall-clock budget).
6. **L7** (`31773b756`) — `black --target-version py311` (the gate's own
   target) applied to all 7 touched files; fixed two pre-existing mypy
   errors in touched test files (`os.ScandirIterator` -> `Iterator[os. DirEntry[str]]`; `guard_module.sfm`/`guard_module.RuleFormatter`
   attribute access on non-re-exported names -> import `sfm`/
   `RuleFormatter` directly and patch those references, same underlying
   module/class objects).

## Verification per item

Targeted pytest + ruff + mypy + pyright + black (`--target-version py311 --check`) run on every touched file after each item; all clean. Full
targeted suite at the end (`test_secret_file_guard.py`,
`test_review7_false_positive_corpus.py`, `test_secret_file_matching.py`,
`test_shell_expansion.py`): **873 passed**. Daemon restarted before every
`src/` commit, verified RUNNING. No gate queued (fixer role).

## Left for the coordinator

Review 8's L2-L6 and L8 (not in this brief's scope). New commits since
review 8's `ff071be8d` baseline: `c63c276f0` .. `31773b756` (6 commits).
