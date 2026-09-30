NOT READY

# N47 fix round 6 verification (narrow), worktree HEAD `bcded377e`

Scope: only the two items team-lead asked for. Nothing tracked was changed;
all work happened in scratch trees under `/workspace/untracked/scratch/`
(`n47v6_archive` = `git archive bcded377e`, `n47v6_reverted` = the same with
finding 1's fix manually reverted, `n47v6_pre` = `git archive 35ea7b7bd`, the
pre-round-6 commit).

## Finding 1 (MAJOR) — CONFIRMED FIXED, RED-proven

Re-ran review 5's `probe_n47r5r_scenarios_test.py` (all 12 cases) and the two
new `test_manual_model_choice.py` tests against a fresh `git archive` of HEAD:
all pass (12 passed; 25 passed for the full `test_manual_model_choice.py`
file).

Reverted only the finding-1 line in the scratch copy (`family != ep_family`
back to `_family_rank(family) > _family_rank(ep_family)`, leaving every other
round-6 change — including the record-key rename — intact) and reran the same
tests: 4 failures, exactly the predicted shape —

- `test_a_human_pick_of_a_lower_family_closes_the_open_episode` and
  `..._is_never_reverted_once_backoff_expires`: `assert 'manual-sess-1:opus' is None` (episode never closes).
- `test_s1_human_picks_sonnet_during_a_delayed_episode`: `/model fable` typed
  at +300 over the human's Sonnet pick.
- `test_s1b_human_picks_sonnet_while_backoff_holds_second_episode`: `/model fable` typed at +3600 over the human's Sonnet pick — the exact field defect
  quoted in review 5 item 1 ("the supervisor reverts the human's Sonnet pick
  45 minutes after they made it").

This is a clean RED/GREEN pair on the reviewer's own reproduction. Finding 1
is fixed and the fix is what closes it (not some other change in the round).

## Finding 2 (MINOR) — fix works, but ships with NO regression test

Ran review 5's S2, S4, S5 probes against `git archive 35ea7b7bd` (review 5's
own commit, i.e. genuinely pre-round-6, not just pre-finding-1-revert): all
three fail, reproducing review 5's exact output (`/model fable@+200` for S2,
`@+3620` for S4, `@+3600` for S5). Ran the same three against the fixed HEAD
archive: all three pass. So the direction is right — S2/S4/S5 were wrong
before this round's fix and right after.

But: `git diff 35ea7b7bd..HEAD --stat` shows round 6 added tests only to
`tests/unit/supervise/test_attributed_downgrade.py` (2 tests — window-bound
and `settle_never_overwrites`, both finding 4/W1 and S2, not finding 2),
`test_manual_model_choice.py` (finding 1's 2 tests, above),
`test_model_fallback_records.py` (finding 4's D1/D2 pair-window tests), and
`test_optimal_config_checker.py`/`test_no_effort_injection.py` (finding 3).
**No committed test references `_last_top_family_seen_session`,
`_last_top_family_seen_ts`, or exercises the supersede path at all.** Grepping
the shipped `test_attributed_downgrade.py` for that mechanism turns up
nothing.

Confirmed directly: I took the round-6-only diff of every touched test file
and found no test added for finding 2. The fixer's report's own words —
"findings 2 and 4's tests pass unchanged against the pre-fix tree ... no bug
there, only missing coverage" — undersell what's missing for finding 2
specifically: finding 4's six tests DO pin real (if narrow) behaviour; finding
2 has zero committed tests of any kind, pre- or post-fix. The only evidence
the fix works is the reviewer's own untracked probe script, which is not part
of the suite and will not catch a regression.

**This is the finding team-lead asked me to surface**: the supersede
mechanism (`_last_top_family_seen_session`/`_ts`,
`_DOWNGRADE_SUPERSEDE_SKEW_SECONDS`) that fixes S2/S4/S5 has no regression
test in the repo. A future refactor of `_downgrade_is_attributed` or
`note_model_reading`'s top-family tracking could silently reintroduce the
bug and nothing in `tests/unit/supervise/` would catch it.

## Verdict

NOT READY to merge as-is on finding 2's test-coverage gap alone (finding 1 is
solid). Direction: add S2/S4/S5 (or equivalent) as committed tests in
`test_attributed_downgrade.py`, asserting on `_last_top_family_seen_*` state
or on the typed-command sequence the way `test_manual_model_choice.py` does
for finding 1.

No gate was run (per brief: narrow verification only).
