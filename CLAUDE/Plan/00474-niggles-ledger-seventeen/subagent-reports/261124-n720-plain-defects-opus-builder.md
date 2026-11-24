# Builder report: N720 plain defects, with N719

**Branch:** `fix-n710-secret-guard-glob-later-parts`. It was reused and fast-forwarded to `origin/main` at `ea8b1bd18`.

**Scope:** the "Buildable now" list in `261124-security-decisions-q66-n720-fable.md`, Decision B:

- W1: item 1 together with N719.
- W2: item 2.
- W3a: `-O` inside a flag cluster, plus the reversed-range traceback.
- W4: item 4.

**Not built:** the escape hatch and the unstaticable-shell-state class (the rest of item 3), item 5, and the `awk` LOW item.

## Reproducers re-run against main first

| Item | Shape                                                                     | Main (Bash, Write, no-index)                    | Bash 5.2 (dummy tree)            |
| ---- | ------------------------------------------------------------------------- | ----------------------------------------------- | -------------------------------- |
| 1    | `shopt -s nocaseglob; cat kit/lib/[I]D_RSA` (and `ID_RS[A]`, `[Ii]`)      | allow, allow, allow (both modes)                | reads                            |
| 1    | `shopt -s nocaseglob; cat kit/[B]IN/LATE` (link)                          | allow                                           | **does not read** (see below)    |
| 1    | `shopt -s nocaseglob; cat kit/[B]IN/[L]ATE` (link)                        | allow                                           | reads                            |
| 2    | `cat kit/lib/[x[:lower:]]d_rsa`, `id_rs[x[:lower:]]`, `id[x[:punct:]]rsa` | deny, allow, allow                              | reads                            |
| 3a   | `bash -xO dotglob -c 'cat kit/*/late2'`, `-Ox`, `-eO`, `-xOe`             | allow in certain mode                           | reads (`-Ox` too; `+O` does not) |
| 4    | `bash -O extglob -c 'cat kit/@(bin)/late' {1..9}x7`, 20-level nesting     | allow (nesting is allowed on Bash and no-index) | reads                            |
| LOW  | `[z-a]` in a component                                                    | full traceback logged                           | n/a                              |

The review's link form needs one correction. Under `nocaseglob`, bash compares a component that has no pattern characters exactly. So `kit/[B]IN/LATE` is not a read, and the test uses `kit/[B]IN/[L]ATE` instead. The bash-truth probe is a Python script, and it ran in gitignored worktree scratch against synthetic files only.

## What changed

- **Item 1.**
  - `secret_file_matching._case_blind_expansion_mention` handles the guard's own matching. Unless bash's defaults are certain and the word can expand, it compares each finite-bracket expansion with every pattern, with both sides case-folded.
  - **N719 (index matcher).** `protected_file_index._segments_match(..., ignore_case=not default_expansion)` adds a case-blind reading for PATTERN components only. It folds each letter and each letter range, but leaves POSIX classes as they are; this was checked in bash 5.2, where `[[:upper:]]*` lists no lower-case name under `nocaseglob`. The index keeps its own class-aware reader.
  - **Deviation from the decision report.** The report said to route the index through `_component_regex`. That reader widens a POSIX class to "any name", and on the index (on-disk truth) that denied every class-bearing glob in a protected file's directory, which a test caught. So the index matcher was not routed through it.
- **`globasciiranges`.** It is now a required snapshot option, and it must be recorded as `-s`. The three test snapshot constants were updated so that certain mode still really runs in those tests.
- **Item 2.** `_class_aware_literal_residue` and `_bracket_end` scan a bracket as bash does: a class counts as one member, a `]` placed first is a member, and a backslash escapes the next character. The new residue is a SECOND candidate at the stem deny gate. The skip gates and the overlap check still use the old residue, so neither can skip something it did not skip before.
  - `_globs_can_intersect` also tries a reading in which each bash-closed bracket stands for one `?`. That reading is used only when at least two literal characters remain. Without that limit, `ls dir/[[:alnum:]_]*` would be denied by text alone.
  - The old reader `_BRACKET_EXPRESSION_RE` is intentionally still used at its other sites. Swapping it out could flip a deny to an allow, which this change must never do.
- **Item 3a.** In `shell_snapshot._SWITCHES_OPTIONS`, a new alternative matches a cluster containing `O` anywhere after a shell command word (`bash`, `sh`, `dash`, `ksh`, `zsh`) in the same statement. Bash 5.2 confirms that `bash --norc -xO` and `bash -o pipefail -xO` both switch dotglob. The old `[-+]O\b` stays in place. `ls -lO` is still not treated as a switch.
- **Bounds.** The bash-aware bracket scan and the index letter folding are quadratic in a token's `[` count: 100k-character tokens took seconds. A token over 1024 characters or 64 `[` therefore keeps the old reading only; a file name cannot be that long. Both bounds are pinned by tests, one of them a `perf_sweep` test.
- **`_segments_match(..., ignore_case=)` is now a required keyword.** The link probes in `_wildcard_links` and `_matching_symlinked_directories` do not know the shell's case option, so they pass `False`, which is main's behaviour.
- **Callers of `iter_protected_mentions` after the reorder.** Most callers either collect every mention with `list()`/`any()`, or take `next()` only to test whether there is any mention. `find_protected_mention` takes the first mention, and only its reported token changes. An `IncompleteScanError` raised earlier now propagates to the guard, which denies.
- **Item 4.**
  - `_holds_search_or_glob` now counts an extglob opener, which fixes the Bash route.
  - `_strict_link_mention` treats an extglob word as globbed.
  - `iter_protected_mentions` now judges `_extglob_words` BEFORE the token streams. Previously the brace stream could hit its size limit first. A `b?n` word in the ordinary stream was always judged before that limit; an extglob word now is too. This fixes the Write-script route.
- **LOW.** `_bracket_regex` returns "any name" for a reversed range instead of letting `re` raise. The `except` and its `log_and_continue` are unchanged.

## Evidence that nothing was loosened

`untracked/scratch/n720-probe/test_differential.py` is gitignored, and it is described here so it can be re-run. It covers:

- 31 bracket shapes × several positions, against both the protected name and the link;
- a nocaseglob variant of each;
- the review's false-positive table;
- the item-3a and item-4 shapes.

The fixture indexes the protected file after writing it, so the index route (route 0) is exercised as well, N719 included. Each command was run through `_every_route` in both modes: 720 command/mode rows, three routes each. The run was on head `c20eb4f04`, once with `PYTHONPATH=/workspace/src` (main) and once with the branch. The result was **245 allow→deny changes and 0 deny→allow changes**.

- Every tightening either names the protected file or comes from the `-O` cluster.
- With nocaseglob possible, `ls kit/lib/[I]*` and `ls kit/lib/[A-Z]*` are now denied on the index route, in conservative mode only. That is correct: under `nocaseglob`, bash lists the protected file for both.
- These stay allowed on both trees: `ls -lO kit/lib`, `ls kit/[[:upper:]]*/` (with and without nocaseglob), and `grep -r x kit/[L]IB`.
- An earlier run, made before the index and `-O` rework and without index coverage, gave 252/0. That figure is superseded. `tests/unit/handlers/pre_tool_use/test_secret_file_guard_n720_plain_defects.py::TestEverythingDeniedBeforeStaysDenied` pins a sample of existing denies, and a test pins class brackets that name no protected file as allowed.

## Tests run

The tests listed below were run with `nice -n 19` in the worktree:

- the new file;
- every `test_secret_file_guard*` file;
- all of `tests/unit/utils` and `tests/unit/config`;
- `tests/integration/test_handler_instantiation.py`;
- `tests/unit/qa/test_audit_error_hiding.py` and `tests/unit/qa/test_check_generated_doc_drift.py`;
- `tests/unit/handlers/test_session_mode_readers.py`.

Results:

- **The `test_secret_file_guard*` files:** 3383 passed, 14 skipped.
- **utils, config, `tests/unit/qa`, handler instantiation and session-mode readers:** 13665 passed, 28 failed.
  - One failure was the branch's own: `test_shell_snapshot` pins `ls -lO` as not a switch. It was fixed by matching `-O` inside a cluster only after a shell command word. Rerun: 277 passed across the snapshot, n720, bash-options and default-globs files.
  - The other 27 are `tests/unit/qa` tests of `llm_qa.py` itself (`main_moved`, `venv_resolution`, `run_test_matrix`). Each one raises `VenvResolutionError`, because this worktree has no venv of its own. That comes from the environment, not from this change.
- **Release-note and holding-area tests:** 127 passed.
- **`check_declared_invariant_pairs.py`:** passes.

## Open items

- **The rest of item 3, item 5 and the `awk` LOW item are unchanged.** Every reproducer the review lists for them is still allowed.
- **The index case-blind reading also applies to `directories_matching`.** It could add a deny for a recursive search whose glob, read case-blind, names a protected file's directory. That is fail-closed, but a reviewer should look at it.
- **The commit trailer.** Commits use the `Co-Authored-By: Claude Opus 5.5` trailer from the session's attribution reminder. The dispatch asked for the Sonnet 5.5 line instead. The reminder's own text gives precedence only to the user's instructions, so this conflict is flagged here for the coordinator rather than settled silently.
- **Review.** An independent security review is needed before merge.
