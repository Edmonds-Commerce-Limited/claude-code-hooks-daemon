# Plan 00610 report: trailing-slash glob in the secret guard

## Findings

- The brief was right. `glob_matches` normalised `*/` to `*` and matched it against protected files at the root.
- None of the three callers in `secret_file_matching.py` touch the slash. The fix therefore lives in the index and in the recursive-search expander.
- A literal directory is judged two ways. A non-recursive command (`ls -d dir/`) is ALLOWED. A recursive reader (`grep -r x dir/`) is judged by `ProtectedFileIndex.find_under` through `recursive_search`.
- Before the fix, `grep -r x */` was allowed even with a protected file at `dir/` (a false negative). `recursive_search` drops any root holding a glob character.

## Change

- `src/claude_code_hooks_daemon/utils/protected_file_index.py`: `glob_matches` returns None for a token ending in `/`. Such a glob names directories only, so it never matches a file at its own level.
- `src/claude_code_hooks_daemon/utils/recursive_search.py`: new `_expand_directory_glob`. A search root that ends in `/` and holds `*`, `?` or `[` is expanded with `glob.glob` to the directories it names. `_reads_of_roots` then reads each one, so `find_under` judges them as it does a literal directory. A root with `$`, a backtick or `{` is left unplaceable, as before. Git grep pathspecs are untouched.
- Tests: `tests/unit/handlers/pre_tool_use/test_secret_file_guard_trailing_slash_glob.py` (12 tests: index level, `search_reads`, and handler verdicts).
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/084-secret-guard-trailing-slash-glob.md`.

## Red (before the fix)

`9 failed, 2 passed`. Examples:

- `ls -d */`, `ls -d ./*/` and `echo */` were DENIED where ALLOW was expected, with only a root-level protected file.
- `grep -r x */` was ALLOWED where DENY was expected, with a protected file under `dir/`.
- The `*/` index-level tests returned a match where None was expected.

## Green (after the fix)

- New file: `12 passed`.
- Together with `test_protected_file_index.py`, `test_recursive_search.py` and `test_secret_file_guard_glob_operands.py`, the earlier 231 existing tests passed. The only failures were two of my own tests, which built the index through `index_for`. I switched them to a directly built `ProtectedFileIndex`.

## QA

See the final reply for the `llm_qa.py changed` verdict.
