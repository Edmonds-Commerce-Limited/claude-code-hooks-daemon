# Code Review: Plan 00610, trailing-slash glob in secret_file_guard

Reviewed `git diff origin/main...HEAD` at 3415cd1ee (commits 5ddf49624 and 3415cd1ee).
Changed: `protected_file_index.py` (+6), `recursive_search.py` (+37), one new test file (128 lines), and a release note.

## Summary

The index change is correct and fixes #204: `ls -d */`, `ls */`, `echo */` and `ls -d ROOT/*/` are now allowed when only a root-level protected file exists. The recursive-search expansion closes a real false allow that existed before this branch. On main, `grep -r x */`, `d*/`, `*/*/`, `**/`, `ROOT/*/`, `di?/`, `[!x]*/`, `.h*/`, `l*/` (symlink) and `rg x */` were all allowed with a protected file below. All of them are now denied.

The probe found no regression: no verdict went from deny on main to allow on this branch, except the intended allows. The new code still has problems:

- It walks the live filesystem at hook time, unbounded and outside the scan deadline.
- It reimplements shell-glob semantics that the index already has, and gets one of them wrong.
- The dot-name filter added in the second commit has no test.

Targeted tests at HEAD: the new file plus `test_recursive_search.py`, `test_protected_file_index.py` and `test_secret_file_guard_glob_operands.py` gave 233 passed.

## Important Issues

### 1. Unbounded live-filesystem walk in the hook path (Confidence: 90%)

**Location:** `src/claude_code_hooks_daemon/utils/recursive_search.py:550-552`, called from `_reads_of_roots` at :566. The guard reaches it from `secret_file_guard.py:1545`, where `search_reads(command, cwd)` is called with no deadline.

**Problem:** `_expand_directory_glob` calls `Path.glob` against the real filesystem on every Bash call whose search root ends in a glob plus `/`. When the pattern contains `**`, the walk is fully recursive (first commit: `glob.glob(recursive=True)`; HEAD: pathlib `**`). That walk follows `**` as globstar, but bash's default (globstar off) reads `**` as `*`. Nothing caps the number of entries, and nothing checks `SCAN_DEADLINE_SECONDS` (5.0 s, `secret_file_matching.py:1503`). `TooManyToEnumerateError` is never raised, so the guard's existing fail-closed or advisory path for a cap or deadline (`secret_file_guard.py:1350-1353`) is never reached.

**Evidence** (`untracked/scratch/rv610_perf.py`, run against HEAD):
- `grep -r x */` with cwd `/workspace`: 14 reads, 0.00 s.
- `grep -r x **/` with cwd `/workspace`: 24,331 reads, 9.05 s (glob.glob version: 33,498 reads, 16.96 s).
- `grep -r x /**/`: 48,764 reads, 28.44 s in this small container. On the first commit it was killed by `timeout 100`. On a real host it is the whole filesystem.

Each of those reads is then passed to `find_under`, which loops over every indexed file. The cost is therefore reads x index size on top of the walk.

**Why it matters:** One ordinary-looking command stalls the PreToolUse hook for every handler, far past the guard's own 5 s budget. An absolute `**` stalls it indefinitely. Earlier work bounded shell expansion (brace caps, deadlines) for exactly this reason. This code reintroduces an unbounded path next to it.

**Suggested fix:** Either drop the filesystem expansion (issue 2), or bound it:
1. Treat `**` as `*` (bash default; the same rule as `glob_matches(default_expansion=True)`).
2. Cap the matches and raise `TooManyToEnumerateError` past the cap.
3. Pass the guard's deadline into `search_reads` and check it while iterating.

Add a test that `**/` with a cap of N raises or returns a fail-closed result rather than walking.

Note for the coordinator: there is no `bounded_recursive_glob` in `shell_expansion.py` or anywhere under `src/`, on this branch or on main. `git grep -n bounded_recursive_glob -- src` returns nothing. The bounded machinery that does exist is the brace caps (`DEFAULT_MAX_BRACE_*`), `TooManyToEnumerateError` (`shell_expansion.py:47`), and the `deadline` parameter of `iter_normalised_shell_words`. The new code uses none of them.

### 2. A filesystem expansion was not needed: the index can answer this, and it duplicates glob semantics (Confidence: 80%)

**Location:** `recursive_search.py:112-113` and `:532-562`, compared with `protected_file_index.py` `glob_matches` and `_segments_match`.

**Problem:** The index already matches shell-glob components against every indexed protected path. That matching follows shell rules: `*` stays inside one component, there is no leading-dot match, and `default_expansion` reads `**` as `*`.

A trailing-slash glob read by a recursive tool is equivalent to the following: some indexed file has an ancestor directory whose components match the glob's components. The match is on a prefix of the file's components, excluding the file name itself. The matched ancestors can then be passed as `Read` roots, so `find_under` still applies `view`, `skip` and ignore handling. The cost is bounded by the index size, with no I/O.

The branch instead adds a second glob engine in another module:
- `_EXPANSION_ROOT` and `_DIRECTORY_GLOB` partition the character set of `_UNPLACEABLE_ROOT`. These are three regexes that must stay in sync.
- `expanduser` and cwd joining are copied from `_place` (:510-519).
- The dot-name rule, re-derived in 3415cd1ee, already exists in `_segments_match`.

The two engines already disagree on `**`: the index reads it as `*` with no dot names, while the walker recurses and includes dot names.

**Caveat:** Index-only matching misses a symlinked directory. `link -> real/` is indexed as `real/...`, and `grep -r x l*/` follows the command-line symlink. That one case justifies a single-level `os.scandir` of symlink entries only. It does not justify a recursive walk.

**Suggested fix:** Add `ProtectedFileIndex.directories_matching(glob_token, bases)`, which returns the matched ancestor directories by reusing `_segments_match` on component prefixes. Use it in `_reads_of_roots` for trailing-slash roots. Keep at most a bounded, non-recursive symlink probe. Delete `_EXPANSION_ROOT`, `_DIRECTORY_GLOB` and the pathlib walk.

### 3. `[^...]` bracket negation is read literally: a false allow (Confidence: 90%)

**Location:** `recursive_search.py:550`. Both `glob.glob` and `Path.glob` use `fnmatch`, which treats `[^x]` as a class containing `^` and `x`.

**Problem:** Bash reads `[^x]` as negation, the same as `[!x]`. Verified: `bash -c 'echo [^x]*/'` in a directory holding `xa/` and `yb/` prints `yb/`. With `dir/key.<protected>`, the probe gives:
- `grep -r x [!x]*/`: DENY
- `grep -r x [^x]*/`: ALLOW (wrong)

This is not a regression (main also allows it), but this branch is now the code path that claims to expand these globs.

**Suggested fix:** Before matching, rewrite a leading `^` inside a bracket to `!`. Alternatively, `_segments_match` and the index route from issue 2 should handle both forms. Add a `[^x]*/` deny test.

### 4. Tests: untested branches, and one test that passes without the fix (Confidence: 85%)

**Location:** `tests/unit/handlers/pre_tool_use/test_secret_file_guard_trailing_slash_glob.py`

- With the new tests run against main's `src/` (copied to `untracked/scratch/test_rv610_baseline.py`), 9 fail and 3 pass. Two of the passes are legitimate controls: the literal `dir/` deny at :111, and `ls -d d*/` at :124. The third, `test_a_trailing_slash_glob_names_directories_only_so_matches_no_file` (:90), passes on main because its index holds only `dir/key...`, which normalised `*` never matched anyway. It tests nothing about the fix. Rebuild it on an index that holds a root-level file, so that it fails on main.
- 3415cd1ee added the dot-name filter (`:551-561`, `zip(..., strict=True)`) and the `**` branch with no test at all. Reverting either one leaves the suite green.
- The following are not covered at handler level:
  - `?` and `[` shapes;
  - an absolute `ROOT/*/`;
  - deep `*/*/` and `a/*/`;
  - dot directories (`.h*/` denied, `*/` not reaching `.hidden`);
  - a symlinked directory (`l*/`);
  - `cd sub && grep -r x ../*/`;
  - `**/`.

  All are correct at HEAD per the probe, but nothing pins them.

**Suggested fix:** Add a parametrised deny table and an allow table taken from the probe output (`untracked/scratch/rv610-probe-head.txt`). Each case must fail on main or on a revert of 3415cd1ee.

## Suggestions

- Pre-existing and out of scope, but worth a plan: whole-tree readers are not recursive searches, so `tar cf - dir/`, `zip -r o.zip dir/`, `cp -r dir/ x` and `ls -R dir/` are allowed for a literal directory that holds a protected file. Before this branch, the glob forms of these were sometimes denied, but only by accident (the top-level match). They are now consistently allowed, which matches the plan's "agree with the literal" goal but leaves the gap visible.
- `recursive_search.py:566`: `_expand_directory_glob` returns `[]` for an unmatched glob, so the root silently disappears. This matches bash (the unmatched literal gives grep an error) and main (which dropped it as unplaceable), so it is acceptable. A one-line comment would stop a reader mistaking it for a fail-open.

## Positive Observations

- The `glob_matches` change is minimal, correct and well documented, and it fixes the reported false deny.
- The recursive half closes a broad pre-existing false allow, with no new false allow found across 60 probe commands (dot dirs, symlinks, absolute paths, `cd`, `*/*/`, `**/`).
- The handler-level tests do discriminate: 9 of 12 fail on main.

## Verdict

[ ] APPROVE
[x] REQUEST CHANGES: issue 1 (the unbounded hook-time walk) must be fixed before merge. Issues 2 to 4 should be fixed in this branch or filed.
[ ] REJECT

## Evidence (kept for the plan)

- Verdict probe: `/workspace/untracked/scratch/rv610_probe.py`. Outputs: `rv610-probe-workspace.txt` (main), `rv610-probe-worktree-issue-204-trailing-slash-glob.txt` (5ddf49624) and `rv610-probe-head.txt` (3415cd1ee, identical verdicts).
- Cost probe: `/workspace/untracked/scratch/rv610_perf.py` (cases 0, 1 and 2).
- Baseline test run: `/workspace/untracked/scratch/test_rv610_baseline.py`, `rv610-baseline-tests.txt`.
