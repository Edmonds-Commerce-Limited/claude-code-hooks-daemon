STOPPING BECAUSE: review complete. I didn't modify the worktree (git status is clean), and every fixture was a temp directory under /workspace/untracked/scratch/rv598/.

**Counts:** 0 Critical, 1 Important, 2 Suggestions. **Verdict: REQUEST CHANGES** (only the Important finding blocks; it's a small fix).

**Checks:** shellcheck on `scripts/lib/resolve_venv.sh` is clean. The 29 resolver/paths test files (including the 2 resolve_venv files touched here) pass: 391 tests, PYTHONPATH=src, worktree venv. Output is in `/workspace/untracked/scratch/rv598-tests-all.txt`.

**Important**

1. **When all candidates are for another path and all fail, the error no longer says why (confidence 75).** `scripts/lib/resolve_venv.sh:488-491`, `_rv_pick_ranked_scan`. I set up two venvs slugged for another path, both exiting 3, and ran `_rv_resolve_python_impl`. origin/main printed one `failed to run` line per candidate. This branch prints nothing per candidate, then the generic `no usable venv found ... Build the venv for this project path with: ... repair` (rc=5). The suggested repair is correct, but nothing says venvs existed and were skipped for another path. This is the regression you asked me to flag. Fix: count the skipped other-path failures in a global (it can't be a subshell variable). When the scan returns 1 with that count above 0, print one summary line in the final error, e.g. `N venv(s) built for other project paths were skipped`. Add a test that runs `_rv_resolve_python_impl` and checks for that line. Probe: `/workspace/untracked/scratch/rv598/probe2.sh`.

**Your questions**

- **Q1 (choice vs origin/main):** unchanged apart from the intended ordering. Rank is still the outer loop. With an own-slug venv on an old lock_hash and an other-slug venv on the current lock_hash, both main and this branch pick the other-slug venv (same probe).
- **Q3 (parity):** shell and Python slugs match for symlinked paths, trailing slashes, `..`, uppercase, non-ASCII and the >40-character truncation. The shell output is the same under C and C.UTF-8 locales. I had no fixture short enough to test non-ASCII filtering without truncation; the md5 suffix does show the full-path bytes agree. Probe: `/workspace/untracked/scratch/rv598/probe.sh`.
- **Q4 (legacy un-slugged and `.venv`):** a legacy name still warns, and so does any name when the own slug can't be computed. The `HOOKS_DAEMON_VENV_PATH` override and cache paths aren't touched.
- **Q5 (error hiding):** no `|| true`. The `> /dev/null` lines only silence stdout of `command -v`.
- **Changed test** (`test_resolve_venv_scan_ranking.py:116`): its intent is preserved. It still checks that a broken best-rank venv falls through to the next rank and is reported. Only the broken venv's name changed to the own slug, since an other-slug failure is now silent by design. That silent path is covered within one rank by `test_other_views_drifted_venv_is_skipped_without_a_warning`, but not when it falls through across ranks.

**Suggestions**

- **Existing shell/Python mismatch, not introduced here:** the shell scan still accepts a working venv slugged for another path (probe2 picks `zzz_other`), while `paths.py` `_venv_slug_eligible` rejects it. It's low impact, since the shell's choice only runs `paths.py`. If you want the scan to follow Plan 00313's eligibility rule, document or align it.
- **`_rv_venv_is_own_slug`:** this matches the own slug as a literal prefix, while Python finds the slug by its rightmost match. They only disagree on unrealistic names (a slug containing `-pyNN-hex`). Worth a one-line comment.