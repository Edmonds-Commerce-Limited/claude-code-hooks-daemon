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

## Round 2 (review fixes)

The pattern-compilation bullet above is superseded: the accessor is now two functions in `sensitive_content.py`,
strict `compile_public_pattern` (raises `re.error`) and the guard's lenient `compiled_public_pattern` built on it.

1. Fail-open: `_capture_value_swapper` compiles with the strict function and refuses (`_ContentGuardUnavailableError`,
   "nothing was written", exit 1, no traceback) when any pattern for a registry kind does not compile. Tests: broken
   alone, first and second; nothing written; no `Traceback`; a broken pattern for an unlisted kind is ignored.
2. The weak test is replaced by one that monkeypatches `compile_public_pattern` and asserts the swapper calls it.
3. Same-name patterns: `swap_unlisted_fakes` takes a sequence of regexes per kind; the CLI keeps every pattern. Tests:
   two valid patterns in both orders (CLI) and a unit test. The coordinator asked for the broken entry second as well
   as first; with item 1 a broken entry refuses in either position, so that is what the parametrised test pins.
4. `mkplan.bash` collision scan removed (the counter is at least `filesystem_highest`, so it was redundant and used
   another rule); test for a plan nested in a numbered folder. Both copies edited.
5. Comment now says `filesystem_highest` in both copies.
6. The guard skips a non-mapping entry with a logged warning (no `validate_options` on this handler).

TDD note: for items 1, 2, 3 and 6 the source was written before the new tests were run, so only item 4's test was seen
red (the reviewer already ran the item 1 and 6 probes against the old code). All new tests pass now.

## Checks

- Targeted run: 615 passed (remote_docs, test_release_slate, test_cli_release_slate_check, the three mk\* script tests
  plus the two new ones, test_sensitive_content). Earlier scripts run: 84 passed.
- black, ruff, mypy clean on touched files. pyright: only unresolved-import errors (pydantic, pytest) because this
  worktree has no venv of its own; nothing else reported. Tests ran with the main venv and `PYTHONPATH` at this
  worktree's `src`.
