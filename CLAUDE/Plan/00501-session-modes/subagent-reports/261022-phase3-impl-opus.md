# Plan 00501 Phase 3 implementation report (Opus sub-agent)

Worktree `/workspace/untracked/worktrees/worktree-501-phase3-focus`, branch `worktree-501-phase3-focus` (pushed).
Tasks 3.1, 3.2 and 3.3 are delivered and ticked in PLAN.md. Nothing is merged, and the main daemon was not restarted.

## Built

- **`core/focus_mode.py`** holds the one implementation every route shares:
  - `parse_focus_command`: anchored at the prompt start, case-insensitive, accepts `hooks[-\s]+d(ae|e)mon focus`, and
    only matches a genuine human prompt (`is_genuine_human_prompt`, which wraps `is_genuine_text`). `off` and its aliases
    count only when they are the WHOLE argument, so "focus end-to-end tests" is a task.
  - `enter_focus` / `exit_focus` return a `FocusChange` with a one-line `line()`.
  - Entry builds a human, session-lifetime entry with a 12 h TTL. On the first entry only, it calls the injected
    `clear_goal` callable; a task change does not clear again. A failed clear is logged at WARNING and stated in the
    line ("a human must type `/goal clear`").
  - The entry line states the ruled wording: the supervisor types `/goal clear` at its next idle, or a human must type it.
  - `failsafe_focus_line`, with the exact ruling 04 text, and `focus_reminder`.
- **Task 3.1, `handlers/user_prompt_submit/focus_mode_trigger.py`**:
  - New handler: `HandlerID.FOCUS_MODE_TRIGGER`, priority 41, non-terminal, not `drives_autonomy`.
  - It is registered in `.claude/hooks-daemon.yaml`, `init_config.py` and `HANDLER_REFERENCE.md`, and in the guidance
    coverage test (as T3).
  - A command produces exactly one line. Every other genuine prompt calls `note_prompt` (TTL renewal).
  - It also states the registry's pending one-time notices (`take_notices`) as `SESSION MODE: ...` lines, which
    includes the restart notices (see Left).
  - A registry failure is logged at WARNING and, on a command, stated to the agent.
- **Task 3.2**:
  - `failsafe_cron_blockage_suppressor`: when the action is `DELIVER_NAMING_FOCUS`, the cadence is reset and the tick is
    allowed with `context=[failsafe_focus_line(task)]`. It is never thinned, whatever is owed.
  - A dropped declared tick's reason now ends `Session mode: <clause>`. The `R-DECLARED-CRON-SUPPRESSED`
    blocked/why/fix/verbose text names focus, and the guidance sentence "a focus mode alone never suppresses a tick" was
    corrected.
  - `auto_continue_stop._goal_ledger_challenge` returns `focus_reminder(task)` when focused, in every environment, and
    otherwise behaves as before. Its `autonomy_allowed` import was replaced by `autonomy_verdict`.
  - The `.goal-intent` part needed no new code: `goal_injection` is `drives_autonomy`, so the chain gate skips it. A
    test pins this, with a control.
- **Task 3.3**:
  - `constants/modes.py` gains `SessionModeIPC`: the actions `get_session_modes`, `enter_focus` and `exit_focus`, their
    keys, and `FOCUS_OFF_ALIASES`, the single source for the aliases.
  - `daemon/session_mode_ipc.handle_session_mode_action` answers them. A bad request returns an error, and a registry
    failure returns an error and logs a WARNING.
  - `server._handle_system_request` routes to it; `get_mode`/`set_mode` are untouched.
  - `session_mode_ipc.clear_goal_signal` defers its `goal_injection` import. The cycle is server -> handlers package ->
    install -> server, which is the same reason `cmd_clear_goal` defers it.
  - The CLI is `hooks-daemon session-mode [get|focus <task...>|focus off] [--session ID] [--json]`. The session
    defaults to `CLAUDE_CODE_SESSION_ID`.
  - The `/mode` skill (`.claude/skills/mode/invoke.sh` and `SKILL.md`) gains `focus <task>` and `focus off` (with the
    aliases), and `get` also runs `session-mode get`.
- The release note is `CLAUDE/UPGRADES/UNRELEASED/release-notes/021-focus-mode-points-a-session-at-one-task.md`;
  020 was the highest on `origin/main`.
- `regenerate-docs` was run on the worktree with `--project-root`, so `.claude/HOOKS-DAEMON.md` and the CLAUDE.md
  block carry the new handler. The guidance test reads them.

## Red and green

| Task | Red                                                                                                           | Green                                                                                                                                                 |
| ---- | ------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 3.1  | `p3-red-core.txt` and `p3-red-trigger.txt`: `ModuleNotFoundError`, pytest exit 2                              | `p3-green-core.txt` (34 passed); `p3-green-trigger.txt` (58 passed, `focus_mode.py` 100%, trigger 95.5%, then the two remaining methods were covered) |
| 3.2  | `p3-red-32.txt`: 7 failed (failsafe context `[]`, declared reason lacked the task, three stop-reminder tests) | `p3-green-32.txt`: 927 passed over `handlers/user_prompt_submit`, `handlers/stop`, `goal_injection*`, the chain gate and the paths import test        |
| 3.3  | `p3-red-33.txt`: `ImportError SessionModeIPC`; `p3-red-skill.txt`: 8 failed                                   | 32 passed, `session_mode_ipc.py` 100%; 9 passed for the skill                                                                                         |

All files are under `untracked/scratch/`.

`tests/unit/daemon/test_paths_import_under_310.py` passes after each import change. Phase 2's Left 1 no longer
reproduces in this tree.

## QA

- First run: `QA: 38/41 PASSED, 1/41 FAILED, 2/41 NOT MEANINGFUL`. Pyright found 2 errors, both in a Mock double in
  `test_session_mode_ipc.py`; they were fixed in `2745a63c2`. In that run, `changed_tests` passed 7031 with 0 failed.
- Second run: `QA: 38/41 PASSED, 2/41 FAILED, 1/41 NOT MEANINGFUL`.
  - The format failure was the autofix rewrapping one line. It was committed in `12cb2e81f`.
  - `changed_tests` reported 7030 passed and 1 failed: `tests/unit/test_doc_write_jail.py::TestSessionWiring::test_every_checkout_of_the_repository_is_protected`.
- Third run, at head `12cb2e81f`: **`QA: 40/41 PASSED, 1/41 FAILED`**. `changed_tests` again reported 7030 passed and 1
  failed, and it was the same jail test.
- That test passes on its own, and it also passes beside every Phase 3 test file (128 passed;
  `untracked/scratch/p3-jail2.txt`). It compares the protected-path set captured when the pytest session starts with
  the repository's checkouts at the moment it runs. Other agents create and remove worktrees while a long run is in
  progress, which explains the result. Phase 3 does not touch `doc_write_jail` or the conftest.
- The coordinator's full gate should confirm the test is clean.

QA could not map 10 files, all marked too-broad: `.claude/HOOKS-DAEMON.md`, `.claude/hooks-daemon.yaml`, `CLAUDE.md`,
`constants/handlers.py`, `constants/modes.py`, `constants/priority.py`, `daemon/cli.py`, `daemon/init_config.py`,
`daemon/server.py` and `handlers/stop/auto_continue_stop.py`.

## Left

1. **Task 4.2 overlap.** `focus_mode_trigger` takes and states ALL of a session's pending registry notices at its next
   prompt, which includes `SURVIVED_RESTART` and `CLEARED_BY_RESTART`. Task 4.2 should build on this rather than add a
   second consumer, because `take_notices` is pop-once. Task 4.2 is not ticked: its "unconditional" part (modes the
   registry does not own) is not done.
2. Three tests in `tests/unit/daemon/test_cli_modes.py::TestCmdRestartModeAdvisory` fail only under
   `--cov=...daemon.cli`, on a YAML constructor error from the real config. They pass without `--cov`. Their code was
   not touched here, and this is the same cov-only pattern Phase 1 noted.
3. The ccy supervisor side ("injects no goals or prompts" under focus) is Phase 5.
