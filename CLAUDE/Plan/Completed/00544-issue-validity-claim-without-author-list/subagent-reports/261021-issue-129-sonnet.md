# Issue #129 report (Sonnet)

No disagreement with the brief; the change is right.

## Red (before the fix)

Four new tests failed with `assert 4 == 0` (EXIT_USAGE returned for claim and for plain check with no list, `None` and `()`): 4 failed, 28 passed. The `--list-eligible` refusal test and the unapproved-author-blocks-claim test already existed and stayed green throughout.

## Changes

- `src/claude_code_hooks_daemon/daemon/issue_validity_cli.py`: the not-configured refusal now sits under `if list_eligible:` only (message reworded to "refusing to list eligible issues"). Single-issue paths proceed; the existing `AuthorWhitelistCheck` already prints `[n/a] author: no approved issue authors configured`. Docstring updated.
- `tests/unit/daemon/test_issue_validity_cli.py`: the old "refuses to judge" test replaced by claim-without-list (exit 0, exactly one assign call, n/a line) and plain-check-without-list tests.
- `CLAUDE/development/IssueSdlc.md`: states the single-issue behaviour.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/010-...` (highest present was 007; 008 and 009 reserved elsewhere).
- The v3.69.0 release note 029 is a released historical note, left unchanged. The CLI help text did not state the old behaviour.

## Green

`tests/unit/daemon/test_issue_validity_cli.py`: 32 passed.

## QA (`llm_qa.py changed --allow-unmapped`, full output in untracked/scratch/qa-129.txt)

37/40 passed, 1 failed, 2 not meaningful. The sole failure is docs_qa `duplicate-block` (advise, 0 block) in `CLAUDE/Plan/00529-.../JOURNAL/00529-Journal-26-10-21.md`, a file this branch does not touch (the N524 item in Plan 00474, fixed in Plan 00543). It made `project_handlers` and `changed_tests` report "not meaningful" by the wrapper's rule, though both show 0 failures (84 passed in changed_tests). Everything else, including pyright, type_check, lint, format and plan_qa, is green.
