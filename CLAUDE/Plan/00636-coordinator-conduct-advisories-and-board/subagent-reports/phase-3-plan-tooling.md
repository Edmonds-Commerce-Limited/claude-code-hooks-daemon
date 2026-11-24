# Plan 00636 Phase 3: plan tooling report

All three tasks done; none skipped (none needed a seat, owner decision or pingbus feature).

- Task 3.1: `mkplan.bash --journal` accepts `NNNNN-slug`, `N-slug` and a trailing slash. A slug must match a real folder exactly (a nonexistent one is refused, writing nothing). Bare numbers unchanged.
- Task 3.2: the synopsis (top-level `--help` and `--journal` usage) is built from `JOURNAL_CATEGORIES` and states the `--ref` forms for a correction.
- Task 3.3: `find_plans(..., search_body=True)` and `bin/hooks-daemon find-plan --body`; archives included, unreadable file does not abort the search.

Each started red: the new tests in `tests/unit/scripts/test_mkplan_journal_ergonomics.py` and `tests/unit/test_plan_finder_body.py` failed before the change. A mid-way red also caught a real bug (a wrong slug created a folder entry through an unmatched nullglob candidate), fixed with a directory check.

Backward compatibility: plan creation, bare-number `--journal`, correction with and without `--ref` are tested in the new file. The deployed script and the bundled template are byte-identical. Shellcheck clean; black and ruff clean.

Targeted tests: tests/unit/scripts, test_plan_finder\*.py, test_plan_journal_guard.py, tests/unit/install/test_plan_workflow.py: 983 passed. The old synopsis assertion in `test_mkplan_journal.py` was updated to the new wording.

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/094-mkplan-journal-folder-name-and-find-plan-body.md`.
