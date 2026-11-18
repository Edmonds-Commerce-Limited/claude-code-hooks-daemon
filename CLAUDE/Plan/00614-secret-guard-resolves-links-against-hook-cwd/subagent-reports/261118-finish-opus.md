# Plan 00614: review 614c fix round, merge of main, final corpus

Branch `agent-a13d7c8504105d4c9-aeae03b4`, pushed, not merged to main. Started at dcb6cbab3 (review 614c P2 RED committed, P2 GREEN and N1 RED uncommitted in the tree).

## Commits

| Commit    | Content                                                                                       |
| --------- | --------------------------------------------------------------------------------------------- |
| f591fc2d6 | P2 GREEN: a cap or deadline hit beside a search or glob denies                                |
| 82a247f48 | RED: N1 (a computed `cd` INTO a directory link)                                               |
| 0b1f5f71f | N1 GREEN: the link scan also returns directory links (`computed_move_directories`)            |
| 66f760d73 | formatter blank lines                                                                         |
| 8d8b44f73 | merge of origin/main (Plan 00618, which carries Plan 00615)                                   |
| c54757ba9 | RED: P2 other routes (parse error, internal error, Grep tool), many failed `cd`s, N3          |
| eb3a49b18 | GREEN: every gave-up route denies beside a search; search walk capped; N3 partial             |
| bdca16e36 | RED: a search past the cap misses a link out (also allowed on main and on dcb6cbab3)          |
| 3d25880d2 | GREEN: past the cap, every place a move could reach is read too; duplicate `_ASSIGNMENT_WORD` |

## What changed

- **P2.** `_gave_up_finding_or_advisory` now covers all four routes where the full scan stops: the cap, the deadline, an unreadable word and an internal error. A Bash command holding a recursive search or a glob, and any Grep tool call, is denied with a "scan stopped before it finished" cause. The no-search case keeps the advisory. The advisory test that pinned an allow for a failed Grep-tool walk now expects the deny.
- **N1.** A computed `cd` adds each directory link as a candidate cwd, in both walkers. Cost was measured with 300 links: about 0.13 s per call.
- **Search walk cap (found during this round).** A failed `cd` keeps its base next to its target, so the search walker's directory set could double with each `cd`. The new gave-up route calls `search_reads` with no deadline, so 20 relative `cd`s were enough to hang the guard. Past 64 directories (`SEARCH_DIRECTORY_CAP`), later moves are no longer followed. Each later read is judged over every indexed file, and over the project root, the targets and every directory link from the link scan.
- **Link out past the cap (pre-existing on main and on dcb6cbab3).** In a project with 300 links out, `cd $(echo x) && grep -r hello .` was allowed. It is now denied.
- **N3 (partial).** A `cd` operand with an extended-glob opener is treated as computed in both walkers; the text walker puts back the `(` that its split removes. When the command names `CDPATH`, a relative `cd` is also treated as computed. `eval` is now a command-start word in the text walker. The shell-function form was already denied once N1 landed.
- **Merge.**
  - `recursive_search` keeps this branch's walk over several directories and takes in main's additions: the rg config context, the lost directory after an unplaceable tilde, roots passed through pipeline stages, the directory readers from Plan 00615, and relocating env vars.
  - main's `expand_tilde` is stricter, so it replaces this branch's `_expand_tilde`.
  - A chdir wrapper's move now keeps the starting directory as a base. Without that, the merge allowed `env git -C d grep --no-index` where main denies it.
  - `effective_cwds` keeps this branch's walker, which already reads `git -C`. main's single-purpose `git -C` helpers are dropped.

## Verification

- Import check: `claude_code_hooks_daemon.__file__` resolves to this worktree's `src`.
- Targeted suites, run file by file (secret guard ×15 files, quarantine, flaggable ×2, index, recursive search ×2, resolution failure, grep grammar, exemptions, matching ×4, segmentation ×7, 4 integration files): all pass at eb3a49b18. After 3d25880d2, the guard and search suites were re-run: 3041 passed, 11 skipped.
- Targeted QA at 3d25880d2: `llm_qa.py format lint type_check pyright error_hiding magic_values fail_open_inventory` passes 7/7.

## Corpus check (DENY to ALLOW must be 0)

Harness: `untracked/scratch/corpus614.sh` and `corpus614_cmp.py`, using the review probe `rv614c/probe_min.py` (guard verdict plus a real bash run on synthetic fixtures). Case files: 14 in all, from reviews 614 to 614c plus this round's `cases614h.json`. `cases614b.json` is excluded because it is not valid JSON for this probe. Each runs in the full and the minimal fixture. Old and new outputs have equal line counts.

| Compared with           | Cases | Old denies | New denies | DENY to ALLOW |
| ----------------------- | ----- | ---------- | ---------- | ------------- |
| origin/main             | 1046  | 185        | 780        | **0**         |
| dcb6cbab3 (round start) | 1046  | 652        | 780        | **0**         |

The new tip raised 0 times. The 29 allows that leak dummy content are all allowed on both old refs too:

- Shapes reading the env-file dummy: that file name is not in the guard's six default patterns, so these are not protected reads.
- The residuals below.

## Residuals (not fixed, recorded)

- **N2: a physical `..` through a directory link.** Examples: `cat dlink/../*`, `head -n1 dlink/../i*`, `cd -P dlink/.. && cat *`, `grep -r x deep/idlink/..`. main's `_physical_root` resolves the search form, but the physical target lies outside the project, so the index does not cover it. Fixing this needs the link-out rule applied to physical roots, and `-P` handled in the text walker.
- **A glob matching a file link** (`cat lin[k]1.txt`). The wildcard-names-the-link rule covers directory links only.
- **An absolute glob outside the project** (`cat /other/checkout/sub/*`).
- **`cat */*` through a link.** The plan allows this by decision: a glob made only of wildcards names no place.
- **Over-deny (accepted).** After a computed or no-match globbed `cd`, a glob or relative read is now denied in a project that has a directory link out (N1). `TestComputedDirectoryChange::test_a_globbed_target_costs_a_bounded_walk` now asserts cost only.
- **CDPATH inherited from the environment.** Only a `CDPATH` named in the command is seen.

## Plan 00615

Not built here. main already carries it: Plan 00618 Task 2.1 / Plan 00615, commit d22224dc0, which covers `find -exec`, `xargs` and the directory readers. The merge kept it, and its tests (`test_secret_file_guard_directory_readers.py`, 162) pass on this branch.
