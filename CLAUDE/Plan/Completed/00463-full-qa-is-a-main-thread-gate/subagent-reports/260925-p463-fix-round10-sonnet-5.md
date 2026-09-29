# Plan 00463 fix round 10 (Sonnet 5)

Worked through review 10's full "For the next fix round" list, plus the coordinator's
decisions in the brief. Nothing skipped; two items turned out to need only pinning
tests, not new code, because the existing behaviour was already correct.

## Done, one commit per item

- `423b15d1c` **B2**: `full_qa_lock_is_held` proved possession by two independent
  facts (an inherited fd resolves to the lock path, a FRESH probe finds it locked),
  which an evader could pass for free by inheriting an UNLOCKED fd while an unrelated
  legitimate run held the lock concurrently. Now calls `flock` directly on each
  candidate inherited fd. RED-proven with review 10's G repro.
- `dab159e78` **B1 (sink) + m2 + m3 + m4**: `_total_test_file_count` anchored on
  `config.rootpath`, which `--rootdir` lets the caller repoint at an empty directory
  (with or without `-c /dev/null`); `total == 0` then allowed through. Now anchors on
  the directory of the conftest.py that actually imported the hook (found by identity
  via `config.pluginmanager`), and an unresolvable/zero count REFUSES. Also:
  `trylast=True` so `-k` deselection is counted (m2), the refusal message no longer
  claims `llm_qa.py changed` acquires the lock (m3), and the xdist docstring claim is
  corrected (m4). RED-proven for `--rootdir=<empty>`, `-c /dev/null` and `-k`.
- `a4438e377` **M2**: dropped the two wall-clock `elapsed` bounds in the M7 pin;
  `b"timeout" in result.stderr` already proves the relay's own budget fired.
- `7cf73ffec` + `3fda3de96` **m1**: `run_tests.sh`'s `flock` had no bound and no
  diagnostic (review 10's H repro: an orphan left holding a leaked, non-CLOEXEC fd
  blocks the next run forever). New `scripts/qa/acquire_full_qa_lock.bash` bounds the
  wait and names holder pids via `/proc`. `full_qa_lock_is_held` now marks the proven
  fd CLOEXEC (after the proof, never before). Incidental: fixed a pre-existing test
  (`"HELD" in probe.stdout` is also true of `"NOT-HELD"`) that was passing without
  actually proving fd inheritance. The fixup commit reworks a mid-loop `echo` that
  this repo's own capture-corruption auditor correctly flagged (not modeled: `for`
  loops) into a single terminal `printf`.
- `b00296d41` **B1 (handler decision)**: checked directly against
  `find_full_qa_invocation` -- every plugin-disabling shape the coordinator named
  (`--noconftest`, `-p no:`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `-c`/`--config-file`,
  `-o addopts=`/`--override-ini addopts`) already denies today, because the flag
  consumes its own value and `tests/` (or nothing, under `bare_is_full`) still
  matches. Pinned in `_FULL_RUNS`, no new code needed. Wrote the owner referral for
  the genuinely unclosable part (`--noconftest` itself, and a future `pytest11`
  bypass) into PLAN.md's "Owner referral (Round 10)" section -- not accepted as a
  residual.
- `9e1737a3d` **M1**: `unseen_policy` (`advisory` default / `deny`) and
  `unseen_sink_description` are now handler options instead of hardcoded text; every
  "guarantee" claim in shared code (`_RULE.verbose`, `get_claude_md`, `handle()`) is
  now "backstop", and the advisory never claims a sink a client project does not have.
  This repo's own config sets an honest, limits-included description. Also wrote up
  the `perl`/`node`-get-no-advisory-at-all gap as a second, separate owner referral
  (a parser-scope change, not a wording fix).

Also committed two stray uncommitted files left by prior rounds (`144ec6c9b`): the
round 9d fix report and review 10's own report.

## Verified

Targeted pytest + ruff + mypy + pyright + black on every touched file, all green.
Full `tests/unit/qa/`, `tests/unit/scripts/test_acquire_full_qa_lock_bash.py`, both
`test_subagent_full_qa_blocker*.py`, and the two integration pins ran clean (1077,
1267, and 5/5 passed across the separate runs; a combined final re-run across all of
them was still in flight when I stopped -- see note below). No new QA suppressions or
exclusions; a genuine repo-audit finding (`test_audit_capture_corruption.py`) was
fixed at the site, not excluded. Daemon restarted and verified RUNNING before every
src/-touching commit.

## Left for the next round

- The two owner referrals in PLAN.md's "Owner referral (Round 10)" section need a
  coordinator/owner decision, not more code from a fix round:
  1. `--noconftest` (and a future `pytest11` entry point's own disabling shapes)
     cannot be closed from inside the checked process.
  2. `perl`/`node`/other unlisted interpreters get a silent ALLOW with no advisory at
     all (`find_full_qa_invocation` returns `None`, never reaching the UNSEEN path) --
     a parser-scope widening, not covered here.
- I started a final combined re-run of every touched test file together
  (`untracked/scratch/p10_final2.txt` in this worktree) as a last sanity check after
  all nine commits; it had not finished when I wrote this report. Every constituent
  suite passed individually in earlier runs this round, so I don't expect a surprise,
  but the next agent (or the coordinator) should check that file's tail before relying
  on it.
