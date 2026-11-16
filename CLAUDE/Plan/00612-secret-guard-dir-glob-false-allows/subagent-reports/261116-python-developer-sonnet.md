# Plan 00612 report: secret guard dir-glob false allows

## Red (tests first)

`tests/unit/handlers/pre_tool_use/test_secret_file_guard_trailing_slash_glob.py`
before any source change: `15 failed, 47 passed`.

- POSIX classes: five index-level `directories_matching` cases, the file-glob
  case (`dir/[[:alpha:]]*` returned None), the mixed-members case, and four
  handler cases (`grep -r x [[:alpha:]]*/` etc. returned ALLOW) plus a file
  glob (`cat dir/[[:alpha:]]*`).
- Symlinks: `directories_matching("l*/")` returned `()`, the hidden-symlink
  case returned `()`, and `grep -r x l*/` returned ALLOW. The literal
  `grep -r x l/` already denied (via `find_under`, which adds `realpath(root)`
  to its bases), so the glob path was the only gap.

One of my own handler assertions (`./l?/`, a two-character name) was wrong and
was corrected to `./?/`.

## Fix

`src/claude_code_hooks_daemon/utils/protected_file_index.py`

1. `fnmatch` replaced in the shared `_segments_match` by `_component_pattern`,
   an `lru_cache`d translator to a regex: `*`, `?`, backslash escapes,
   bracket expressions with `!`/`^` negation, a leading literal `]`, ranges,
   and POSIX classes expanded to explicit ASCII character sets (C locale).
   An unclosed `[` is a literal; a bracket holding only reversed ranges
   matches nothing (negated: any character). Runs of `*` collapse, every
   other token consumes one character, so there is no catastrophic
   backtracking. File globs (`glob_matches`) and directory globs share it.
2. `directories_matching` additionally calls
   `_matching_symlinked_directories`: when every component before the last is
   literal, it runs one `os.scandir` of that parent, keeps symlinks whose name
   matches the last component (same matcher, so dot rules apply), and returns
   those whose `realpath` is a directory containing an indexed protected file.
   The caller then runs `find_under` on the link path, which already follows
   `realpath` as for a literal `l/`.

Why scandir of the literal parent and not more: it is one directory level, so
cost does not depend on tree size (the earlier walk cost 9-28 s per call).
Limit, stated in the release note: a symlink matched only below a wildcard
directory (`*/l*/`) is not judged. Expanding wildcard parents would need a
walk or an unbounded fan-out, so I left it; this remains a false allow for
that shape.

## Green

Both touched test files plus `tests/unit/utils/test_protected_file_index.py`:
`148 passed`. A wider run of `tests/unit/utils` (`-k "protected or secret or recursive or glob"`) gave `1586 passed` before the test correction above; the
existing `[^x]`/`[!x]` tests still pass.

## Also

Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/088-secret-guard-dir-glob-false-allows.md`.
Out of scope items (`**/` base directory, bash older than 5.2, Plan 00611)
untouched.
