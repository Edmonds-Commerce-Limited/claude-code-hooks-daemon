STOPPING BECAUSE: review complete.

**Verdict: changes requested.** The 18 new tests fail on main and pass on the branch, and the related tests pass (151). Apart from backslash escapes, the translator gives the same answers as `fnmatch` on globs without a POSIX class (fuzzed). `scandir` lists one directory, fails open on `OSError` (the shell can't expand there either), and costs one listing per call.

1. **IMPORTANT** `src/claude_code_hooks_daemon/utils/protected_file_index.py:350-382`. `*` becomes a greedy `.*`, so matching backtracks polynomially. `*a*a*a*a*b` against a 255-char name takes 10.9s (`fnmatch`: about 0s). An ordinary glob, `*-*-*-*-*.json` against a 244-char name, takes 0.7s, and that runs once per file per depth. The docstring's claim that matching "cannot blow up" is false. Fix: write each `*` plus the literal after it as an atomic group `(?>.*?X)`, as CPython's `fnmatch` does, and add a timing test.
2. **SUGGESTION** `:231-244`. A glob under a symlinked literal parent still gets through: with `up` pointing at the project root, `grep -r x up/di?/` is allowed while `up/dir/` is denied. Fix: realpath the literal parent before matching.
3. **SUGGESTION** (already on main): `grep -r x d*`, with no trailing slash, is allowed for a real protected directory.

Probes: `/workspace/untracked/worktrees/worktree-plan-612-glob-allows/untracked/scratch/review612/` (`probe.py`, `probe2.py`, `test_probe612*.py`).