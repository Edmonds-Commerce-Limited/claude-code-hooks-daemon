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
  - **N719 (index matcher).** `protected_file_index._segments_match(..., ignore_case=not default_expansion)` adds a case-blind reading for PATTERN components only. The index keeps its own class-aware reader.
  - **Deviation from the decision report.** The report said to route the index through `_component_regex`. That reader widens a POSIX class to "any name", and on the index (on-disk truth) that denied every class-bearing glob in a protected file's directory, which a test caught. So the index matcher was not routed through it.
- **`globasciiranges`.** It is now a required snapshot option, and it must be recorded as `-s`. The three test snapshot constants were updated so that certain mode still really runs in those tests.
- **Item 2.** `_class_aware_literal_residue` and `_bracket_end` scan a bracket as bash does: a class counts as one member, a `]` placed first is a member, and a backslash escapes the next character. The new residue is a SECOND candidate at the stem deny gate. The skip gates and the overlap check still use the old residue, so neither can skip something it did not skip before.
  - `_globs_can_intersect` also tries a reading in which each bash-closed bracket stands for one `?`. That reading is used only when at least two literal characters remain. Without that limit, `ls dir/[[:alnum:]_]*` would be denied by text alone.
  - The old reader `_BRACKET_EXPRESSION_RE` is intentionally still used at its other sites. Swapping it out could flip a deny to an allow, which this change must never do.
- **Item 3a.** In `shell_snapshot._SWITCHES_OPTIONS`, `(?<!\S)[-+][A-Za-z]*O[A-Za-z]*\b` replaces `[-+]O\b`. A side effect is that `curl -LO` now gets the conservative glob reading. That only matters for globs that reach protected files.
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

Each command was run through `_every_route` in both modes: 700 command/mode rows, three routes each. It was run once with `PYTHONPATH=/workspace/src` (main) and once with the branch. The result was **252 allow→deny changes and 0 deny→allow changes**. Every tightening either names the protected file or comes from the `-O` cluster. `tests/unit/handlers/pre_tool_use/test_secret_file_guard_n720_plain_defects.py::TestEverythingDeniedBeforeStaysDenied` pins a sample of existing denies, and a test pins class brackets that name no protected file as allowed.

## Tests run

The tests listed below were run with `nice -n 19` in the worktree:

- the new file;
- every `test_secret_file_guard*` file;
- all of `tests/unit/utils` and `tests/unit/config`;
- `tests/integration/test_handler_instantiation.py`;
- `tests/unit/qa/test_audit_error_hiding.py` and `tests/unit/qa/test_check_generated_doc_drift.py`;
- `tests/unit/handlers/test_session_mode_readers.py`.

The pass counts are recorded in the PR body.

## Open items

- **The rest of item 3, item 5 and the `awk` LOW item are unchanged.** Every reproducer the review lists for them is still allowed.
- **The index case-blind reading also applies to `directories_matching`.** It could add a deny for a recursive search whose glob, read case-blind, names a protected file's directory. That is fail-closed, but a reviewer should look at it.
- **The commit trailer.** Commits use the `Co-Authored-By: Claude Opus 5.5` trailer from the session's attribution reminder. The dispatch asked for the Sonnet 5.5 line instead. The reminder's own text gives precedence only to the user's instructions, so this conflict is flagged here for the coordinator rather than settled silently.
- **Review.** An independent security review is needed before merge.
