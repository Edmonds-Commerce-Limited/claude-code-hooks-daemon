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

## Part 2 (part A)

Brief: `untracked/scratch/brief-501-phase8-3a.md`. The expiry follows the adviser's ruling
(`261023-phase8-3-expiry-ruling-fable.md`, option 3). The Part 1 design said "prompts do not renew"; that line is
superseded by the ruling.

### What changed

All paths are under `src/claude_code_hooks_daemon/` unless stated otherwise.

- **`utils/session_modes.py`**
  - Adds `SessionMode.MANUAL_GOALS` and puts it in `_REGISTRY_OWNED`.
  - Adds `MANUAL_GOALS_RETENTION_SECONDS` (30 days). Its comment describes a liveness bound, not a TTL.
  - Adds `_RENEWAL_TTLS` and `_RENEWED_BY_ANY_PROMPT`.
  - `renewal_ttl` now returns the retention for manual-goals.
  - New `SessionModeEntry.renewed_by(*, genuine)`: focus is renewed only by a genuine prompt, manual-goals by
    every prompt.
  - New `manual_goals_entry(...)` factory (lifetime `SESSION`).
  - New `SessionPolicy.goal_intent_suppressed`.
  - Removes the stale "Task 8.3 builds the mode" comment.
  - The work-halting sets are untouched, so `drives_work` stays True and the mode is neither blocked nor
    halting.
- **`core/session_mode_registry.py`**: `note_prompt` now runs on every prompt and renews each entry with
  `renewed_by(genuine=...)`. It still returns whether the prompt was genuine. A machine prompt can now commit an
  expiry it finds, as any read already does.
- **`core/manual_goals.py`** (new, test first in `tests/unit/core/test_manual_goals.py`)
  - `GoalsOutcome` with `ENTERED`, `ALREADY_MANUAL`, `EXITED` and `NOT_MANUAL`.
  - `GoalsChange.line()`.
  - `enter_manual_goals(registry, sid, *, source, evidence)`. It is idempotent: when the mode is already on it
    does not re-enter and does not log.
  - `exit_manual_goals(registry, sid, *, evidence)`.
  - `goal_intent_suppressed(registry, sid)`.
  - Enter and exit are logged through the registry's own transition records. A renewal is not logged, as with
    focus.
- **`handlers/stop/goal_loop_detector.py`**
  - In `_attribute_clears`, an `Attribution.HUMAN` verdict calls the new `_enter_manual_goals`, which runs
    `enter_manual_goals(source=HUMAN, evidence="a human typed a goal clear (<verdict evidence>)")`.
  - On `ENTERED`, the entry line is queued once through `queue_line`.
  - A failure goes through the existing `log_and_continue` boundary, and the Stop is allowed.
- **`handlers/post_tool_use/goal_injection.py`**
  - New `write_automated_goal_signal` and `_automated_goal_allowed`. A session in manual goals is logged at INFO,
    and an unreadable registry is a WARNING; in both cases nothing is written.
  - The three automated callers use the new function: the retirement fan-out (gated per owner), the flip and
    reassert path in `_write_combined_signal`, and `_write_fallback`.
  - `write_goal_signal` itself, and so `daemon/cli.py` `inject-goal`, stays ungated.
- **`handlers/user_prompt_submit/focus_mode_trigger.py`**: `_apply` calls `note_prompt` on every prompt, a focus
  command included, before carrying out the command.
- **`.claude/ccy/claude-supervise.py:2862`**: `_SESSION_MODES_STORED_MODES` now includes `"manual-goals"`, which
  parses to label `None` like focus. The mode never closes the gate.
  - Pinned by `TestFieldPin.test_closed_value_sets`, which derives the set from `registry_owned`.
  - Also covered by the new `TestReader.test_manual_goals_alone_is_not_blocked_and_keeps_the_gate_open`.
  - It takes effect only after the running worker hot-reloads. I did not touch the running process.
- **Tests**
  - `tests/unit/utils/test_session_modes.py`: renewal rules, factory, policy.
  - `tests/unit/core/test_session_mode_registry.py`:
    - A tick-only session keeps the mode.
    - Machine traffic renews manual-goals but not focus.
    - A session with no prompt for the retention period loses its file.
  - `tests/unit/handlers/user_prompt_submit/test_focus_mode_trigger.py`: a tick, a focus command and plain text
    each renew the mode.
  - `tests/unit/handlers/stop/test_goal_loop_detector.py`:
    - A human clear enters the mode and states it once.
    - A second human clear adds no line.
    - Supervisor and supervisor-assumed clears do not enter the mode.
    - `/goal <condition>` changes nothing.
    - A failed entry is a WARNING, and the Stop is allowed.
  - New `tests/unit/handlers/post_tool_use/test_goal_injection_manual_goals.py` covers:
    - the helper: manual, other session, and fail closed;
    - `_write_fallback`;
    - `_write_combined_signal` for a manual and an auto session;
    - the retirement fan-out with one manual owner and one auto owner.

### QA

`llm_qa.py changed --range 8ea9c88a8..HEAD --allow-unmapped`: **QA: 41/41 PASSED** at `3d7c1ee27`, on a clean
tree. The first run found one `error_hiding` `return-none-on-error` in the new helper. `3d7c1ee27` fixes it: the
registry read now returns a bool, so `None` is never returned from an `except`.

### Head

`3d7c1ee27` for the code. This report is committed on top of it.

### Left for part B

1. **Prompt trigger**
   - In `core/manual_goals.py`, add `parse_goals_command(prompt)` mirroring `core/focus_mode.py`
     `parse_focus_command` and `_COMMAND_RE`: `goals on|auto` means EXIT and `goals off|manual` means ENTER.
   - In `handlers/user_prompt_submit/focus_mode_trigger.py`, call it in `handle()` next to
     `parse_focus_command`, and branch in `_apply` after the unconditional `registry.note_prompt` line.
   - Evidence: `the human's hooks-daemon goals prompt command`.
   - Make the failure lines in `_apply_or_report` say "MANUAL GOALS NOT CHANGED" for a goals command.
   - Update `get_claude_md`.
2. **IPC**
   - Add `ACTION_ENTER_MANUAL_GOALS` and `ACTION_EXIT_MANUAL_GOALS` to `constants/modes.py` `SessionModeIPC` and
     its `ACTIONS`.
   - Add `_answer` branches in `daemon/session_mode_ipc.py` that call `enter_manual_goals` and
     `exit_manual_goals`.
3. **CLI**
   - Add `hooks-daemon goals {on,off}` (aliases `auto`/`manual`) in `daemon/cli.py`, beside
     `_session_mode_request`/`cmd_session_mode` (about lines 2212-2389), with subparsers near 11012-11049.
   - Tests go beside `tests/unit/daemon/test_cli_session_mode.py`.
4. **`/mode` skill**: in `.claude/skills/mode/SKILL.md` usage and the `invoke.sh` parse list, map
   `goals auto|on` to `goals on` and `goals manual|off` to `goals off`.
5. **Docs**
   - Add a manual-goals section to `CLAUDE/core/SessionModes.core.md` and its `install/templates/core/` twin,
     keeping the two byte-identical.
   - Add the label to the `session_mode_indicator` `status-line-explained` entry.
   - Add the routing-table wording in `CLAUDE/CLAUDE.md` ("Session modes (focus, BLOCKED, usage-paused)").
6. **Release note**: `CLAUDE/UPGRADES/UNRELEASED/release-notes/026-manual-goals-mode.md`.
7. **Open question for the coordinator (not changed here)**: automated goal CLEARS are not gated.
   - `_maybe_refresh_on_retirement` with no live refs, and `_write_fallback(fallback=None)`, still call
     `clear_goal_signal`.
   - Either can therefore clear a `/goal <condition>` the human typed while in manual goals.
   - The brief scoped the gate to the three `.goal-intent` writes. Decide whether the retraction should be gated
     too.
8. **Wording the entry line already promises**: the `ENTERED` line names `hooks-daemon goals on` and
   `/mode goals auto`, which part B builds. Both must land in this branch before it merges.
