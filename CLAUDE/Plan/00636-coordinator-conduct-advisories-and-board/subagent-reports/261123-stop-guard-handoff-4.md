# Stop-guard handoff 4: fixing the PR 226 review (after F1 and `auto`)

Continues `261123-stop-guard-handoff-3.md` (read its "Decided design" for F2-F9; it stays
authoritative). Worktree `.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`, branch
`plan-00636-stop-guard`, pushed. Python:
`untracked/venv-workspace_claude_worktrees_agent-a6d-7f9b-py313-0d6d49c6/bin/python` with
`PYTHONPATH=src`, `nice -n 19`, targeted tests only.

## Done this session

- **F1** (c09194909): `utils/stand_in_cron.py` gains `stand_in_requirement(hook_input, *, config, delay_hours, now=None)`, `configured_delay_hours(config)` and `STAND_IN_DELAY_OPTION`.
  `auto_continue_stop._stand_in_block` calls it. The guard has a `_config_loader` seam (also feeds
  `_team_seat_config`; an unlocatable project root now falls back to defaults) and, on an
  `[awaiting-human]` non-synthetic stop, appends the stand-in reason to its deny under
  `ALSO REQUIRED BEFORE STOPPING AGAIN:`. `test_owner_wait_stand_in_cooperation.py` green; stop-chain
  shadowing test green.
- **`on_unreadable_bus: auto`** (a3f240fe4): values `auto | refuse | allow`, default `auto`.
  `auto` = refuse where `self._bus.flags_readable()` is True, else ALLOW with
  `BlockingResult.context` advisory (`_render_unchecked`: team, owner-started threads and open
  questions unchecked, both notify commands). The advisory is also appended to a deny when another
  team is stale. `flags_readable()` added to `OwnerWaitBus`; `TeamchatOwnerWaitBus` returns False;
  a raising probe = False. Invalid value falls back to `auto` (tests rewritten). The example yaml
  comment no longer says `refuse` (test pins it). A Stop ALLOW with context goes out once as
  `hookSpecificOutput.additionalContext` (`hook_result._format_stop_response`), which makes Claude
  Code continue one turn; the next stop is `stop_hook_active` and the guard stands down.

## Left

1. F3 (re-entry by own marker), F2 (widened waiting regexes, red test = review's 8 probe rows plus
   `not waiting on any user input`), F4 (`guards_armed`), F5 (fail closed on exceptions for an armed
   coordinator; update the reason in `tests/unit/handlers/test_pretooluse_fail_closed_tagging.py`,
   which now says `default auto`), F6-F9 LOW. Design per handoff 3. Red test first, commit and push
   each.
2. Docs: `docs/guides/HANDLER_REFERENCE.md` (~line 4860-4876 still says default `refuse` and shows a
   literal `refuse` example), CONFIGURATION, release note
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/026-...md` (says expect one refusal per stop: now only
   with a flag-reading adapter or explicit `refuse`), `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`
   (~line 249: values and default), `owner_wait_bus.py` docstring already updated, PLAN.md /
   DESIGN.md 20.1 and the OPEN point (coordinator chose `auto`, fail-open by design on v1, advisory
   its only effect there). Regenerate HOOKS-DAEMON.md and the CLAUDE.md block.
3. Journal via `mkplan.bash --journal`; light QA (targeted tests, stop-chain shadowing,
   response-validation, tests/unit/config, ruff, black, mypy); push; comment on PR 226.
