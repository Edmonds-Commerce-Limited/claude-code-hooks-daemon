# Batch Q report (N371 residuals, N374 cli.py pair)

## N371 scan depth

- `CLAUDE/Plan/mkplan.bash` `filesystem_highest` now uses a recursive `scan_plan_tree` applying the daemon's rule: a
  `NNNNN-name` folder holds its number and is not searched; every other folder is searched at any depth, dot-folders
  included (`dotglob`). The bundled template is a byte copy (parity test passes). The false "mirrors the daemon's"
  comment is replaced with the real rule and a pointer to the test.
- Test: `tests/unit/scripts/test_mkplan_scan_depth_parity.py`, seven shapes, runs `highest_plan_number` and the real
  script (counter 0) against one tree. Red first: 4 of 7 failed (year folder, three levels, dot folder, and a plan
  nested inside a numbered folder, which the old scan wrongly counted as 999).

## N371 mkroutine

- `mkroutine.bash` advances a lagging counter to the disk high-water mark with a note on stderr, as mkplan does. No
  bundled template copy of mkroutine exists. The two tests that asserted refusal were rewritten to assert the advance;
  a counter-ahead-of-disk test was added. Header comment item 5 updated. (The script was edited before its test was run
  red; the old refusal tests were the red evidence, and they pass only under the new behaviour.)

## N374

- `"completed"` literal: `CiRunState.is_completed` in `core/release_slate.py` uses the existing `_CI_COMPLETED`;
  `cli.py` calls it. Test in `tests/unit/core/test_release_slate.py`.
- Pattern compilation: `_compiled_public_pattern` became public `compiled_public_pattern` in `sensitive_content.py`
  (comment in `flaggable_content_channel_guard.py` updated); `_capture_value_swapper` uses it. A non-mapping
  `public_patterns` entry raises `_ContentGuardUnavailableError`. Tests:
  `tests/unit/remote_docs/test_cli_remote_docs_public_patterns.py` (bad regex dropped and capture succeeds; non-mapping
  entry refuses; shared accessor).

## Checks

- Targeted run: 615 passed (remote_docs, test_release_slate, test_cli_release_slate_check, the three mk\* script tests
  plus the two new ones, test_sensitive_content). Earlier scripts run: 84 passed.
- black, ruff, mypy clean on touched files. pyright: only unresolved-import errors (pydantic, pytest) because this
  worktree has no venv of its own; nothing else reported. Tests ran with the main venv and `PYTHONPATH` at this
  worktree's `src`.
