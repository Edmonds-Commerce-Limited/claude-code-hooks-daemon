## 09:22 · action · — — Targeted QA green

Targeted QA is green at 8e43489c0: `llm_qa.py changed --allow-unmapped` gave `QA: 43/43 PASSED`, with changed_tests at 10084 passed and 0 failed. The --allow-unmapped flag covers only files the tool classed as too-broad: `.claude/HOOKS-DAEMON.md`, `.claude/hooks-daemon.yaml`, `constants/handlers.py`, `constants/priority.py`, `constants/rule_ids.py`, `daemon/init_config.py`, `lint_on_edit.py`, `staged_lint_gate.py` and `handlers/session_start/__init__.py`. A whole-suite run must cover these. The only file it classed as uncovered was the staged truth-change. That file now has its own test (`tests/integration/test_unreleased_truth_changes_manifests.py`) and a map rule.

What remains: the coordinator's full gate and merge. The `<hooksdaemon>` rule row for R-STAGED-LINT-FAILURE in CLAUDE.md regenerates from the corrected Rule text on main.
