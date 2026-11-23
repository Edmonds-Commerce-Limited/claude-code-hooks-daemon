# Stop-guard handoff 6: PR 226 review fixes (after F6-F9 and most docs)

Continues `261123-stop-guard-handoff-5.md`. Same worktree, branch `plan-00636-stop-guard`, pushed.
Python: `untracked/venv-workspace_claude_worktrees_agent-a6d-7f9b-py313-0d6d49c6/bin/python`, with
`PYTHONPATH=src` and `nice -n 19`. Use `-o addopts=""` and grep the summary line, because piping
pytest to tail is blocked.

## Done this session (each was test-first, then committed and pushed)

- **F6** (2cd729efc): `bump_command` always names `--team` (shell-quoted, or the `<team>`
  placeholder). The unused `BUMP_ALL_WAITING` was removed.
- **F7** (0ae5a7f17): `has_meaningful_body` strips mentions and thread-id shapes. It then needs a
  word outside `BOILERPLATE_WORDS` (widened with chase and politeness words) and `STOPWORDS`.
- **F8** (99392a7b3): `OwnerThread.started_at` is a required keyword field. `OwnerThread` and
  `BusPost` docstrings state the unit is Unix seconds, and that Matrix ms must be divided by 1000.
- **F9** (d99eb2f57): `_waiting()` checks `ModeLabel.AWAITING_HUMAN in session_policy(...).labels`.
  `goal-blocked` alone is not a wait. Added `goal_blocked_entry` to `tests/support/autonomy.py`.
- **Docs** (8b0fd8816): `auto` is now the default in HANDLER_REFERENCE, the config-changes yaml,
  release note 026, 00630 DESIGN.md 20/20.1 and 00636 PLAN.md.
  - These docs note that on v1 the advisory costs one extra continue turn, and that an invalid
    value falls back to `auto` (this matches the code; the old docs said `refuse`).
  - F2-F5 are documented there too.
  - The OPEN point is settled.
  - Task 2.1b, the review fixes, was added and ticked.
- `docs/guides/CONFIGURATION.md` needed no change: it mentions the handler only in the priority
  table.

Targeted tests were green: `tests/unit/handlers/stop/`, `test_session_mode_readers`,
`test_owner_wait_bus`, `test_owner_wait_check`. Ruff, black and mypy are clean on the touched
files.

## Left

1. Check whether `get_claude_md` text in the guard mentions `refuse` as the default.
   - It is at line ~664 of `owner_wait_stop_guard.py`, and already says `auto`.
   - Run `tests/unit/handlers/test_claude_md_guidance_coverage.py` and the handler-reference
     coverage test.
   - If they need it, regenerate HOOKS-DAEMON.md and the CLAUDE.md block.
2. Journal via `CLAUDE/Plan/mkplan.bash --journal 00636 <category> <body-file>`, with the body in
   scratch. It should cover F6-F9 and the docs.
3. Light QA:
   - stop-chain shadowing, response-validation, `tests/unit/config` and
     `test_pretooluse_fail_closed_tagging`;
   - ruff, black and mypy on the changed src.
4. Comment on PR 226, listing F1-F9 with their commits:
   - c09194909 F1, 79d8bd2ac F2, d48de45f2 F3, a4baf26b3 F4, 03ecd2701 F5;
   - 2cd729efc F6, 0ae5a7f17 F7, 99392a7b3 F8, d99eb2f57 F9;
   - 8b0fd8816 for the docs.
