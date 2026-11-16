# Plan 00610 report: trailing-slash glob in the secret guard

## Findings

- The brief was right. `glob_matches` normalised `*/` to `*` and matched it against protected files at the root.
- None of the three callers in `secret_file_matching.py` touch the slash.
- A literal directory is judged two ways. A non-recursive command (`ls -d dir/`) is ALLOWED. A recursive reader (`grep -r x dir/`) is judged by `ProtectedFileIndex.find_under` through `recursive_search`.
- Before this work `grep -r x */` was allowed even with a protected file below a matching directory (a false allow), because `recursive_search` drops any root with a glob character.

## Final design (after the Opus review)

The first attempt expanded the glob on the live filesystem (`glob.glob`, then pathlib). The review found it unbounded (`**/` 9 s, `/**/` 28 s) and a second glob engine. It is removed. There is no filesystem walk now.

- `protected_file_index.py`
  - `glob_matches` returns None for a token ending in `/`: such a glob names directories only, never a file at its own level.
  - New `ProtectedFileIndex.directories_matching(token, bases, *, default_expansion)`. It matches the glob's components against each indexed file's ANCESTOR-directory prefixes (never the file itself), with the existing `_segments_match`. Dot names and `**` follow the existing `default_expansion` rule through shared helpers `_absolute_tokens` and `_glob_parts`, which `glob_matches` now uses too.
  - `_segments_match` reads a leading `[^` in a bracket class as `[!`, as bash does (fnmatch took it literally, a false allow for `[^x]*/`).
- `recursive_search.py`
  - A search root ending in `/` with `*`, `?` or `[` becomes one `Read(glob=True)` carrying its absolute pattern and the tool's rules. `search_reads` sets `default_expansion` once from `default_glob_semantics(command)`.
  - `protected_reached` turns a glob read into one `Read` per directory from `directories_matching`, then calls `find_under` as for a literal directory (view, skip and ignore handling unchanged).
  - `_place` takes an `unplaceable` pattern so a glob root can be placed; a root with `$`, a backtick or `{` stays unplaced.
- Not covered: a symlinked directory is indexed under its real path, so `grep -r x l*/` through a link is not matched (the review's caveat; same as before the change).
- An unmatched glob root yields no directory, as bash hands the literal to the tool and as main did.

## Tests

`tests/unit/handlers/pre_tool_use/test_secret_file_guard_trailing_slash_glob.py` (index level, `search_reads`, handler verdicts). The weak test that passed on main was replaced by one built on a root-level file. New: dot directories (`.*/`, `.h*/`, `*/`), `**/` with and without `default_expansion`, `[^x]`, `[!x]`, `[a-e]`, `?`, absolute `ROOT/*/`, `./*/`, `rg`, and `cd docs && grep -r x ../*/`.

Red (before the rework, against the pathlib version): `19 failed, 20 passed`. Examples: `AttributeError: 'ProtectedFileIndex' object has no attribute 'directories_matching'`, `grep -r x [^d]*/` wrongly denied, `grep -r x [^x]*/` wrongly allowed.

Green: `909 passed` over the new file, `test_recursive_search.py`, `test_protected_file_index.py`, `test_secret_file_guard_glob_operands.py` and `test_secret_file_guard.py`.

## QA

See the final reply for the `llm_qa.py changed --allow-unmapped` verdict.
