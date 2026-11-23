# Stop-guard handoff 5: fixing the PR 226 review (after F2-F5)

Continues `261123-stop-guard-handoff-4.md`. The "Decided design" section of handoff 3 is still
authoritative for F6-F9. The worktree is `.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`, on
branch `plan-00636-stop-guard`, which is pushed. Python:
`untracked/venv-workspace_claude_worktrees_agent-a6d-7f9b-py313-0d6d49c6/bin/python` with
`PYTHONPATH=src` and `nice -n 19`. Run targeted tests only.

## Done this session (each fix was test-first, then committed and pushed)

- **F3** (d48de45f2): only the guard's own refusal earns the re-entry pass.
  - New helper `stop_hook_helpers.recent_stop_hook_block_texts(path, lookback)`.
  - The pass is granted only when the rule id appears in any block within the last 200 lines. A
    deny by another handler, or a spurious `stop_hook_active`, is evaluated afresh.
  - An unreadable or raising re-entry check stands down (N411).
  - A re-entered stop never repeats the `auto` advisory. The advisory is an ALLOW with context,
    so repeating it would loop.
- **F2** (79d8bd2ac): wider waiting detection in `_WAITING_RE`.
  - It searches all declaring text after the first `STOPPING BECAUSE:`, with quoted spans blanked.
  - New wordings: blocked on, pending, need X to, X must answer, until X decides, and a named
    person (`@handle` or a capitalised name).
  - A negation at the end of the match's own clause cancels it.
  - Tests pin the review's 8 probe rows, plus near-misses (`waiting on CI`, `pending QA`).
  - An unreadable transcript, when not a re-entry, is now treated as an unconfirmed wait for each
    armed team, under the bus policy, without reading the bus.
- **F4** (a4baf26b3): an unknown role, or an unresolved probe, keeps the guard armed.
  - These become `_Unconfirmed` under the policy, with no bus read.
  - An unresolved probe uses the `owner_wait_bus.TEAM_PLACEHOLDER` (`<team>`) template.
  - A declared other role, no team (ABSENT) and a sub-agent are still left untouched.
- **F5** (03ecd2701): `handle()` wraps `_check()`.
  - Any exception on a stop for an armed coordinator, or one whose seat state is unreadable,
    DENIES with the static `_FAIL_CLOSED_REASON`, sent `under_rule`, whatever the policy says.
  - A declared worker is allowed.
  - A fault in `matches()` returns True so that `handle()` decides.
  - The reason in `test_pretooluse_fail_closed_tagging.py` is updated.

All targeted runs were green: the guard, `stop_hook_helpers`, `owner_wait_bus`, stand-in
cooperation, stop-chain shadowing, guidance coverage, `auto_continue_stop`, fail-closed tagging,
ruff, black and mypy.

## Left

1. **The LOW findings F6-F9**, designed in handoff 3. For each: red test first, then commit and push.
   - F6: `bump_command` adds `--team`.
   - F7: strip thread-id shapes and stopwords from the boilerplate filter. `bump Q61` and
     `still waiting on @owner` must not count.
   - F8: make `started_at` required, and document it in seconds (Matrix milliseconds must be
     converted).
   - F9: check `ModeLabel.AWAITING_HUMAN` only, not `is_blocked`. This is in `_waiting()`.
2. **Docs.**
   - Do everything in handoff 4 "Left" item 2: HANDLER_REFERENCE (still says default `refuse`),
     CONFIGURATION, release note 026, `config-changes/v3.77.0.yaml`, and PLAN.md / DESIGN.md 20.1
     plus the OPEN point.
   - Also document F2-F5 there:
     - wider wording detection;
     - an unreadable stop or role, or an unresolved probe, counts as unconfirmed;
     - only the guard's own re-entry passes;
     - a fault fails closed.
   - Regenerate HOOKS-DAEMON.md and the CLAUDE.md block, since `get_claude_md` changed.
3. **Journal** via `mkplan.bash --journal`.
4. **Light QA**: targeted tests, stop-chain shadowing, response validation, `tests/unit/config`,
   ruff, black and mypy.
5. **Push and comment on PR 226**, listing F1-F5 with their commits.
