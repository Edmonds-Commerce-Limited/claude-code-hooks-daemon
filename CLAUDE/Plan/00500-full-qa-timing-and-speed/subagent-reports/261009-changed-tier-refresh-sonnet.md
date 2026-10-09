# Changed-tier shard reach: refresh onto main

- Merged `main` into `agent-ac60dcdb33334a059-ef11a181` with `--no-ff`: no conflicts (merge commit 27dcd0f03).
- PLAN.md: added Task 2.5 under Phase 2, marked done, merge hash left for the coordinator.
- Tests (branch venv, `src` imported from the worktree): 4378 passed across tests/unit/qa/ and every test file
  referencing `run_changed_tests`, `llm_qa`, `shard_reach` or `test_shards`.
- Checkers: `audit_error_hiding.py` rc 0, `check_magic_values.py` rc 0, ruff check clean, black --check clean,
  mypy clean on the changed files, bandit (`-s B101`, project invocation) clean on `shard_reach.py`.
  Bandit on `scripts/qa/*.py` with no skips reports only the B404/B603/B607 subprocess lows the project does not scan.
- Generated-docs drift: not run, the branch touches no handler guidance.
- `llm_qa.py` was not run.
