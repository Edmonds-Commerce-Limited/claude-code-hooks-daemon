## 17:02 · action · — — D-EXEC fixes

Security review D-EXEC fixed in the repository classifier (commit 8b7095442, `core/scratch_repos.py`).

- D-EXEC 2: pointer files (`.git` file, `commondir`) are read with `read_small_regular_file`: lstat, regular-file check, `O_NOFOLLOW|O_NONBLOCK`, fstat and a size cap. A FIFO or symlinked pointer no longer hangs the sweep or leaks the target's text; the OUTSIDE_POINTING reason no longer echoes the pointer.
- D-EXEC 1: nested git runs with `submodule.recurse=false` and `diff.ignoreSubmodules=all`; status ignores submodules; any gitlink (mode 160000) in a related clone's index makes it PROTECTED, because its state is not proved. The filter-sentinel test needed a same-size edit: git never runs a filter when the size differs, which is why a first version passed at RED.
- D-EXEC 3: the registered-worktree advice quotes the path with `shlex.quote`.
- Note: the `branch` config allowlist accepts the branch_records keys, so a pushed clone carrying them still gets P4.
