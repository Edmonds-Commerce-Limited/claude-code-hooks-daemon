# Plan 00501 Task 8.3: the `manual-goals` mode, implementation report

Brief: `untracked/scratch/brief-501-phase8-3.md`. Branch `worktree-501-phase8-manual-goals`, base `8ea9c88a8`.

## Part 1

I stopped before writing any code. Reading the code below (and the brief's reading list) took this agent past its
150k context budget. This part records the design and the code facts that settle it, so the next agent can start
at the RED tests without reading the code again. Line numbers are at base `8ea9c88a8`.

### Facts found

All paths are under `src/claude_code_hooks_daemon/`.

1. **Precedence is already in place.** `utils/session_modes.py:92-101`: `ModeLabel.MANUAL_GOALS` sits between
   `AWAITING_HUMAN` and `FOCUS`. Line 98 carries a stale "Task 8.3 builds the mode" comment; delete it.

   - `SessionMode` (line 43) has no `MANUAL_GOALS`.
   - `_REGISTRY_OWNED` (line 61) holds focus and blocked only.
   - `SessionModeEntry.label` maps `ModeLabel(self.mode.value)`, so a mode value of `"manual-goals"` gets its label
     with no other change.

2. **Every entry must expire.**

   - `SessionModeEntry.__post_init__` refuses `expires_at <= entered_at`.
   - The registry's `_parse_record` and `_finite` (`core/session_mode_registry.py:615-656`) refuse a non-finite
     expiry.
   - The supervisor requires a finite expiry too.

3. **The supervisor would close its gate on the new mode.** `.claude/ccy/claude-supervise.py:2862` has
   `_SESSION_MODES_STORED_MODES = frozenset({"focus", "blocked"})`, and `_parse_session_modes_record` (line 2931)
   raises `_SessionModesError` on any other mode. A `manual-goals` entry would therefore read as "session-modes
   file unreadable, treated as BLOCKED", and the supervisor would withhold `continue`. That breaks the owner's
   answer. The fix:

   - Add `"manual-goals"` to that set.
   - Have the parser return `label=None` for it, as for focus.
   - Pin the change in `tests/unit/supervise/test_session_modes_gate.py`, which pins these copies.
   - The edit takes effect only after the running worker hot-reloads (see `CLAUDE/development/CcySupervisor.md`).
     Do not touch the running process.

4. **Where `.goal-intent` is written.** All writes go through `write_goal_signal`
   (`handlers/post_tool_use/goal_injection.py:483`). It has four callers:

   - Line 1365: the retirement fan-out to every OWNER session (`_maybe_refresh_on_retirement`), so the check must be
     per target session.
   - Line 1510: `_write_combined_signal`, which serves both the flip and the new-session reassert.
   - Line 1561: `_write_fallback`.
   - `daemon/cli.py:6139`: the human's explicit `inject-goal` CLI. It runs in the CLI process, which has no
     registry. Leave it ungated: it is a human's manual goal, not automated injection.

   Every handler caller already treats a `None` return as "not written, do not latch, retry later". That is the
   behaviour wanted while the mode is on: when the mode ends, the next qualifying event writes the goal.

5. **The entry hook.** `handlers/stop/goal_loop_detector.py:327` `_attribute_clears` logs each verdict and queues
   `verdict.line()`. It catches `OSError`, `RuntimeError`, `GoalClearAttributionError` and `TransitionLogError` and
   calls `log_and_continue`. `ClearVerdict` (`core/goal_clear_attribution.py:209`) carries `attribution` and
   `evidence`.

6. **The pop-once channel.**

   - `SessionModeRegistry.queue_line` and `take_lines` (registry lines 353-367) hold the queued lines.
   - `pending_mode_statement` (`core/session_mode_statement.py`) is their only reader. `focus_mode_trigger` calls it
     on every prompt, AFTER `_apply`, so a line queued during `_apply` is stated in the same prompt's
     `SESSION MODE:` line.

7. **Patterns to mirror.**

   - Focus operations: `core/focus_mode.py` (`parse_focus_command`, `_COMMAND_RE`, `FocusChange.line()`,
     `enter_focus`, `exit_focus`).
   - IPC: `daemon/session_mode_ipc.py` (`handle_session_mode_action`, `_answer`).
   - IPC constants: `constants/modes.py:27` `SessionModeIPC` (its `ACTIONS` frozenset).
   - CLI: `daemon/cli.py:2212-2389` (`_session_mode_request`, `cmd_session_mode`) and the subparsers at 11012-11049.
   - `/mode` skill: `.claude/skills/mode/SKILL.md` and `invoke.sh`. There is no template copy under `src`.
   - `mode-history` already prints every transition, so registry `enter` and `exit` show there with no extra work.

8. **Status line.** `SessionPolicy.badge()` shows the top label, so the badge needs no code. Still check that the
   `session_mode_indicator` segment has no per-label map, and add the label to its `status-line-explained` entry.

   - `manual-goals` must NOT go into `_WORK_HALTING`, `_HALTS_STOP_BLOCK` or `BLOCKED_LABELS`.
   - With it outside those sets, `drives_work` stays True, ticks are delivered and `continue` is untouched, which
     matches the owner's answer.

### Design

- **`utils/session_modes.py`**
  - Add `SessionMode.MANUAL_GOALS = "manual-goals"` and put it in `_REGISTRY_OWNED`.
  - Add `MANUAL_GOALS_RETENTION_SECONDS = 30 days`. Its docstring must say this is not a TTL: the mode ends at an
    explicit switch-back or with the session, because a new session has a new id. The bound exists only because
    every entry must expire (fact 2), so a dead session's file gets reaped. Prompts do not renew the entry
    (`renewal_ttl` stays None).
  - Add the factory `manual_goals_entry(session_id, *, entered_at, source)`, with lifetime `SESSION` so it survives
    a restart.
  - Add `SessionPolicy.goal_intent_suppressed`, which is True when the `MANUAL_GOALS` label is live.
  - Do not touch the work-halting sets.
- **New `core/manual_goals.py`** (test first: `tests/unit/core/test_manual_goals.py`)
  - `parse_goals_command(prompt)`, mirroring `parse_focus_command`: `hooks-daemon goals on|auto` means EXIT and
    `off|manual` means ENTER.
  - `GoalsOutcome`: `ENTERED`, `ALREADY_MANUAL`, `EXITED`, `NOT_MANUAL`.
  - `GoalsChange.line()`. The ENTERED line says automated goal injection is off for this session; `continue`, cron
    ticks and guards are unaffected; a typed `/goal <condition>` still works but does not end the mode; and
    `hooks-daemon goals on` or `/mode goals auto` ends it.
  - `enter_manual_goals(registry, sid, *, source, evidence)` is idempotent: when the mode is already on it does not
    re-enter and does not log again.
  - `exit_manual_goals(registry, sid, *, evidence)`.
  - `goal_intent_suppressed(registry, sid)`.
- **Stop path.** In `_attribute_clears`, when the verdict is `Attribution.HUMAN`, call
  `enter_manual_goals(..., source=HUMAN, evidence=verdict.evidence)`. If the outcome is ENTERED, `queue_line` its
  line; that is the one statement on entry. The existing restart dedupe (`attributed_keys`) means a re-read clear
  cannot re-enter the mode. Add tests:
  - A human clear enters the mode.
  - A supervisor or supervisor-assumed clear does not.
  - A transcript holding only `/goal <condition>` changes nothing.
  - A second human clear does not repeat the line.
- **`goal_injection.py`**
  - Add one helper that the three handler callers use instead of `write_goal_signal`.
  - It reads `get_data_layer().session_modes.policy(sid)`. When `goal_intent_suppressed` is set, it logs at INFO
    and returns None.
  - It fails closed. `RuntimeError` or `OSError` from the registry is a WARNING through `log_and_continue`, naming
    the error, with no write.
  - Test the flip, reassert and fan-out paths, the last with one owner manual and one not.
- **Prompt trigger.** `focus_mode_trigger._apply` also parses the goals command, and the transition evidence is
  `the human's hooks-daemon goals prompt command`. Update its `get_claude_md`.
- **IPC.** Add `ACTION_ENTER_MANUAL_GOALS` and `ACTION_EXIT_MANUAL_GOALS` to `SessionModeIPC` and `ACTIONS`, and
  `_answer` branches for them.
- **CLI.** Add a top-level `hooks-daemon goals {on,off}` command (alias `auto`/`manual`), with the session taken from
  `--session` or `CLAUDE_CODE_SESSION_ID` as in `cmd_session_mode`. It prints the line. Add CLI tests beside
  `tests/unit/daemon/test_cli_session_mode.py`.
- **`/mode` skill.** `goals auto|on` maps to `goals on`, and `goals manual|off` to `goals off`. Update both the
  SKILL.md usage and the `invoke.sh` parse list.
- **Docs.**
  - Add a `manual-goals` section to `CLAUDE/core/SessionModes.core.md` and to its template under
    `install/templates/core/`, keeping the two byte-identical. The section covers entry, the single suppression,
    exit, the absence of a TTL, its place in the precedence, and the supervisor's reading.
  - Leave a pointer that the control-panel mod section is Plan 00497 Task 3.5's.
- **Release note.** `CLAUDE/UPGRADES/UNRELEASED/release-notes/026-manual-goals-mode.md`, in the same format as 025.

### Files changed (committed)

Only this report.

### Left

The whole implementation, in the order of the Design list above, followed by the brief's QA loop:
`run_autofix.sh`, then `llm_qa.py changed --range 8ea9c88a8..HEAD --allow-unmapped`. After QA passes, tick the
PLAN.md task and write Part 2.

The supervisor edit (fact 3) must land in the same branch as the first commit that can write a `manual-goals`
entry. Otherwise a merged daemon would switch the supervisor's `continue` off for any session that enters the mode.

### Head

The commit that adds this report. No QA was run, because there is no code change yet.
