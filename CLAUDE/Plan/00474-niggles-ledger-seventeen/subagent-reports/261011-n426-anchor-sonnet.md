# N426 report: anchor the ten GENUINE_REASON_ABOVE suppressions, map their files to the test

Plan 00474, niggle N426. Branch worktree-n426-suppression-anchor.

## Remedy 1: line-drift-proof anchors

`GENUINE_REASON_ABOVE` in `tests/unit/qa/test_check_inline_suppressions.py` rows are now
`(path, directive comment stripped, occurrence index from 0)`. The comment text is built from the
existing `NOSEC` / `SHELLCHECK` constants, so no literal directive appears in the file.

- `_anchored_line()` resolves the anchor to a line at test time and asserts (fails, never skips)
  when the requested occurrence does not exist, naming the count that matched.
- Repeated comments are disambiguated by the occurrence index: init.sh SC2317 (0, 1) and
  venv.sh SC1090 (0, 1). The others are unique in their file today.
- Verified by script that each of the ten anchors resolves to exactly the line the old number
  pointed at (9289, 1228, 2653, 2763, 356, 532, 91, 31, 37, 158).
- The assertions about each suppression are unchanged (is a directive, reason not on its own line,
  `judge_comments` clean).
- New tests: anchor drift fails loudly (zero matches and a missing occurrence); the ten anchors
  resolve to ten distinct lines.

## Remedy 2: changed_tests map

`scripts/qa/changed_tests_map.yaml`: six `glob` rules (one per file named: claude-supervise.py,
init.sh, scripts/install/venv.sh, constants/paths.py, install/transport_toggle.py,
install/transport_verify.py), each running `tests/unit/qa/test_check_inline_suppressions.py`.
Rules are additive, so they sit beside the existing `*.sh` shell_check rule with no conflict.
New test `test_a_change_to_any_anchored_file_selects_this_test` fails if a file in
`GENUINE_REASON_ABOVE` has no such rule, so a future row cannot be added unmapped.

## Verification

Targeted only: `test_check_inline_suppressions.py` and `test_run_changed_tests.py` (which validates
the map): 212 passed. black --target-version py311 unchanged, mypy clean, ruff clean.
