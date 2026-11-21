## 17:37 · decision · Task 3.0 N2 — N2: a git directory must prove it is bare

Task 3.0 N2 closed (`core/scratch_repos.py`). A git directory found with no `.git` marker (a "bare candidate") is now disposable only when it proves it is bare: its config's last `core.bare` must be a git true value and it must hold no `index`. Otherwise it is OUTSIDE_POINTING (PROTECTED), with a reason naming the directory and `git init --separate-git-dir`; an unreadable config stays STUCK through the existing config read. A value-less `core.bare` counts as not bare (fail closed).

A git directory that a `.git` file in the same entry points back at is not a bare candidate: that marker judges it (work tree and git directory both in the entry), so a fully contained `--separate-git-dir` repository stays DISPOSABLE.

Tests: `TestSeparateGitDirectories` in `test_scratch_repos.py` (outside work tree, no commit/no index, bare=true with an index, FIFO config, true bare, in-entry work tree) and two `n2` sweep tests in `test_scratch_sweep.py`.
