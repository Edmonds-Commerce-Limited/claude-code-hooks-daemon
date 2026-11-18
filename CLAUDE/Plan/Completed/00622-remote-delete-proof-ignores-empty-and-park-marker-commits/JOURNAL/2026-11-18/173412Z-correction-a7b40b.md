## 17:34 · correction · 16:28

The round 1 fix left 12 tests failing that its report did not list.

The three `R-GIT-PUSH-DELETE-REMOTE` test files are `test_destructive_git_remote_delete_merged.py`, `_chained.py` and `_lines.py`. Their fixtures built the "unmerged" branch, and the "pushed after our last fetch" commit, with `git commit --allow-empty`. Under the `empty-commits-only` rule such a branch is lossless to delete, so the guard correctly allowed it, and the tests expecting a deny failed. Round 1's targeted run did not include these files.

Each fixture commit now changes a file through the new shared `tests.support.git_fixtures.commit_content` helper, so it stands for real unmerged work again. No assertion changed.
