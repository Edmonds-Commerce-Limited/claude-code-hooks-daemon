# N450 (GitHub #103): a words-only full_qa_patterns entry judges operands as words

Branch `worktree-issue-103-words`. Plan 00474.

## Commits

One commit on the branch carrying the fix, tests, release note and this report (hash in the final reply; a report cannot name its own commit).

## Red first

New class `TestAWordsOnlyEntryJudgesOperandsAsWords` (12 cases). Before the fix: 4 failed, 8 passed. Failing: `php probe.php .`, `php probe.php ..`, `php probe.php <nested>`, `php probe.php --verbose .`. Run from the repository root as the working directory.

The first draft ran from a subdirectory (`vendor/`), where `.` is narrowed by the below-root rule and only 2 failed. The case was moved to the root so that `.` is a real reproduction.

## Tests added or changed

Added in `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py` (none changed):

- Words-only `php` entry with `full_words: [bin/qa]`, `read_only_flags: [-t]`. Not full: `.`, `..`, nested repo root (a directory holding `.git`, as the neighbouring tests build them), `--verbose .`, `<nested>/lib`, bare `php probe.php`, `php bin/qa -t stan`.
- `php bin/qa` is still full.
- Regression: the pytest whole-suite shape (`full_args: [tests, .]`, `bare_is_full`) still treats `.`, a repo root and bare as full.
- Regression: `full_args: []` with `full_words` keeps the path rules (`php probe.php .` full).
- Regression (follow-up commit, at the coordinator's request): the shipped `run-changed-tests` shape `{command: run_changed_tests.py, full_words: []}` is never full for no operand, `.` or a repo root. Kept safe by retaining the `frozenset()` coercion.
- Shipped `llm_qa.py all` is full, `llm_qa.py changed` is not.

## QA

- pytest on both handler test files: 1815 passed.
- `./scripts/qa/llm_qa.py changed`: all static checks green (lint, type_check, pyright, docs_qa, plan_qa, holding-area etc). `format` reported one file reformatted by black (auto-fixed, my test file); `black --check` on both touched files now passes. The `format` result is marked NOT RECORDED for the tree because the tree changed during the run.
- `changed_tests`: 4135 passed, 4 failed, 5 skipped. The 4 failures are in `tests/unit/handlers/test_safety_handlers_hostile_input_performance.py` (`TestCombinatorialSmallInputShapesStayLinear`, timing-ratio assertions on other handlers such as `write-protected-paths` and `block-sensitive-content`). Re-run alone, 2 different shapes failed (load average 12-17 from concurrent agents). They do not touch this handler; I read them as load-induced flakiness, not as caused by this change, but I did not prove that on a clean main under idle load.

## Implementation choice

Added a bool field `judges_operand_paths` (default True) to `FullQaPattern`, set in `_parse_entry` to `full_args declared or full_words absent`. `_add_path_operand` gates the `_operand_is_full` call on it. The `frozenset()` coercion stays, so every `full_args is None` and `full_args == frozenset()` use is untouched: the line `pattern.full_args is None` (every run full) cannot start firing for words-only entries, and the `full_words: []` never-full rule is unchanged. Dropping the coercion instead would have needed every one of those uses re-proved. The bare-run below-root check still calls `_operand_is_full` on `.`, so `bare_is_full` narrowing is unchanged. Path-like operands still count as targets via the `elif` branch.

Docs updated: `FullQaPattern` docstring and the handler guidance text ("An entry with `full_words` and no `full_args` judges operands as words only").

Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/050-words-only-full-qa-patterns-judge-operands-as-words.md`.

## Deviations

None from the ruling. The "nested git init repo" is built with a `.git` directory rather than running `git init`, matching the neighbouring tests; the marker lookup is the same.
