# PR 251 security-review fixes: handoff 5

Branch `plan-00635-host-seat-lane-guard`. Supersedes `review-fixes-handoff-4.md`.

## Update after the later independent review (S1 to S3)

- The adopt-STUCK branch described in the first bullets below was REMOVED: it stranded intact trees and hid new folders sharing an adopted entry's name, and nothing in `src/` calls `adopt()`. `resume_claimed` now binds only to the id the latest claim names; both cases give `renamed-back` (two new tests, red first). The old strict test was replaced by them. Niggle N737 records that adopt claim-id binding must be enforced where adoption is wired.
- The evacuation gate now calls `refuse_unrestorable` (xattr/sparse entries block the whole worktree), test-first.
- `resume_claimed` docstring rewrapped; the xattr refusal names `/proc`.
- origin/main (PR 256) is merged. Report: `pr251-review-fixes-report.md`.

## Done (superseded where noted above)

- `resume_claimed` (`core/scratch_archive_remove.py`): SUPERSEDED, see the update above (the adopt STUCK branch no longer exists).
- `TestAdoptedArchives::test_a_claim_naming_another_archive_than_the_adopted_one_is_stuck`: SUPERSEDED, replaced by two renamed-back tests.
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
