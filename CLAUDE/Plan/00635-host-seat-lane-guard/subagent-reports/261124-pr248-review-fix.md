# PR #248 review fixes (I1-I3, S1-S6)

Fixes for `subagent-reports/261124-review-pr-248.md` (in the main checkout; not on this branch). All changes were made test-first.

## Important

- **I1**: `_UNKNOWN_REFUSAL` now reads "the teamchat probe gave no answer, so the guard stays armed". It no longer claims a seat is held or a duty "cannot be read". `test_unknown_duty_refusal_never_claims_duty_host` asserts the new phrase and asserts that both old phrases are absent. The test's `_NO_ANSWER` probe was narrowed to `whoami probe gave no answer`, so it still tells the once-per-session note apart from the refusal.

- **I2**:

  - The comment in `utils/long_running_command.py` now says the lane guard keeps its own per-language copy, pinned by `test_registry.py` in both directions.
  - `test_registry.py` replaces the `BUILD_PATTERNS[1:]` slice with these named tuples and tests:
    - `_MIXED_SHARED_BUILD_PATTERN` and `_SHARED_BUILD_IN_LANE` are explicit. A test asserts that together they equal `BUILD_PATTERNS`, so reordering or adding to that tuple fails the test.
    - `_SHARED_IN_LANE` must all be in the lane. This is the existing direction.
    - New reverse direction: the lane set must equal `_SHARED_IN_LANE` plus an explicit `_LANE_ONLY_PATTERNS`, so a new strategy pattern has to be listed on purpose.

- **I3**: PLAN.md has a new Decision paragraph dated 2026-11-24. It records two things:

  - The arming ruling: only an explicit host duty arms the guard; a null, missing or unreadable duty leaves it silent; a probe that gives no answer keeps it armed.
  - The finding-2 re-scope: `npm t` and `pre-commit run` are closed; `docker exec`/`ssh` remain an owner question; everything else is won't-chase.

  Task 2.1 now names the strategy domain and marks the status of each finding-2 item. Finding 3 is still OPEN.

## Suggestions

- **S1**: `rspec` and `phpunit` now end on `(?=\s|$)`. New negative tests cover `rspec-x`, `bundle exec rspec-queue`, `phpunit-x` and `phpunit-watcher watch`.
- **S2**: Added `test_a_seat_resolved_earlier_is_armed_when_a_later_probe_gives_no_answer`. One resolver answers WORKER (silent), then UNRESOLVED (armed, DENY), and the test asserts that every call re-asks it. It is a handler-level test with a fake resolver, as the review suggested. Driving the real `SeatContextResolver` would need a trusted kit binary.
- **S3**: The handler's own acceptance test is now `nice -n 19 pytest tests/unit`, a wrapped form. The bare form stays the Python strategy's test. The `unseated` copy is gone: the handler imports `HARNESS_CANNOT_PRODUCE` from `common.py`, which was made public for this. New test: `test_no_acceptance_command_is_declared_twice`.
- **S4**: Release note 102 is reworded to describe current behaviour only. The before/after phrasing ("now", "newly", "no longer", "as before") is gone. It stays note 102, because the other open PRs already avoid that number.
- **S5**: Added `strategies/lane_commands/CLAUDE.md`, a pointer in the `lsp_noise` style. It covers what differs from TDD, the edit guards, the two-way pin and the `(?=\s|$)` rule. I checked that `qa/strategy_pattern_checker.py` scans this domain: it reports no violations here, and the 3 it reports elsewhere already existed.
- **S6**: Wrapped the long docstring line in `_verdict`.

None of the suggestions were skipped.

## Verification

- `black` and `ruff` are clean on the changed `.py` files.
- `generate-docs` was re-run. `.claude/HOOKS-DAEMON.md` did not change, because the refusal text is not part of the generated docs.
- Targeted tests: 5370 passed, 6 skipped. They cover:
  - the lane guard
  - `tests/unit/strategies`
  - `tests/unit/docs_qa` and `tests/unit/plan_qa`
  - `test_claude_md_guidance_coverage`
  - generated-docs path-agnostic and upgrade-regenerate
  - blocking-handler evasion and fail-closed tagging

The full QA gate was not run, as instructed.
