# PR 251 security-review fixes: handoff 5

Branch `plan-00635-host-seat-lane-guard`. Supersedes `review-fixes-handoff-4.md`.

## Done

- `resume_claimed` (`core/scratch_archive_remove.py`): when no candidate verifies and an excluded record of the entry (same checkout, other id) carries the adopt proof, it returns `stuck` and never renames back. Other excluded records still mean `renamed-back`.
- `TestAdoptedArchives::test_a_claim_naming_another_archive_than_the_adopted_one_is_stuck` is no longer xfail and passes.
- `test_scratch_archive_apply.py`: `test_a_crash_after_the_record_append_resumes_to_removal`. It passed on first run (the F1 fix already covered the path), so it is a regression pin, not red-first.
- Fixed a pre-existing mypy error in the apply test (`expired_ids` imported from its defining module).
- DESIGN.md adopt row carries the adopt claim-id rule. No "packed after", "earliest" or "leftover claim" wording was in DESIGN.md.
- Release note 106 mentions the adopt STUCK rule; the release-note shape tests pass.
- `run_changed_tests.py --select-only` maps `scratch_archive_remove.py` to `test_scratch_archive_remove.py`.
- The niggles ledger has no tally to update for N733 or N736.
- PR 251 body updated with the adopt STUCK rule.

## Remains

- The full QA gate is the coordinator's. PR 251 CI QA also fails on two magic-timeout literals on main (fixed in PR 256).
- The batch path (`pack_batch`) records no claim event and has no production caller; left as is.
