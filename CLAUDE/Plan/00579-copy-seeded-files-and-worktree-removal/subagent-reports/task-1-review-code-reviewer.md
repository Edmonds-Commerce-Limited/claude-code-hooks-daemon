# Task 1 review (code-reviewer, read-only; reply recorded by the coordinator)

Verdict: **approve** for branch `worktree-579-seeded-copy-removal` at `b155d6b21`. No critical or important findings. The reviewer's probe is `untracked/scratch/579-review/test_probe_579.py`; both new test files plus the probes gave 27 passed and 1 skipped (a chmod test, skipped under root).

## Checked and safe

- A missing or malformed config excuses nothing (`install/worktree_seed_report.py`).
- Path traversal and absolute paths: matching is exact or by prefix against entries git produced, so nothing unsafe gets through.
- Tracked or dirty files never reach the seeded-copy judgement.
- Directory seeds: the file sets must be equal. Extra, missing or unreadable files all block, and FIFOs and sockets are never opened.
- A symlink inside a seed is compared by link target. A symlink in the worktree is excused by the existing symlink filter.
- Main-checkout resolution: a bare repo, a submodule or git older than 2.31 excuses nothing. The config is read from main.
- Large files are compared in 64 KiB chunks after a size check.
- The tests use real temporary repositories and worktrees.

## Suggestions

1. **Taken: fail-unsafe.** If a parent directory of the seed in main is a symlink into the worktree being removed, the source is the copy itself, so it compares identical. Fix: refuse the comparison when the source resolves inside the worktree.
2. **Not taken; fails safe.** A nested seed under a wholly ignored directory still blocks, because `ls-files --directory` reports the parent.
3. **Taken.** Bound the comparison's size inside the hook; going over the bound counts as "differs".
4. **Not taken; fails safe.** `./`-prefixed seed paths are never excused.
