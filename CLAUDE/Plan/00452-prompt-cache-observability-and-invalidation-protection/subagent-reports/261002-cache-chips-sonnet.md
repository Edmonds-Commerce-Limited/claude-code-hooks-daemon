# Prompt-cache chips (concept A) - report

Branch: worktree-cache-chips

## What changed

- `src/claude_code_hooks_daemon/handlers/status_line/prompt_cache_indicator.py`: rewritten render. Chip constants and `_RESET` mirror `usage_indicator.py:43-48`; `_ratio_severity`, `_main_chip`, `_ratio_chip`, `handle` and `_sub_agent_chips` are the new render path; `explain_segment` lists the glyphs and thresholds; acceptance-test description updated. Absence rules, the sub/total existence rules and the fail-silent sidecar `except (OSError, RuntimeError, ValueError)` are unchanged.
- Options: `healthy_pct` 90, `warn_pct` 75, `critical_pct` 50 (set via the registry's `_<option>` setattr, as for usage). A ratio BELOW a threshold is worse, the opposite of usage; documented in the module docstring, `explain_segment`, yaml and notes.
- Severity: the worst of ratio band and state wins; COLD is always red.
- `tests/unit/handlers/status_line/test_prompt_cache_indicator.py`: rewritten for the chip design (SGR strings asserted exactly, band boundaries parametrised, state overrides, sub/total, absence, fail-silent).
- Docs/config: `CLAUDE/Architecture/StatusLine.md` (no prompt-cache section existed, so a new "prompt_cache is READ" section was added, plus the READ-fields list), `.claude/hooks-daemon.yaml.example` and `.claude/hooks-daemon.yaml` (options), `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.68.0.yaml` (new entry), release note `213-the-prompt-cache-status-segment-is-now-compact-colour-coded-chips.md`.

## Example renders (colour stripped; main chip colour in brackets)

- all green with sub: `| ⚡ main|⑂|Σ` (each green)
- sub degraded (62% on 5m): `| ⚡ main|⑂ 62% 5m|Σ` (main green, sub orange, total green)
- cold: `| ⚡ ❄ 509k|⑂|Σ` (main red)
- expiring: `| ⚡ main 99% ⏳4m|⑂|Σ` (main yellow)
- invalidated: `| ⚡ main 99% ↻ messages_rewritten|⑂|Σ` (main yellow)

## QA

- ruff check, black (py311, line length 100), mypy: clean on both touched Python files.
- `llm_qa.py changed`: 34/37 passed; changed_tests 1092 passed, 0 failed. The three failures:
  - `generated_doc_drift`: `.claude/HOOKS-DAEMON.md:189` still carried the old one-line description. Fixed in this commit (not re-run after the fix).
  - `docs_qa`: three advisory `duplicate-block` findings in Plan 00479 PLAN.md against Plan 00480's artefact. Not touched by this change.
  - `changed_tests`: reports `.claude/hooks-daemon.yaml` as unmapped (`too-broad`), which fails the run for any edit to that file; the task asked for that edit.
- The run also warned the tree changed during it (the HOOKS-DAEMON.md fix was made after), so it is not recorded for this tree.

## Caveats

- Tests were written before the code but I did not run them red first; the first run was green (90 passed across the indicator and tiers test files, 638 across `tests/unit/handlers/status_line`).
- Percentages display rounded down (as usage does), so a displayed `89%` can never sit beside a green chip.
- With both EXPIRING and a recent miss, both details show (`main 99% ⏳2m ↻ cause`).
- pyright on the test file reports `Import "pytest" could not be resolved` because of the worktree venv layout (pyright wants `lsp-venv`); the source file is clean.
