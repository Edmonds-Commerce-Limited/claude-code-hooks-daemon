STOPPING BECAUSE: the review is complete. All three of the prior review's findings hold up.

**Verdict: APPROVE.** Nothing blocks the merge. Three stale docstrings are left to file as a low-severity plan task.

1. **Backtracking: fixed.** The pathological globs (`*a*a*a*a*b`, the 8-star form, and the `?`, `[a]` and `a?` runs, all against 255 chars) now take about 0.1–0.2 ms each. 300k random globs with no POSIX class gave 0 mismatches against `fnmatchcase`. A further 4,000 cases using `^`, `[:alpha:]` and `[:digit:]` gave 0 mismatches against bash `[[ == ]]` under `LC_ALL=C`.
2. **Symlinked parent: correct.** `up/dir/` and `up/di?/` are both denied. It cannot escape the project: a realpath outside the project matches no indexed file, and a link to an ancestor (`out/project/di?/`, `rootl/*/`) is still denied. A dangling link or a link loop is allowed, which is right because there is nothing to read. Non-strict `realpath` does not raise, and `scandir` errors return `()`.
3. **Bare globs: consistent.** In a project whose only protected file is nested, `grep -r x *`, `di[rx]` and `./*` deny just as `grep -r x .` does. `cat *`, `ls *`, `ls -R *`, `grep x *` and `wc -l *` stay allowed, because only grep-family readers that recurse reach `_reads_of_roots`.

**Stale docstrings (low severity):**
- `protected_file_index.py:210` still says "``token`` ends in ``/``".
- In `recursive_search.py`, the `_directories_read` docstring (around line 377) and the `_EXPANSION_ROOT` comment at line 112 still say a glob must end in `/`.

2,347 related tests pass. The probes are in `/workspace/untracked/worktrees/worktree-plan-612-glob-allows/untracked/scratch/r612/`.