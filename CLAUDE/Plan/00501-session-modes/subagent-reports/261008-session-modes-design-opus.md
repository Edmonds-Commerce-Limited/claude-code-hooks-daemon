I couldn't create `/workspace/untracked/agent-reports/261008-session-modes-design-opus.md`. This agent is read-only and has no file-writing tool. The full proposal is below. Please save it to that path as written.

---

# Session modes: design proposal (Plan 00501 rework, issue #91)

**Date:** 2026-10-08 · **Author:** Opus planning agent (read-only) · **Status:** proposal for the owner

## 0. Findings that change the plan

These came out of reading the code. Each one affects the design.

- **F1. The `[awaiting-human]` marker is one file for the whole project, not one per session.** It is `untracked/human-input-blockage-marker.json` (`utils/blockage_marker.py:41`).
  - Whichever session writes last wins (`write_marker`, `:55`).
  - The suppressor clears it on *any* prompt with no tick sentinel, from *any* session, with no session check (`failsafe_cron_blockage_suppressor.py:311-319`). So the owner typing in session B silently re-arms crons in session A, which is still waiting.
- **F2. The ccy supervisor's own typed lines count as "the owner coming back".** `continue`, `/goal …` and notices all start with `🤖 [ccy-supervisor`, but the suppressor only checks for a tick sentinel (`classify_tick`, `:306`). A tested "is this a genuine human?" classifier already exists and is used for `AskUserQuestion`: `utils/human_presence.py:80` `_is_human_prompt`, with `skill_scan/constants.py:29` `EXCLUDE_CONTENT_MARKERS`. The suppressor does not use it.
- **F3. The supervisor never reads the awaiting-human marker.** It stands down only for a usage pause (`claude-supervise.py:6846-6850`). So it can still type `/goal` or the session-actions directive into a session that has declared it is blocked.
- **F4. The `/goal` loop can be detected exactly on the daemon side, not by matching prose.** Claude Code writes a structured transcript attachment for every goal evaluation: `{"type":"goal_status","met":false,"condition":…,"reason":…,"iterations"?,"tokens"?}`. It is followed by a `user` record `"Stop hook feedback: …"` and a `system/stop_hook_summary`.
  - This was seen in real transcripts under `~/.claude/projects/-workspace/*.jsonl`: 266 records, 239 of them `met:false`.
  - One recorded reason reads: *"The assistant explicitly states it is 'staying stopped' and '[awaiting-human]' … Plans … remain live"*. That is the loop the issue describes.
  - The supervisor sees only output *timing* (`OutputActivity`, `:976`), not screen text. So the supervisor should not be the detector.
- **F5. The loop turns arrive as Stop-hook re-entries.** The `/goal` evaluator is itself a Stop hook (Plan 00419 notes), so the next Stop arrives with `stop_hook_active=true`. `auto_continue_stop.matches()` skips genuine re-entries (`auto_continue_stop.py:742-758`). A detector inside `auto_continue_stop` would therefore miss exactly the turns it needs to count. It must be its own handler that does not skip re-entry.
- **F6. A "break the loop" channel already exists.** `goal_injection.clear_goal_signal(session_id)` (`goal_injection.py:518-556`) removes `<session>.goal-intent` and drops `<session>.goal-clear`. The supervisor turns that into a fixed `/goal clear` (`claude-supervise.py:2600-2603`, `7280-7318`). It is capped at 5 per process, and it ranks below goal *injection*.
- **F7. The supervisor has no socket client.** It is stdlib-only and talks to the daemon only through per-session files in `untracked/context-sidecar/` (usage-paused, goal-intent, goal-clear, model-switch, operator, session-actions). Task 3.1's "socket query" would be a new and unusual channel. The established pattern is a per-session file the daemon owns.
- **F8. The daemon `mode` (default/unattended) already has the lifetime the owner wants for focus.** It is in memory only and resets to config `default_mode` on restart (`cli.py:2232-2243`). But it applies to the whole daemon, so every session of the project. It is **not shown on the status line** (no status-line handler reads it), only through `/mode get` and the `health` IPC (`controller.py:1291`).
- **F9. Stop hooks in this daemon cannot halt a turn yet.** `continue:false` / `stopReason` is supported only for PreToolUse (`hook_result.py:93-94, 260-302`; `result_types.py:124` `deny_and_halt`). Claude Code documents that `continue:false` "takes precedence over all other decisions" (`CLAUDE/Code/HooksSystem.md:424`). Whether that beats the `/goal` evaluator is unknown and needs a spike. If it does, the daemon can break a loop without any supervisor.

## 1. Inventory of mode-like state today

| # | State | Scope | Set by | Cleared by | Persistence | Read by |
|---|---|---|---|---|---|---|
| 1 | **`[awaiting-human]` marker** | Meant to be per session, but stored as one project file (F1) | `auto_continue_stop` Branch 2 ALLOW when the stop text matches `_AWAITING_HUMAN_DECLARATION` or `_HUMAN_BLOCKED_PATTERNS` (`auto_continue_stop.py:181-234, 815, 940-977`); skipped for synthetic probes | Any prompt without a tick sentinel (`failsafe_cron_blockage_suppressor.py:311-319`); expiry `expiry_hours`, default 24 (`:122, 324`) | File `untracked/human-input-blockage-marker.json`; survives daemon restart | `failsafe_cron_blockage_suppressor` (drops failsafe ticks at `:345-369` and declared jobs at `:408-423`, honouring `runs_while_awaiting_human`, `config/models.py:2206, 2328`); the stand-in only fires while the marker is live |
| 2 | **Failsafe cadence/backoff** | Project file plus a session field | Suppressor `_apply_backoff` (`:425-445`) | Any non-tick prompt (`reset_cadence`, `:318`) | File `CADENCE_FILENAME` | Suppressor |
| 3 | **Awaiting-human stand-in cron** | Session (lives in `session_crons`) | `auto_continue_stop._stand_in_block` demands a `[tick:stand-in]` one-off cron (`:698-710, 816-820`; `utils/stand_in_cron.py:131-147`); gated by autonomy | Fires once; acts only if the marker is still live | Claude Code cron | The agent (Fable sub-agent) |
| 4 | **Daemon mode `default`/`unattended`** | Whole daemon (all sessions) | `/mode` skill → `_system set_mode` (`server.py:2467-2499`); CLI `set-mode` (`cli.py:2011`); config `default_mode` (`config/models.py:1975`; `controller.py:946-969`) | `set_mode default`; daemon restart → config default | Memory only | `UnattendedModeInterceptor` blocks every main-thread Stop before the chain (`core/mode_interceptor.py:127-170`, wired at `controller.py:1042-1055`); `health` |
| 5 | **`ask_user_question_blocker` mode** (`strict`/`advisory`/`unattended`) | Handler option for the project | Config | Config edit; a human prompt seen recently in this session downgrades `unattended` to `strict` (`ask_user_question_blocker.py:236-253`, `utils/human_presence.py:111`) | Config | That handler |
| 6 | **Autonomy verdict (Plan 00498)** | Environment + effective hostname | Config `autonomy:` (`utils/autonomy.py:100-123`) | Config edit | Config | Chain gate `chain.py:1119-1125` (9 `drives_autonomy` handlers); direct calls in `auto_continue_stop.py:706, 927`, `background_process_tracker.py:392`; status line `environment_indicator.py:46-47, 83-86` ("no autonomy"); `autonomy_notice` at SessionStart |
| 7 | **Usage pause** | Per session | Usage gate when a ceiling is crossed (`utils/usage_pause_gate.py`, `utils/usage_pause.py:120-122, 163`) | Resume tick at/after `resume_at`; `clear_usage_pause`; override file | File `context-sidecar/<sid>.usage-paused`, bounded by `resume_at` + grace | `hook_is_usage_paused` in `auto_continue_stop:731`, `cron_stop_enforcer:152`, `cron_subagent_stop_enforcer:130`, `persistent_cron_assertor:119`, `failsafe_cron_session_advisor:132`, `recovery_cron_advisor:563`; **supervisor** `load_usage_pause` decides the whole tick (one `/compact`, then silence, `claude-supervise.py:6671-6751, 6846-6850`) |
| 8 | **Cron pause** | Per session, per declared job | CLI `cron-pause <job> --reason` (`cli.py:11416`; `utils/cron_pause.py`) | 24 h TTL (`:52-55`) | File `untracked/cron-pauses.json` | Cron enforcers |
| 9 | **Goal signals** | Per session | `goal_injection` on a plan flip to In Progress; CLI `inject-goal` | `clear_goal_signal`; CLI `clear-goal` (`cli.py:11293`); TTL 600 s | `context-sidecar/<sid>.goal-intent` / `.goal-clear` | Supervisor `/goal` (cap 5 per hour, identical-text guard, `:7213-7274`) and `/goal clear` (cap 5, `:7280-7318`) |
| 10 | **Goal ledger** | Whole project | `goal_injection` | Plan reaches a terminal status | File `goal-ledger.json` | `auto_continue_stop._goal_ledger_challenge` (`:913-938`); suppressor `_work_is_owed` |
| 11 | **Claude Code's own `/goal` slot** | Per session (in Claude Code) | Typed `/goal …` | `/goal clear\|stop\|off\|reset\|none\|cancel` | Claude Code | The goal evaluator Stop hook (`goal_status` attachments, F4) |
| 12 | **Release in progress** | Whole project | `/release` writes `untracked/release-state.json` | Step 15 verification deletes it | File | `release_blocker` project handler (terminal DENY, `.claude/project-handlers/stop/release_blocker.py:106`) |
| 13 | **Orchestrator-only (simulate)** | Main thread | Code constant `BLOCKING_ENABLED = False` (`.claude/project-handlers/pre_tool_use/orchestrator_simulate.py:171`) | Code edit | Code | That handler (records only) |
| 14 | **Session-actions / standing-auth / model-switch / operator signals** | Per session | Various handlers and CLI | Consumed or TTL | `context-sidecar/<sid>.*` | Supervisor |
| 15 | **Claude Code `permission_mode`** | Per session, from Claude Code | The user | The user | n/a | `utils/permission_mode.py` (bypass-only approvers) |
| 16 | **Supervisor presence (🎩)** | Per project | The supervisor's status file | Supervisor exit | File | `status_line/supervisor_indicator.py` |

Not mode-like, so out of scope: `strict_mode` (QA error tiers), `staging_simulation` (git index simulation), `one_shot_approval` markers.

## 2. A unified session-mode model

### 2.1 Principle

A **session mode** is a named, per-session condition with five parts:

1. a **suppression set**: what work-driving machinery it turns off;
2. an **entry source**: human, agent declaration, daemon detection, or config;
3. **exit conditions**;
4. a **lifetime class**;
5. a **status-line label**.

Modes **compose**. A session can be `focus` and `awaiting-human` at once. The effective policy is the **union of suppressions**, plus one precedence rule for the single thing that conflicts (the unattended stop-block, see 2.4). Guards are never part of any mode.

### 2.2 The modes

| Mode | Kind | Entered by | Exited by | Lifetime |
|---|---|---|---|---|
| `focus` | user intent | Prompt `hooks-daemon focus <task>` (speech-to-text spellings tolerated); `/mode focus <task>`; CLI `hooks-daemon session-mode focus …` (keyed by `CLAUDE_CODE_SESSION_ID`, like `cron-pause`) | `hooks-daemon focus off\|done\|end\|disable`; new session id; TTL (open question 2); daemon restart only if the owner keeps that rule (open question 1) | **session-scoped, in memory** with the session-scoped file mirror below |
| `awaiting-human` | agent declaration | `STOPPING BECAUSE: [awaiting-human]` / frozen patterns (unchanged write side) | A **genuine human** prompt in **this** session (F1/F2 fix); expiry 24 h; the stand-in's ruling (unchanged) | Persistent per-session file, survives restart (as today) |
| `goal-blocked` | daemon detection | Goal-loop detector (section 3) | Genuine human prompt; repo change (HEAD moved or a non-journal tracked file changed); capped timer (default 4 h); explicit `hooks-daemon focus off`-style `session-mode clear goal-blocked` | Persistent per-session file, survives restart. Restart must not re-arm the loop |
| `usage-paused` | daemon (existing) | Usage gate | Resume tick / override | Existing `.usage-paused` file. **Shown** in the new view, **not migrated** in storage |
| `unattended` | user/config | `/mode unattended` (daemon-wide today) | `/mode default`; restart → config | Phase 1: stays daemon-wide and is shown on the badge. Later, optionally per session (open question 5) |
| *(environment)* `no-autonomy` | config | `autonomy:` | config | Not a session mode. Shown as today in `environment_indicator`, and folded into the same verdict |

**Decision: `goal-blocked` and `awaiting-human` form one family, not three independent states.** This answers the issue's request to merge rather than add a third state. Internally both are `BLOCKED` with `reason ∈ {declared, goal-loop}`. They share one suppression set and the human-prompt and expiry exits. `goal-loop` adds three things:

- a one-time `/goal clear` action;
- the repo-change exit;
- no stand-in demand, because a detected loop has no laid-out options for Fable to choose from.

The status line shows them under different labels (`awaiting-human` vs `goal-blocked`) because the owner wants to see the difference.

Under the unified model, a declared `[awaiting-human]` stop that is then re-armed by `/goal` is simply: `BLOCKED(declared)`, plus the detector firing the `/goal clear` action early (2 cycles instead of 3, section 3).

`unattended-worker` (from the owner's list) is **not a new mode**. It is the *absence* of `focus`/`BLOCKED` in an autonomy-allowed environment, optionally combined with daemon `unattended`. The badge shows nothing for the plain worker (the default stays quiet) and shows `unattended` when that daemon mode is on.

### 2.3 Suppression matrix (✕ = suppressed, ✓ = runs, – = n/a)

| Machinery | focus | BLOCKED (awaiting-human / goal-blocked) | usage-paused | autonomy off |
|---|---|---|---|---|
| Declared `persistent_crons` ticks (dropped at UPS) | ✕ (all jobs, including `runs_while_awaiting_human`) | ✕ unless `runs_while_awaiting_human` (as today) | existing | – (crons not created) |
| Failsafe tick | ✕ (open question 4) | ✕ (today's rows 2/3 logic kept) | existing | – |
| Watchdog tick `[tick:watchdog]` | ✓ (protective) | ✓ | ✓ | ✓ |
| Stand-in tick / demand | ✕ demand | demand ✓ for `declared`, ✕ for `goal-loop`; tick ✓ | – | ✕ (today) |
| `drives_autonomy` handlers (9) | ✕ | ✕ (new for BLOCKED: no cron re-assertion or directives while blocked) | partly existing | ✕ |
| Goal-ledger stop challenge | ✕, replaced by a one-line "focus task: …" reminder | ✕ | – | ✕ |
| `goal_injection` writing `.goal-intent` | ✕ | ✕ (**the non-rearm rule**) | – | ✕ |
| Supervisor `/goal` | ✕ | ✕ | ✕ | – (no signal) |
| Supervisor `/goal clear` | ✓ (one-off on entry, open question 6) | ✓ (one-off on `goal-loop` entry) | ✕ | – |
| Supervisor session-actions / standing-auth | ✕ | ✕ | ✕ | – |
| Supervisor `/compact`, post-compact `continue`, model restore, operator warnings, notices | ✓ | `/compact` ✓; `continue` ✕ (open question 7); others ✓ | existing | ✓ |
| Unattended stop-block interceptor | ✓ (keeps working on the focus task; reason names the task) | **✕** (see 2.4) | existing | ✓ |
| `STOPPING BECAUSE:` rule / explain-or-continue | ✓ | ✓ | existing | ✓ |
| Guards (`release_blocker`, QA, etc.) | ✓ | ✓ | ✓ | ✓ |

### 2.4 Precedence

There is one conflict axis: modes that **halt** (usage-paused > BLOCKED) against modes that **drive** (unattended). A halting mode always wins.

- `UnattendedModeInterceptor` must stand down while the session is BLOCKED or usage-paused. Otherwise it is one more source of stop re-arms, even with its re-entry guard.
- `focus` does not conflict with `unattended`. It narrows what to work on rather than whether to work.

Status-line precedence when several modes are active is `usage-paused > goal-blocked > awaiting-human > focus > unattended`. Show the top one plus a `+N` count, with the full list in `status-line-explained`.

### 2.5 Architecture

1. **`utils/session_modes.py`** (new). A pure policy module.
   - `SessionMode` StrEnum, `BlockReason`.
   - Frozen `SessionModeEntry(mode, session_id, entered_at, source, detail, expires_at, evidence)`.
   - `SessionPolicy`: booleans derived from the active set: `drives_work`, `goal_machinery`, `drops_tick(tick)`, `unattended_block`, `label()`.
   - No I/O, so it is easy to TDD.
2. **`SessionModeRegistry`** (thread-safe, in `DaemonDataLayer` beside `disclosure`).
   - It is the single read/write API, and it **writes through** to one per-session file `context-sidecar/<sid>.session-modes` (suffix deliberately not `.json`, same reason as `.usage-paused`).
   - Each entry records `lifetime ∈ {daemon, session, persistent}`.
   - On daemon start the registry loads the files and drops `daemon`-lifetime entries. For each one it drops, it writes a "cleared by restart" note so the restart notice can be shown.
   - This one file is how the supervisor reads modes (F7), how the status line reads them, and how they survive restarts where the policy allows it. The supervisor reaper (`reap_stale_sidecars`, `:3386`) and a daemon-side TTL bound stale files.
   - The file carries **no free text the supervisor types**. Mode names come from a closed set, and the focus task text is read only by the daemon. This keeps the security shape of the existing channels.
3. **The verdict.**
   - `autonomy_verdict(hook_input)` gains `session_modes`, and `allowed` becomes `env_allowed and policy.drives_work`.
   - `explain()` gains a session clause such as "focus mode: <task>" or "goal-blocked since HH:MM (3 identical stops, no repo change)".
   - Both routes (the chain gate and the 3 direct calls) pick this up for free, as the plan intends.
   - `goal-blocked`'s narrower set (goal machinery only, if the owner prefers that over the full BLOCKED set) would need `Handler.drive_kinds`. **Recommendation: don't.** BLOCKED suppresses everything work-driving, so one boolean is enough. That is simpler and matches what awaiting-human means.
4. **IPC.** Keep `get_mode`/`set_mode` unchanged. Add `_system` actions `get_session_modes {session_id}` and `set_session_mode {session_id, mode, on/off, detail}`, used by the skill, the CLI and acceptance tests.
5. **The suppressor** becomes the single **tick-drop** point for all modes. It asks `policy.drops_tick(tick)` instead of reading the marker directly. Its backoff logic is unchanged. It stays ungated.

## 3. Detecting the goal loop and not re-arming it

### 3.1 Detector

`goal_loop_detector` is a new Stop handler.

- **Shape:** non-terminal, not `drives_autonomy`, and it **runs on re-entry** (F5). Its priority is ahead of `auto_continue_stop`, and it never changes the decision.
- **Each Stop:** it reads the transcript tail since its last checkpoint (`transcript_bytes` style). It extracts:
  - `goal_status` attachments with `met:false`, plus `reason` and `iterations`;
  - whether a **genuine human prompt** appeared (`human_presence._is_human_prompt`, made public);
  - the current turn's `STOPPING BECAUSE:` text.
- **Cycle:** a stop whose text carries `STOPPING BECAUSE:` and is followed by a `goal_status met:false` with no genuine human prompt in between. Cycles are held in memory per session in a bounded ring.
- **Fire when** all of these hold:
  - **consecutive cycles ≥ `min_cycles`** (default **3**, or **2** if every stop in the run declared `[awaiting-human]` or matched `_HUMAN_BLOCKED_PATTERNS`);
  - all within **`window_minutes`** (default **30**);
  - **no repo change** across the run. The fingerprint is `HEAD` sha plus a hash of `git status --porcelain=v1 -z` over tracked paths, **excluding `*/JOURNAL/*`, `untracked/` and the plan's own scratch**, so a "still blocked" journal entry each turn does not hide the loop (option `ignore_paths`). It is computed only when a `met:false` is present, so it costs nothing otherwise;
  - pairwise **stop-text similarity ≥ `similarity`** (default **0.75**, `difflib.SequenceMatcher` on normalised text: lowercase, digits/shas/timestamps collapsed, quoted spans stripped).
- **Rollout:** `mode: observe | act`, defaulting to **`observe` for the first dogfood release**. Observe logs everything and changes nothing. A week of data should set the defaults before flipping to `act`.

### 3.2 Actions on entering `goal-blocked` (in `act` mode)

1. `registry.enter(BLOCKED, reason=goal-loop, evidence=…)`.
2. `clear_goal_signal(session_id)`. The supervisor types `/goal clear` (existing channel, F6). Two supervisor changes are needed:
   - goal-clear must **outrank** goal-intent while the session-modes file says BLOCKED;
   - the clear must be allowed **while the child is not work-idle**. Test it, because the loop never goes work-idle. *Spike:* does a `/goal clear` typed mid-turn get queued or rejected?
3. A context line to the agent, once: "goal-blocked: the /goal loop was detected (N stops, no repo change); the goal is being cleared; stop with one line and wait".
4. **Spike (F9):** extend Stop formatting to emit `continue:false` + `stopReason`, and check whether it ends the turn despite `/goal`. If it does, use it as the non-supervisor break, once per entry, never repeated. If it does not, document that without ccy the only backstop is `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`.

### 3.3 Not re-arming

While BLOCKED:

- `goal_injection` writes no `.goal-intent` for the session, though its ledger bookkeeping still runs;
- the goal-ledger challenge is suppressed;
- the supervisor skips `/goal`, session-actions and standing-auth (it reads the session-modes file, mirroring `load_usage_pause`);
- declared and failsafe ticks are dropped.

On exit nothing re-sets the goal automatically. The next plan status flip, or `inject-goal`, does that as normal.

### 3.4 What to log so false positives can be seen

Append to `untracked/session-modes.jsonl` (private, capped like `stop-events.jsonl`). One record per transition and per detector evaluation that reaches `min_cycles-1`:

- `ts`, `session_id`, `event: enter|exit|near-miss|observe-fire`;
- `mode`, `reason`, `source`, `cycles`, `window_s`;
- `similarities` (list);
- `repo_fp_first/last`, `goal_iterations`, `goal_reason_sha` + its first 120 chars;
- `stop_text_sha`s, `declared_awaiting_human`, `thresholds` (a snapshot of the options);
- on exit, `exit_cause: human_prompt|repo_change|timer|explicit|restart`;
- `supervisor_present`, `action_taken`.

Also add `stop-events.jsonl` field `goal_status_met` when seen.

Add a CLI `hooks-daemon session-modes [--session ID] [--log N]` that prints the active modes and the last transitions with their evidence. A false positive then appears as "entered goal-blocked → human prompt within 2 min with 'no, keep going'". A `false_positive_hint` flag is set when the exit is a human prompt within 10 minutes of entry.

## 4. Migration

1. **Awaiting-human marker.**
   - **Write side:** the patterns, sentinel and anchoring are unchanged. `_maybe_record_human_blocked_marker` calls `registry.enter(BLOCKED, declared)`.
   - **Storage:** moves from the single project file into the per-session file. To keep upgrades seamless, read the legacy `human-input-blockage-marker.json` once on startup, import it if valid for its session, then delete it. Keep `blockage_marker.py`'s `marker_is_valid`; `cron_pause` reuses it.
   - **Clear side:** fixes F1 and F2. Only a genuine human prompt **in the same session** clears it. That is a behaviour change, so add a release note.
   - `RuleID`s, rule texts and `runs_while_awaiting_human` stay as they are.
2. **`mode` skill.**
   - `/mode`, `/mode get`, `/mode unattended`, `/mode default` and their IPC are **unchanged**.
   - New verbs: `/mode focus <task>`, `/mode focus off`, `/mode clear-blocked`. `/mode get` prints the daemon mode plus this session's modes, keyed by `CLAUDE_CODE_SESSION_ID` from `invoke.sh`.
   - Keep the `DaemonMode` enum. Don't rename the skill.
   - The `health` response gains `session_modes_count` and nothing else, because health is not per session.
3. **Status line.** Add a new `session_mode_indicator` segment that reads the registry in-process using the status input's `session_id`. It also finally shows daemon `unattended` (F8). It needs a `SegmentExplanation` entry for `status-line-explained`. `environment_indicator`'s "no autonomy" stays where it is.
4. **These stay separate:** `release_blocker` (a guard; a release that is part done is not a mood), `orchestrator_simulate`, `cron_pause`, the `ask_user_question_blocker` mode option, the usage-pause *storage* (shown, not migrated), `permission_mode`, and the guards in general.
5. **Supervisor.**
   - Add one new reader, `load_session_modes`, pinned to the daemon's field names by a `tests/unit/supervise/` test like the others.
   - Add a gate in `decide_once` after the usage-pause check that skips the goal, session-actions and standing-auth families (and `continue`, if open question 7 says so).
   - The goal-clear priority change from 3.2.
   - The edit has to be followed by the hot-reload check in `.claude/rules/ccy-supervisor-dogfooding.md`.

## 5. Revised phases and tasks (TDD, smallest first)

**Recommendation:** rename the plan to **"00501 session modes (focus, blocked, goal-loop)"**. Keep the number and issue #91, and add a journal `decision` entry. The work is no longer one feature.

**Phase 0: spikes and evidence (no production code)**
- 0.1 Fold this report into the plan. Correct the fact-checker's R1–R3 and add F1–F9.
- 0.2 Spike: capture real Stop payloads during a `/goal` re-arm, including `stop_hook_active` and record order. A script over the existing transcripts and `stop-events.jsonl` is enough.
- 0.3 Spike: does a Stop `continue:false` end the turn while `/goal` is active? Does a typed `/goal clear` mid-turn queue?

**Phase 1: the model (pure, no behaviour change)**
- 1.1 TDD `utils/session_modes.py`: enum, entries, `SessionPolicy` union and precedence, `drops_tick` truth table.
- 1.2 TDD `SessionModeRegistry`: thread safety, write-through file, lifetime classes on load, restart note, TTL, reap.
- 1.3 TDD `autonomy_verdict` with session modes, plus `explain()` wording. Verify both routes are covered: the chain test plus the 3 direct-call tests.

**Phase 2: awaiting-human folds in, and the bug fixes (small, shippable alone)**
- 2.1 TDD: the suppressor clears only on a genuine human prompt in the same session (F1, F2). Regression tests for cross-session and supervisor-typed prompts.
- 2.2 TDD: `auto_continue_stop` writes the registry. Legacy marker import. The suppressor reads `policy.drops_tick`.
- 2.3 TDD: `UnattendedModeInterceptor` stands down while BLOCKED or usage-paused.

**Phase 3: focus**
- 3.1 TDD a UserPromptSubmit `session_mode_trigger`: spelling tolerance (`hooks-daemon`, `hooks daemon`, `hooks demon`), `off` aliases, anchored to the start of the prompt (the Plan 00228 lesson: never match prose about the trigger). One context line. The prompt still reaches the model.
- 3.2 TDD focus tick-drop through the suppressor. The goal-ledger challenge is replaced by the focus reminder.
- 3.3 TDD `/mode focus` and `session-mode` CLI and IPC.

**Phase 4: visibility**
- 4.1 TDD `session_mode_indicator` segment and its explanation entry.
- 4.2 Restart notice (only if open question 1 keeps "restart clears").
- 4.3 `session-modes.jsonl` and the `hooks-daemon session-modes` CLI.

**Phase 5: supervisor**
- 5.1 TDD `load_session_modes` and the `decide_once` gate. Field-pin test.
- 5.2 TDD goal-clear outranks goal-intent under BLOCKED; the busy-session clear rule from spike 0.3.

**Phase 6: goal-loop detector**
- 6.1 TDD transcript extraction (`goal_status`, genuine-human, stop text) from fixture records copied from real transcripts with text scrubbed.
- 6.2 TDD the cycle ring, similarity, repo fingerprint with `ignore_paths`, thresholds, `observe` mode, near-miss logging.
- 6.3 TDD `act` mode: enter BLOCKED(goal-loop), `clear_goal_signal`, one-time context line, optional halt (from spike 0.3).
- 6.4 Exits: human prompt, repo change (checked at UPS and at Stop), timer.

**Phase 7: docs and acceptance**
- 7.1 `get_claude_md()` for the new handlers. Autonomy docs gain a "Session modes" section. Release note in UNRELEASED (after the release commit lands).
- 7.2 Acceptance:
  - focus on → tick dropped → focus off;
  - `[awaiting-human]` in session A is not cleared by session B;
  - a live dogfood `/goal` loop in observe mode, then in act mode.
- 7.3 After a week in `observe`: tune thresholds from `session-modes.jsonl`, then flip the default to `act` in a follow-up.

## 6. Open questions for the owner (with recommended defaults)

1. **Does a daemon restart clear focus?** You asked for it to. But restarts follow most merges, and a focused session is often the one doing the merge. **Recommended:** focus is *session*-lifetime. It survives a daemon restart and is cleared by `off`, a new session id, or the TTL in question 2. "Nothing persisted" still holds: the only record is a per-session runtime file that dies with the session. If you keep "restart clears", the lifetime is a one-line class change and the restart notice (Task 4.2) is mandatory.
2. **Focus TTL?** **Recommended:** 12 h, renewed by each genuine human prompt in the session.
3. **Merge goal-blocked into awaiting-human?** **Recommended:** yes. One `BLOCKED` family with two reasons and two badges (2.2).
4. **Does focus drop the failsafe tick?** **Recommended:** yes. Its prompt says "resume the active plan", which is the distraction. A rate-limited focused session recovers when the human next types.
5. **Should `unattended` become per session?** **Recommended:** not in this plan. Show it on the badge now. Open a follow-up if two sessions of one project ever need different values.
6. **Should entering focus also `/goal clear` an existing goal?** **Recommended:** yes, once. A live `/goal` for other plans is the strongest pull away from the focus task.
7. **Under BLOCKED, should the supervisor's post-compact `continue` be suppressed?** **Recommended:** yes. `/compact` still runs, but a blocked session should not be told to continue.
8. **Goal-loop rollout:** `observe` by default for one release? **Recommended:** yes, with thresholds 3 cycles (2 if declared) / 30 min / similarity 0.75 / repo-unchanged excluding JOURNAL, and a 4 h timer.
9. **Should the detector use a Stop `continue:false` halt if spike 0.3 shows it works?** **Recommended:** yes, once per entry, logged, never repeated.
10. **Rename the plan to "session modes"?** **Recommended:** yes, keeping 00501 and #91.

### Critical files for implementation
- /workspace/src/claude_code_hooks_daemon/utils/autonomy.py
- /workspace/src/claude_code_hooks_daemon/handlers/user_prompt_submit/failsafe_cron_blockage_suppressor.py
- /workspace/src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py
- /workspace/.claude/ccy/claude-supervise.py (`decide_once` around 6846 and 7213–7318)
- /workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py (`clear_goal_signal`), plus /workspace/src/claude_code_hooks_daemon/core/mode_interceptor.py and /workspace/src/claude_code_hooks_daemon/utils/blockage_marker.py

---

**Path:** `/workspace/untracked/agent-reports/261008-session-modes-design-opus.md`. Not written, because this agent has no write tool. Please save the text above there.

**Summary:**
1. **Recommendation:** yes, make per-session modes a first-class concept and rename the plan to "session modes". The modes are `focus`, `BLOCKED` (awaiting-human or goal-blocked) and `usage-paused`, with daemon `unattended` shown on the badge. Modes combine: their suppressions add up, and a mode that halts work beats one that drives it.
2. **Bug (F1):** today's `[awaiting-human]` marker is one project-wide file, and any prompt from any session clears it (`failsafe_cron_blockage_suppressor.py:311-319`).
3. **Bug (F2):** the supervisor's own `continue` and `/goal` lines also clear it, because the suppressor only checks tick sentinels. Phase 2 fixes both and ships on its own.
4. **Gap (F3):** the supervisor never reads the awaiting-human marker, so it can type `/goal` into a session that says it is blocked.
5. **Loop detection:** do it in the daemon, not the supervisor. Claude Code writes `goal_status` records (`met:false` plus a reason) into the transcript, and the supervisor never sees screen text.
6. **Re-entry:** the loop's turns come back as Stop-hook re-entries, which `auto_continue_stop` skips. So the detector has to be a separate Stop handler that also runs on re-entry.
7. **Breaking the loop:** reuse the existing `clear_goal_signal` → `/goal clear` channel. Spikes are needed on whether a Stop `continue:false` beats `/goal`, and whether a mid-turn `/goal clear` gets queued.
8. **Supervisor channel:** a per-session `context-sidecar/<sid>.session-modes` file written by the daemon. This replaces the plan's socket idea, which would be a new pattern for the stdlib-only supervisor.
9. **Persistence:** recommend focus lasts for the session and survives daemon restarts, because restarts follow most merges. This needs your sign-off, since it changes what you asked for. BLOCKED survives restarts (as awaiting-human does today). The detector ships in log-only `observe` mode first, logging to `session-modes.jsonl`, so thresholds can be tuned.
10. **What doesn't change:** the `/mode` skill and its IPC stay compatible (it gains `focus` verbs), `release_blocker` and the other guards stay separate, and the 10 owner questions each have a recommended default.