# Usage chips always show the percentage (5h10%)

Owner request: "for usage - i think we can bring in percent numbers, i want to see them / 5h10% 7d5% its only a few extra chars and it helps / we can allow them to be spaced more when they go yellow though".

## Change

`UsageIndicatorHandler._chip` in `src/claude_code_hooks_daemon/handlers/status_line/usage_indicator.py`:

- Below `warn_pct`: `5h10%` (label, then floored percentage and `%`, no space, no countdown), still green.
- At or above `warn_pct`: unchanged, `5h 67% 3h 20m`.

Module docstring, `explain_segment` (`how_to_read`), the acceptance-test description, `CLAUDE/Architecture/StatusLine.md`, release note `211-...` and `config-changes/v3.68.0.yaml` now describe the new format. `docs/guides/CONFIGURATION.md` mentions only the ceiling segment, so it needed no change.

## Separator choice

Kept `|` between chips (`📈 5h10%|7d5%`). The owner's example used a space, but the existing tests deliberately assert the `|` separator and that it carries no background (`test_the_separator_carries_no_background`), and the docs everywhere describe `|`. Nothing indicated a space was clearly intended in the segment, so the example was read as shorthand. Switching is a one-constant change (`_SEPARATOR`) if the owner wants it.

## TDD

Tests changed first in `tests/unit/handlers/status_line/test_usage_indicator.py`: green renders now `5h13%|7d3%`, `7d42%`, ceiling case `5h13%|7d3% ⛔ 80%`, `7d` threshold option case `7d3%`; added parametrised below-warn cases (0 -> `5h0%`, 9.9 -> `5h9%`, 59.9 -> `5h59%`) and an at-warn spaced case (`5h 60% 3h 0m`).

Red (before implementation): `10 failed, 48 passed` in test_usage_indicator.py.

Green (after): `tests/unit/handlers/status_line/` 658 passed.

## Static checks

ruff clean, black --target-version py311 clean, mypy on usage_indicator.py clean, `run_pyright_check.py --json` 0 errors 0 warnings, `check_generated_doc_drift.py` no drift.
