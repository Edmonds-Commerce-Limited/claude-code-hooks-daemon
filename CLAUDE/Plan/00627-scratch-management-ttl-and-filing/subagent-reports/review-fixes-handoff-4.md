# PR 251 security-review fixes: handoff 4 (wind-down)

Branch `plan-00635-host-seat-lane-guard`. Review: `261124-pr251-security-review-opus.md` (this folder).

## Done (pushed)

- **F1 + F2 (code, test-first)**: commit a6b78b068. `resume_claimed` accepts only the record whose `archive_id` the LAST-appended covering claim event named (append order, no clock). The `packed_at` filter and `_first_claim_at` are gone. Test helpers now pack under the claim's id (`_claimed_id`); `_adopted` claims with the adopted id. Three new tests were RED before the fix and pass after it. Targeted suites: 679 passed, 5 skipped. black, ruff, mypy, cold import, invariant pairs, the error-hiding audit and the tests/unit/qa subset were all clean.
- **F3**: filed as NIGGLES N736. The mount-namespace limit is added to the DESIGN.md open-file row. Not fixed, by instruction.
- **Ledger**: N733 closed on the reviewer's F4 probe.
- **Release note 106**: the resume paragraph is reworded to describe the id binding. Number 106 does not clash with main (which ends at 105) or with the open PRs (#251, #220).
- **Review report**: filed as `subagent-reports/261124-pr251-security-review-opus.md`. Commit abf790945.
- **PR #251 body**: updated with F1/F2 fixed, the F3 limit, and N733 closed.

## Mid-way (parked)

The brief's clause "claim cannot be matched to the archive -> STUCK, never rename back" is not yet implemented for adopt.

- The test `TestAdoptedArchives::test_a_claim_naming_another_archive_than_the_adopted_one_is_stuck` is committed as `xfail(strict=True)`. It covers an adopted record, then a claim with a fresh id, then a partial removal, then a resume. The resume currently returns `renamed-back` and should return `stuck`.

## Next steps

1. In `resume_claimed`, when no candidate verifies and any EXCLUDED record (same checkout, names the entry, other id) carries `ADOPT_PROOF` in `proof_ids`, return `stuck` and never rename back. Do not make every excluded record mean `stuck`: the F1 tests, the N733 test and `test_an_older_record_of_the_same_name_does_not_authorise` must stay `renamed-back`.
2. Remove the xfail marker, then rerun the targeted suites and black, ruff and mypy.
3. Look for an apply-level test (`test_scratch_archive_apply.py`) that crashes after the append and then resumes to removal through `apply_sweep`. If there is none, add one.
4. Docs:
   - Add the adopt claim-id rule to the DESIGN.md adopt row (the "crash between the adopt move" row).
   - Search DESIGN.md case-insensitively for "packed after", "earliest" and "leftover claim" and correct any time-filter wording.
   - Run the release-note shape test on note 106.
   - Confirm `run_changed_tests.py` maps `scratch_archive_remove.py`.
   - Check whether the ledger has a tally that needs N733 and N736.
5. Update the PR #251 body to cover the adopt STUCK rule.

The batch path (`pack_batch`) records no claim event: only `scratch_archive_apply.py` calls `record_claim`. Batch has no production caller, so it was left as is.
