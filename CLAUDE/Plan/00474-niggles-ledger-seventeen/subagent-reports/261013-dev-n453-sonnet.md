# N453: check.md source drift

Plan 00474, ledger entry N453.

## Defect

`tests/integration/test_deployed_skill_trees.py` failed with `hooks-daemon/check.md (contents differ)`. Line 46 of the source page still carried the pre-N439 OK text.

## Evidence

- Code (`src/claude_code_hooks_daemon/handlers/session_start/optimal_config_checker.py`, line 290) prints "no model has an explicit effort level, so each runs at its own default". The deployed page was correct; the source was stale.
- Red before: 1 failed, 4 passed.
- Fix: source `src/claude_code_hooks_daemon/skills/hooks-daemon/check.md` line 46 now identical to the deployed `.claude/skills/hooks-daemon/check.md`.
- Green after: 5 passed.
- `./scripts/qa/llm_qa.py changed`: `QA: 40/40 PASSED` (changed_tests: 51 passed, 0 failed).

No release note added (unreleased N439 change, per instruction).
