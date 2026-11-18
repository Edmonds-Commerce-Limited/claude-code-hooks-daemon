# Plan 00614: fix round 6, the six defects of the independent review

Branch `agent-a13d7c8504105d4c9-aeae03b4`, pushed, not merged to main. Review: `261118-independent-review.md` (FAIL, 6 defects, 0 DENY-to-ALLOW).

## The rule applied

A scan, resolution or placement that cannot finish denies. It is never logged and allowed.

## Commits

| Commit    | Content                                                                                       |
| --------- | --------------------------------------------------------------------------------------------- |
| 5d02e2ede | merge of origin/main; the branch's ledger entry N650 renumbered                               |
| 5e341797d | the entry is N661 (N650 to N659 are Plan 00618's, N660 is Plan 00622's); correction journal   |
| 54cc17217 | RED: one test class per defect D1 to D6, each built from the reviewer's probe                 |
| 3ea34344d | GREEN: D1 to D6                                                                               |
| 1995969ed | RED: a deeper relative word after a computed `cd` (found in the class sweep below)            |
| 8bcdc77e9 | GREEN: that defect; enum for the link kind (error_hiding); release note, ledger N662, PLAN.md |

## What changed

- **D1 (a link loop ended the scan).** Each entry is classified on its own. A loop (ELOOP) is not a directory. Any other error leaves the link's kind unknown, and the scan is then incomplete. One entry never ends a listing. `expand_directory_glob` does the same: an unknown match makes the globbed `cd` a computed move.

- **D2 (the 512-directory cap allowed).** `scan_project_links` returns `LinkScan(directories, complete, directory_links)`. The scan is incomplete past 512 directories, past 512 directory links, or on an unknown link. Both walkers then raise `IncompleteScanError`, a `ResolutionFailedError`:

  - the text walker, for any relative word read after the computed move;
  - the search walker, for any later reader.

  The guard's existing unresolved route denies it. The docstrings that called the cap "a residual recorded in the plan" are rewritten.

- **D2's cost.** In a project past 512 directories (most real repositories), every computed `cd` before a relative word denies. Measured on a 600-directory fixture: `cd $(printf plain)`, `cd $(printf plain); ls` and `cd "$D" && make test` all deny. To keep the common idiom working, `cd "$(git rev-parse --show-toplevel)"` is not treated as computed:

  - The quoted, backtick and walker-split forms are placed at each ancestor of the command's directory, up to the project root, with no scan.
  - A command that names a `GIT_` variable is still computed.
  - With no protected file in reach, `cd "$(git rev-parse --show-toplevel)" && ls -la`, `... && make test` and `... && grep -r x plain` are allowed on the 600-directory fixture.
  - The unquoted `$( )` form before a recursive search still denies.

- **D3 (option spellings).** `env`, `tar` and `sudo` chdir options are now read in all of these spellings:

  - in a short-option cluster: `-iC d`, `-iCd`, `-nD d`;
  - by any prefix of the long name: `--chd=d`, `--ch d`, `--c=d`.

  The cheap gate in front of the tokeniser accepts both. A misreading only adds a directory to judge from.

- **D4 (`exec`).** `exec` is read past like `command` and `builtin`, with `-c`, `-l` and `-a NAME` handled, in both walkers.

- **D5 (link made between calls).** The scan is reused only within one tool call (`link_scan_scope` around `_evaluate`), never for a wall-clock window. The reviewer's `cachecheck.py`, run with the cap above the fixture's size: before the link, allow; with the link just made, **deny**.

- **D6 (pathless Grep).** A Grep tool call with no `path` is judged at the absolute hook `cwd`. `cwdcheck.py`: `cwd = P/olink`, `P/inner/irel` and `P/inner` now deny.

- **Found in the class sweep: a deeper relative word after a computed `cd`.** The scan names each directory that holds a link, but the shell may be above it.

  - `cd $(printf q/sub); cat a/late` read the link in `q/sub/a`. It was allowed on main, on the round-start tip and after D1 to D6.
  - A word of several components is now also resolved from each directory above a scanned directory whose trailing components spell the word's leading ones.
  - On the search side, a reader after a computed move is also judged as reading every directory link the scan found. This is an accepted over-deny in a project holding a directory link out of the project, and it is in release note 002.

## Reviewer probes, re-run on the final tip (own fixtures built with the reviewer's harness)

- `loopcheck.py` on `fx/`: all four commands deny, including `cd $(printf plain); cat late` and `grep -r x latedir`, which were allowed. That fixture is past the cap, so the deny is the fail-closed route. The loop-only case under the cap is pinned by `TestALinkLoopDoesNotEndTheComputedMoveScan`, which uses a sorted `scandir` so the loop is met first.
- `cachecheck.py`: allow, then **deny**, then deny.
- `cwdcheck.py`: pathless Grep from a link-out cwd denies.
- `probes()` (157) and `probes2()` (59): the full results are in the comparison table below. What is still allowed on the new tip is exactly the reviewer's recorded residuals (N2, `fli[n]k`, absolute globs, `*/*`, CDPATH from the environment) and the "not counted" list: `nsenter`, `unshare`, `systemd-run`, in-language chdir, `git -C … cat-file`, `cat loopa`, `olin?`, `ls -R`, brace through a link, time-of-check `ln -s`, a NUL-bearing name and a 5,000-character name.
- Nested `bash -c` 1 to 7 deep around `cd inner; cat rel`, `cd olink; grep -r x .` and `cd olink; cat i*`: all deny on `fx/` and `fxn/`.

## Old-versus-new decisions (0 DENY-to-ALLOW required)

Harness: the reviewer's `tools/harness.py` (real `SecretFileGuardHandler`, process cwd `/`). Corpus: the reviewer's 2,390 commands, plus every string literal of this tip's guard, matching and search test files. Old trees are `origin/main` and the round-start tip (`54cc17217`, the merged branch before any fix; source snapshots under `untracked/scratch/614-r6/`). Fixtures `fx/` (protected file in the project) and `fxn/` (none) were built fresh in this worktree's scratch.

| Run               | Old tree    | Cases | Old denies | New denies | DENY to ALLOW | ALLOW to DENY | Errors |
| ----------------- | ----------- | ----- | ---------- | ---------- | ------------- | ------------- | ------ |
| corpus, `fx/`     | origin/main | 2446  | 784        | 1179       | **0**         | 395           | 0      |
| corpus, `fx/`     | round start | 2446  | 1078       | 1179       | **0**         | 101           | 0      |
| corpus, `fxn/`    | origin/main | 2446  | 781        | 1179       | **0**         | 398           | 0      |
| corpus, `fxn/`    | round start | 2446  | 1078       | 1179       | **0**         | 101           | 0      |
| `probes()`, both  | origin/main | 157   | 27         | 145        | **0**         | 118           | 0      |
| `probes()`, both  | round start | 157   | 142        | 145        | **0**         | 3             | 0      |
| `probes2()`, both | origin/main | 59    | 10         | 51         | **0**         | 41            | 0      |
| `probes2()`, both | round start | 59    | 38         | 51         | **0**         | 13            | 0      |

The ALLOW-to-DENY cases against the round-start tip fall into three groups:

- computed or globbed `cd`s in a fixture past the scan cap (`fx/` has 600 + 70 directories);
- the new chdir spellings and `exec`;
- quoted `bash -c` bodies holding an operator, which the text walker reads loosely as a computed move (recorded in N662).

## Targeted QA and tests on the final tip

Import check: `claude_code_hooks_daemon.__file__` resolves to this worktree's `src`.

QA at `8bcdc77e9`: `llm_qa.py format lint type_check pyright error_hiding fail_open_inventory magic_values eacces_safe inline_suppressions british_english` passed 10/10. No suppressions were added.

Tests: the guard-related files ran in two chunks of 17 and 18. The first held the 17 secret-guard, quarantine and flaggable handler files: 2484 passed, 11 skipped. The second held the 17 matching, search, segmentation, index, predicate and resolution-failure util files plus the wall-clock invariant: 2020 passed. No whole-suite run was made, and `changed_tests` was not run, since it timed out over this range in the previous round. Files outside these sets, such as CLI and docs QA, are left to the coordinator's gate.

## The same defect class, again and again: proposal for a structural fix

This is the sixth review round on this plan, and the class keeps returning: a bounded walk that stops (a cap, a slice, an error, a depth limit, a cache window) and whose caller treats "not found" as "not there". This round fixed five instances (D1, D2, D5, the D1 sibling in `expand_directory_glob`, and the deeper-word gap). The sweep found more of the same shape that were not fixed here (ledger **N662**):

- the quarantine guard sends `ResolutionFailedError` to its advisory route;
- the A1 no-search advisory route;
- a missing or relative hook `cwd`;
- suspected, not probed: the `[: LINK_DIRECTORY_CAP + 1]` base slices in `_DirectoryWalk.change` and `_expand`, which follow a relative or globbed `cd` from the first 17 directories only.

Patching each one as a review finds it does not converge. Three structural changes are proposed:

1. **One result type for every bounded walk.** Every bounded scan or listing returns a `Bounded[T]` (value plus `complete`), as `LinkScan` now does. No bare tuple or None should be able to mean "stopped early". Have a QA check (`fail_open_inventory` already scans boundaries) flag:
   - a `[:CAP]` slice;
   - a `return None` in an `except`;
   - a `log_and_continue` in the placement modules whose caller does not consume `complete`.
2. **One fail-closed wrapper at the guard boundary.** Anything incomplete raises `IncompleteScanError`, and the guards (secret and quarantine alike) map `ResolutionFailedError` to deny in one shared helper. The per-guard `except Exception` advisory routes should keep only what the owner has decided may advise (A1).
3. **Move the link scan off the hot path.** An index of links, built in the background like the protected-file index and denying until built, would remove the 512-directory cap. Large projects' computed `cd`s would then be judged rather than denied, which is the cost this round accepts.
