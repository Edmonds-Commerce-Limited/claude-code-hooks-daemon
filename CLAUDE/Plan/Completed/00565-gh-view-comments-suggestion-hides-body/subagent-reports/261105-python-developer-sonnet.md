# Plan 00565 report: python-developer (Sonnet)

## Change

- `utils/gh_view_comments.suggest_with_comments(command, view, noun)` now takes the noun. A bare view gains
  `--json <fields>`; a `--json` list still gains `,comments`; a bare `--json` with no value gains the field list.
  Unknown noun raises `ValueError`. `--comments` is never suggested.
- Field lists (one dict, single source): issue `title,body,state,comments`; PR `title,body,state,author,comments`.
  Justification: title/body/comments are required; `state` (and a PR's `author`) is what the interactive view shows
  and costs nothing. `reviews`, `files` and the like were left out as heavy and not what the guard is about.
- Both handlers: REQUIRED ACTION text says `--comments` alone omits the body when output is not a terminal; the Rule
  `fix` line changed; `get_claude_md()` recommends the `--json` form and carries the warning. The fallback branch
  now calls the helper too. Matching and blocking are untouched; `--comments` is still allowed.
- Acceptance tests unchanged: their patterns (`BLOCKED`, `--comments`) still match, since the deny text names
  `--comments` in the warning.
- Callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/001-gh-view-suggests-json-body-and-comments.md`.

## TDD (red first, commit 17c3bab80)

Red run of the four test files before the fix: `27 failed, 96 passed`. Examples:
`TypeError: suggest_with_comments() takes 2 positional arguments but 3 were given` (9, util tests);
`AssertionError: assert 'gh issue view 123 --json title,body,state,comments' ...` (handler tests);
`assert 'omits the body' in 'BLOCKED [R-GH-ISSUE-VIEW-NO-COMMENTS]: ...'` (deny text and claude_md, both nouns).
Green: those four files plus the integration workflow and comment-splitting tests, 430 passed.

## QA (targeted, `llm_qa.py changed`)

39/42 passed. Remaining items and their disposition:

- `format`: one test file (test_gh_pr_comments.py) needed black; fixed by the autofix that ran, committed.
  `llm_qa.py format` now passes.
- `changed_tests`: 2621 passed, 1 failed. The failure was
  `test_safety_handlers_hostile_input_performance.py::...[whitespace_run]`, a timing test; run alone it passes
  (43 passed). The host was heavily loaded (the QA run took 1948s).
- `changed_tests` also reports the two handler files as unmapped `[too-broad]` (more referring tests than
  `MAX_IMPORT_SELECTION`). This needs `--allow-unmapped` and the coordinator's full gate; I did not run the full
  suite. The tests that name the handlers directly were run and pass.
- `project_handlers` was marked not meaningful only because `format` failed during that run.

## Disagreement

None with the approach. Note: `suggest_with_comments` gained a required positional parameter; it has no other callers.
