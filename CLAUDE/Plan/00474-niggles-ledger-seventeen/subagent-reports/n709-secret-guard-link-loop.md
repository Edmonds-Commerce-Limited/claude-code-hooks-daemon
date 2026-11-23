# N709 fix report: secret guard denies the plan-script bootstrap

**Branch**: `fix-n709-secret-guard-bootstrap`. **Status**: fixed, pending merge and independent security review.

## Root cause

The ledger's suspected mechanism was wrong. No glob-overlap heuristic (`_glob_token_overlaps_stem`, `_glob_intersection_mention`) fires on the bootstrap. Tested against the bare matcher with no index, every bootstrap variant gave `None`.

What actually happens:

1. The bootstrap contains a computed `cd` (`cd "$(dirname "${BASH_SOURCE[0]}")"`). `_DirectoryWalk.indeterminate()` responds by adding every link-holding project directory as a base. Here that was 275 directories, from the link index.
2. Past `LINK_DIRECTORY_CAP` (16) of them the `CwdSet` is `overflowed`. `_overflow_mention` then denies any relative word that `CwdSet.could_be_link` accepts, and it reports `patterns[0]`. So `*.secret*` was never really "matched": it is just the first default pattern.
3. `CwdSet._listing` built its listing with a link-following `entry.is_dir()`. A pair of links pointing at each other raises ELOOP, so the whole directory became `None` ("cannot be listed"). `could_be_link` returns True for every word when any listing is `None`.
4. The reported token is therefore simply the first relative word: `cat`, `cd`, or `bash` (the shebang's argument on the Write route).

## Reproduction in this repository

A probe heredoc was denied with the sentence "moves into more than 16 existing directories". The culprit was another agent's scratch directory holding a two-link loop. I did not touch that directory. I also did not open any protected file.

The same defect hit this fix's own test file. Python test strings containing `cd "$D"` were denied, so the test assembles the move from pieces.

## Fix

The fix is in `src/claude_code_hooks_daemon/utils/secret_file_matching.py`. A new helper, `_listed_kind`, classifies each entry on its own:

| Entry                                   | Classified as                                                 |
| --------------------------------------- | ------------------------------------------------------------- |
| A link in a loop                        | a link that is not a directory (as `_link_kind` already says) |
| An entry whose link-ness cannot be told | a link to a directory (fail closed)                           |
| A non-link whose type cannot be told    | a directory (same as `_entry_may_be_directory`)               |

A `scandir` that fails for the whole directory still yields `None`, which still denies every word.

## Tests

`tests/unit/handlers/pre_tool_use/test_secret_file_guard_link_loop.py`: 23 tests, red before the fix for the reason above. The fixture is hermetic: 20 link-holding directories plus one loop.

**Now allowed** (Bash and Write routes):

- The bootstrap, read from the Plan 00213 `PROPOSAL.md` template. No committed plan script sources the library yet.
- `cd "$D"`, `bash`, `mkdir y`, `cat r.md`, `echo` after the computed move.

**Still denied:**

- The loop's own link names, and `t*`.
- A link beside the loop that points at a protected dummy (`late`, `bin/late`).
- A protected path named by its literal spelling.
- Any word, when the directory's `scandir` refuses.

**Suites run:** secret guard and matcher suites (3898 passed, 11 skipped), plus ruff, black and mypy on the changed files.

## Residual, not fixed

A truly unlistable directory, or an unfinished link scan, still denies every relative word after a computed `cd`, command names included. Exempting command-position words is a wider change (`./x`, `. x`, a PATH holding `.`) and needs its own review. It is unconfirmed whether fedora-desktop.1's deny comes from a loop or from this residual. The diagnostic: does their deny carry the "more than 16 existing directories" sentence, and is there a link loop under their project?
