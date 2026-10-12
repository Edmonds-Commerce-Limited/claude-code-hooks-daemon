# N432 (issue #83): conflict-marker gate scopes its git grep to the recorded paths

Branch: worktree-issue-83-scoped-grep. Agent: python-developer (sonnet). I agree with the coordinator's ruling and implemented it as written.

## Change

`src/claude_code_hooks_daemon/handlers/pre_tool_use/conflict_marker_commit_gate.py`:

- `_findings` sorts `recorded` once into `paths` and passes it to `_marker_sizes` and to `_candidate_lines`.
- `_candidate_lines` and `_grep` take `paths`. `_grep` runs `git --literal-pathspecs grep ... -e <prefilter> -- <chunk>` for each chunk of `_ATTR_CHUNK` (256) paths, concatenates the stdout of the chunks, and keeps exit 1 as "no match" per chunk. Non-zero other exits and timeouts raise through `_raise_unreadable` as before.
- `--literal-pathspecs` is the same global option `_added_line_numbers` already uses. The paths come from `--name-only` or `ls-files --full-name` (repository-relative) and `_grep` runs at the repository root, so they resolve from there.
- The `path not in recorded` filter in the loop is gone: the grep can no longer return an unrecorded path. The exclusion test, protected-path withholding, `-I` then `--text -l` binary / `-diff` handling and added-line filtering are untouched.
- Empty `recorded` still returns early. `_ATTR_CHUNK`'s comment now says it serves `git grep` too. The module docstring's Cost paragraph is rewritten to match.
- The timeout, the fail-closed rule and N430 are untouched.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/036-the-conflict-marker-gate-scans-only-what-the-commit-records.md`.

## Tests (class `TestTheGrepIsScopedToTheRecordedPaths`)

RED on the unchanged source (4 failed, 5 passed):

- `test_both_passes_carry_only_the_recorded_paths`: `AssertionError: assert '--literal-pathspecs' in ('grep', '--cached', '-I', '-n', '-z', '--full-name', ...)`
- `test_a_glob_named_file_does_not_widen_the_scan`: `ValueError: tuple.index(x): x not in tuple` (no `--` pathspec at all)
- `test_a_list_longer_than_one_chunk_is_scanned_to_its_end`: `assert 2 == 6` (two whole-tree greps, no chunks)
- A fourth failure was a test-setup error (`git add ':(top)x.txt'` is read as pathspec magic by git add itself); I dropped that parameter, so a leading-`:` name is not covered by a test.

Also in the class: an unrecorded file holding a marker never denies; names `a[1].txt`, `*.md`, `q?.txt` are found when they hold a marker; a `-diff` attributed file in a later chunk is still read whole.

GREEN: the whole file, 168 tests, passes. black, ruff and mypy are clean on both touched files. `llm_qa.py changed`: 37/40 passed. The one finding is the plan_qa advisory `journal-freshness` for plan 00495 (unrelated; its journal is 6 days quiet), and 2 detectors are listed as not meaningful because of it.

## Not measured

I did not reproduce the 5,800-file timing; scoping is shown by the argv spy test, not by a benchmark.
