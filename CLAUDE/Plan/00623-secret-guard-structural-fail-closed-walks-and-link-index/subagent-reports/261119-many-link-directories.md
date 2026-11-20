# Plan 00623 follow-up: more than 512 link-holding directories

Branch `agent-a13d7c8504105d4c9-aeae03b4`, from tip `aa5e3d0fe` with `main` merged (`de94ddcb9`). Code commit `71ca5278a`.

## Start state

- The WIP commit `aa5e3d0fe` (the review's last test edits) was re-verified: its three files gave 642 passed, 0 failed.
- The merge with `main` conflicted only in ledger 00474: N668's status (kept the branch's "Fixed"), then N669 and N670 (branch) followed by N671 (main).

## Design

Past `LINK_SCAN_DIRECTORY_CAP` (512) the link-holding directories are judged **by link name** instead of from each directory.

- **Why it is sound.** A computed move lands in some project directory `X`. A word `w` read there passes through a link only if a leading part `p` of `w` makes `X/p` a link path. Then `p`'s components equal the trailing components of that path, whatever `X` is. So `LinkNames.reaches(w)` is true when any leading part of `w` spells the tail of any link path in the project. Globbed components are matched with `fnmatchcase` and also literally (bash keeps an unmatched glob as written). A component holding `(`, `{` or `\` matches any name. A `..` anywhere counts as reaching.
- **Where the paths come from.** `LinkIndex.verify` now returns every link entry it listed (`LinkScanResult.links`), from the same verification that produces `holding` and `directory_links`. Nothing new is stored and nothing is read from disk, so the cache is no more forgeable than before.
- **What stays a real base.** Directory links stay real bases (`_add`, `scanned`, `computed_links`), because their targets are not in the index. They are bounded by `INDEXED_DIRECTORY_LINK_CAP` (512). All links are bounded by `INDEXED_LINK_CAP` (65,536). Past either bound the scan is `stopped` and denies.
- **Under the cap nothing changes.** `_scan_from_index` returns exactly what it did. `_walk_project_links` (the cold walk) is untouched and still stops at 512.
- **Kept denies, made explicit:**
  - `CwdSet.overflowed` is forced true, so the guard's line-1922 deny (a relative glob or word past 17 directories) and `_overflow_mention` keep firing.
  - A relative or globbed `cd` after the move marks the walk `unscanned`, as it did past 17 existing directories.
  - Recursive search is marked `lost`/`overflowed`, as it was past `SEARCH_DIRECTORY_CAP` (64). Every later read is judged over every indexed file, and each directory link is read as a root.

## Tests

`tests/unit/handlers/pre_tool_use/test_secret_file_guard_many_link_directories.py` (80 tests). `LINK_SCAN_DIRECTORY_CAP` is patched to 8 and the fixture holds 20 link-holding directories.

- **Ordinary commands allowed (RED before the change):** `cd "$D" && cat r.md`, `cd -`/bare `cd`/`cd $(…)` then a read, `cd "$(mktemp -d)" && ls`, `cd "$TMPDIR" && python3 x.py`, `cd "$(dirname "$0")" && ./run.sh`, `cat src/main.py`, `ls -la`, `npm test`. Each is tested with and without a link out elsewhere in the tree.
- **Denied (a link to the protected dummy and a directory link out, in the last tree):** `cat late`, `zz/late`, `wNN/zz/late`, `l*`, `z*/late`, `./zz//late`, `dl/<protected>`, `../zz/late`, `src/../zz/late`, `cd zz && cat late`, `grep -r x dl`, `grep -r x .`, `cd ~ && cat late`, `cd - && head late`. The same list is tested with the links made after the build.
- **Negative twins:**
  - a cold index denies;
  - an overflowed index denies;
  - more directory links than their bound deny;
  - more links than their bound deny.
- **Shape:** under the cap the scan carries no `named` and lists every directory. Past it, `directories` holds only the directory links.
- **Recursive search:** a search from a holding directory with a protected file below it denies. This test is RED with the `lost` line disabled.
- **`TestLinkNames`:** the name rule on its own, 22 cases.

## Differential and cost

The oracle is the tip with `LINK_SCAN_DIRECTORY_CAP` lifted in-process: `untracked/scratch/p623-512/p512.py` in the worktree, 24 commands, index built and aged past the racy window.

- **0 DENY-to-ALLOW against the oracle**, at 700 and at 5,000 link-holding directories.
- **2 ALLOW-to-DENY against the oracle.** `cat .bin/tool` denies because it names a link, even though the link stays inside the project. `cat a/../zz/late` denies because it holds `..`.
- **Cost at 5,000 holding directories (about 10,000 directories):** 0.1 to 0.25 s per command, against about 1 s for the oracle. The oracle's cost was `_anchored_spellings` and glob matching over every holding directory per word. What remains is mostly `LinkIndex.verify` (about 0.23 s), which is unchanged.

## Fail-closed (review harness)

`/workspace/untracked/scratch/00623-review/tools/failclosed.py` was re-run on this tree, cold and built. It covers 364 probes × 11 forced stops × 2 fixtures.

- **0 deny-to-not-deny in all 44 runs.**
- The built `link-scan-cap-2` scenario now goes through the name path rather than a stopped scan. It opened nothing.
- The forced stop for "directory-link bound 0" is the unit test `test_more_directory_links_than_their_bound_deny`.
- The harness's `oracle.py` (real bash) was **not** re-run.

## Targeted tests

Run on commit `71ca5278a`.

- **Every `test_secret_file_guard*` file, plus the flaggable and quarantine guard tests:** 2,836 passed, 11 skipped, 0 failed.
- **Utils and the rest:** `test_bounded_walk`, `test_link_index`, `test_recursive_search*`, `test_resolution_failure`, `test_secret_file_matching*`, the hostile-input performance file and `test_payload_capture` gave 1,192 passed, 0 failed.
- **Static checks:** ruff and black are clean on the changed files, and mypy is clean on the three changed modules. Pyright was not run.

## Judgement calls that loosen something

1. **Holding directories past the cap are no longer lexical cwds.** Against the cap-lifted oracle, a word is no longer joined to each holding directory for protected-glob anchoring (`_anchored_spellings`), nor for `link_out_of` and `bases_above_scanned`.
   - This matters only for a configured protected glob with a directory part. None of the defaults has one.
   - The anchoring was incidental anyway: a computed move can land in any project directory, and a directory that holds no link was never a base.
   - Link reach through those directories is covered by the name rule. A relative glob is still denied by the overflowed-set deny.
   - Against the shipped tip this is no loosening, because the tip denies every such command.
2. **Words past the cap are allowed at all.** Before, every relative word after a computed move in such a project was denied. Now a word that names no link and holds no `..` is allowed. That is the purpose of the change, and it rests on the soundness argument above.
3. **Directory-link bound.** The bound is the same 512 as before, now under its own name. It is not raised.

No placement override of a stopped scan was added, and no folder is excluded from the index. The 200,000-directory build cap is unchanged.

## Left

- **pnpm trees:** each `node_modules/<pkg>` there is a directory link, so a pnpm tree past 512 of them still denies.
- **This repository** still overflows the 200,000-directory build cap (N670). That needs an owner decision.
- A stopped scan still hands every found directory to the walkers before it denies. That costs time on large trees, not correctness, and predates this change.
- An independent review of this change.
