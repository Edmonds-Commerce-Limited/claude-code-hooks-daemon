# Changed-tier shard reach: refresh onto main, then review round 1

- Merged `main` into the branch with `--no-ff`: no conflicts (merge commit 27dcd0f03).
- Review round 1 (`261009-00500-task-2.5-review-r1-opus.md`, copied alongside) asked for the full import closure
  (B1, S1), the whole-suite triggers first (B3), a CI fallback that matches (B2) and derived floors (S2-S4).
- Failing tests first: the review's four cases (two-hop dependent, mirror hiding referrers, package `__init__`,
  whole-suite trigger over a named reference) failed on the branch. A transitive-closure `reach_tests` and a
  trigger-first check turned them green (121 tests in `test_run_changed_tests.py`). The review's `or` ordering
  raised IndexError once the file became unmapped, so the assertions read `unmapped or shard in shards`.
- Measurement (the full closure, real `test_shards.yaml` and reach declaration, 1,423 test files, every one of the
  3,770 tracked non-test files, one file per run):
  - All 3,770: 2,887 reach the whole suite, 883 a strict subset (of which 866 were already named on main).
  - The 2,833 files main sends to the whole suite: 2,816 still do, 17 (0.6%) narrow. Mean fraction of the suite
    selected 0.996. Python only (272): 17 narrow, mean 0.956. The 17 are near-empty package `__init__.py` files and
    test-local conftests.
  - The measurement took 610 s for 3,770 files with the old selector run beside it.
- Ruling 2 applies: narrowing saves under 10% of the tests for nearly every file it could touch, so it is not
  shipped. The feature code, declaration and tests were restored to main's content (`scripts/qa/run_changed_tests.py`,
  `scripts/qa/llm_qa.py`, `CLAUDE/QA.md`, their two test files) or removed (`shard_reach.py`,
  `changed_shard_reach.yaml`, `test_shard_reach.py`). PLAN.md Task 2.5 is marked declined with this evidence.
- B3 exists only in the declined build: `git show main:scripts/qa/run_changed_tests.py` has no `whole_suite` list.
  B2 is moot, since the CI fallback script and the local gate both still treat any unmapped file as the whole suite.
  S2-S4 concern code that no longer exists.
- `llm_qa.py` was not run.
