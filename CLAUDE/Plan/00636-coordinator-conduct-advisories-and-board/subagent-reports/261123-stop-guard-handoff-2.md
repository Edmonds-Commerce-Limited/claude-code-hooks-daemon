# Handoff 2: 00636 Task 2.1a owner-wait Stop guard (branch plan-00636-stop-guard)

Worktree: `/workspace/.claude/worktrees/agent-a6d1fc9ca72dfceff-148fd440`. Tools:
`PYTHONPATH=src nice -n 19 $(ls -d untracked/venv-*)/bin/<tool>`; targeted runs only; never pipe
pytest/mypy to head/tail (use `| grep -E "passed|failed|^FAILED"`). Read handoff 1 first
(`261123-stop-guard-handoff.md`); this one supersedes its "fails open" design.

## Done (pushed, head 13db500b3)

- `handlers/stop/owner_wait_stop_guard.py` written, all 41 handler tests + adapter tests green; ruff,
  black, mypy clean. Registered: `HandlerID.OWNER_WAIT_STOP_GUARD`, `Priority.OWNER_WAIT_STOP_GUARD = 3`,
  `RuleID.STOP_OWNER_WAIT_UNBUMPED`, `handlers/stop/__init__.py`; inventories in
  `test_session_mode_readers.py` (MODE_READERS) and `test_pretooluse_fail_closed_tagging.py` (audited).
- Design correction from the coordinator: option `on_unreadable_bus: refuse|allow` (handler option,
  `handlers.stop.owner_wait_stop_guard.options.on_unreadable_bus`; the brief wrote
  `owner_wait_guard.on_unreadable_bus`, read here as the handler option, same place as
  `window_minutes`). Default `refuse`: unreadable bus or a raising adapter on an APPLIES coordinator team
  denies, text names `pingbus thread --team <t> Q<n> --ask` and `--re <event id> --ask` (from the new
  adapter method `notify_commands`), says "stop again", says why (reason + "no notify flag or m.thread
  ... unverified here"), never restates waits. `allow` = fail open with WARNING. Invalid value -> refuse
  - WARNING. Re-entry (`stop_hook_active`) always allowed.

## Left (in order)

1. Config surfaces, mirroring `idle_workable_issue_stop_gate`: `.claude/hooks-daemon.yaml` (stop block,
   ~line 1441, priority 3), `.claude/hooks-daemon.yaml.example` (~1004, with commented options
   `window_minutes: 30`, `on_unreadable_bus: refuse`), `daemon/init_config.py` (~518 stop line).
   `docs/guides/HANDLER_REFERENCE.md` has no per-handler Stop sections for siblings (check what
   `tests/` demands; maybe generated). Priority 0-9 tables: `CLAUDE/HANDLER_DEVELOPMENT.md:553`,
   `CONTRIBUTING.md:248`, `docs/guides/CONFIGURATION.md:547` add `owner_wait_stop_guard`.
   `.claude/HOOKS-DAEMON.md` is generated (`bin/hooks-daemon generate-docs`), leave or regenerate.
2. Holding area: release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/020-...md` (format like 015),
   and add `handlers.stop.owner_wait_stop_guard` (+ `.options.window_minutes`, `.options.on_unreadable_bus`)
   to `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml` `added:`; update its header comment.
3. Targeted tests: `tests/integration/test_stop_chain_terminal_shadowing.py`,
   `tests/unit/handlers/test_all_handlers_response_validation.py` (find path), `tests/unit/config/`,
   anything asserting config/yaml/handler-count parity (grep tests for `idle_workable_issue_stop_gate`).
4. Plan: tick Task 2.1a; annotate 2.1 partly done (AskUserQuestion deny out of scope); fix "unreadable
   bus fails open" wording in Tasks 2.1/2.1a; add OPEN design point for coordinator/owner: on pingbus v1
   the default `refuse` refuses EVERY waiting coordinator stop once (adapter cannot read notify flag),
   until a v2 adapter reads the flags; `allow` is the escape hatch. Add a one-line correction pointer in
   00630 DESIGN.md 20 ("fails OPEN") and 20.1 ("unreadable-bus fail-open stands"). Journal via
   `CLAUDE/Plan/mkplan.bash --journal 00636 <category> <body-file>`.
5. PR (do not merge), body ends with the Claude Code attribution line. Do not send bus messages.
