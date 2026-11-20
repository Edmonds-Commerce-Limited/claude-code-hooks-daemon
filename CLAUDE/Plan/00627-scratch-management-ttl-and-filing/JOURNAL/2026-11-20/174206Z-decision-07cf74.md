## 17:42 · decision · Task 3.0 reflog — Reflog and pseudo-ref commits join a related clone's tips

Task 3.0 reflog row closed (`core/scratch_repos.py`). A related clone's tip set (R6) now also holds:

- every commit a reflog names: `rev-list --no-walk --reflog --all --max-count=MAX_TIPS+1` through `_nested` (safe env and flags). `--reflog` includes each linked worktree's HEAD reflog (checked on git 2.47). `--all` is there because a bare `--reflog` with no reflog is an empty revision list that rev-list refuses with a usage error; it adds only ref tips already in the set.
- every commit named by `ORIG_HEAD`, `FETCH_HEAD`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `AUTO_MERGE` in the git directory, the common directory and each linked worktree's admin dir, read as files (`read_small_regular_file`, 64 KiB cap), never through git. A non-regular file or a line whose first word is not a sha is BROKEN (STUCK).

Any of those not contained by a live-verified remote tip (`_held_by_verified`) makes the clone PROTECTED; more than MAX_TIPS distinct commits is PROTECTED unproved. A stash's reflog entries are now also counted, on top of the existing "a stash" reason.

Tests: `TestRecoverableCommits` (reflog only, ORIG_HEAD only, FETCH_HEAD only, linked-worktree reflog, unparseable and FIFO pseudo-refs, MAX_TIPS bound, and a pushed clone with a pushed ORIG_HEAD and reflog staying covered). `rev-list` joined `_ON_THE_PUSHED_CLONE_PATH` in the wrong-verdict controls.

Residual: a long-lived clone with more than MAX_TIPS (200) distinct reflog commits is PROTECTED even when all are pushed (fail closed, by design).
