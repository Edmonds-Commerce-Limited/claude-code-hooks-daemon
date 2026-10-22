# Research: The Daemon's Couplings to Claude Code (refresh of Plan 00292)

Plan 00549, Task 1.4. Research only. Read from this repository at `main` commit `dfdf77c8e` (2026-10-22). Every path
below is relative to `/workspace`; `src/` means `src/claude_code_hooks_daemon/`. Line numbers are from that commit.

Starting material: Plan 00292's
[`RESEARCH-daemon-couplings.md`](../00292-codex-cli-dual-host-research/RESEARCH-daemon-couplings.md) (ten
couplings, ranked easy/medium/hard/fundamental) and its
[`OPTIONS-abstraction.md`](../00292-codex-cli-dual-host-research/OPTIONS-abstraction.md) (recommendation:
build toward a host-adapter layer at the front controller, Option A, with a verdict-degradation mode, Option D, from
day one; lines 429-466). This document does not research opencode. Other Phase 1 documents cover it.

## Classification used here

The brief asks for a coarser scale than 00292's, aimed at what an adapter can absorb:

- **N, host-neutral core**: works unchanged for any host that can run a command per event, or is pure daemon logic.
- **A, thin adapter could cover**: a data table, a field rename, a serializer swap or a different deploy target. It
  needs work per host, but the daemon's internal model does not change.
- **D, deep Claude Code dependency**: the feature exists because of a Claude Code behaviour (a tool, a field, a
  re-entry contract, a TUI, a file format). A second host either offers an equivalent or the feature is lost.

Each 00292 coupling also gets a refresh verdict: **STILL TRUE**, **CHANGED** (still a coupling, but its shape or size
moved), or **GONE** (the 00292 claim no longer holds).

## Part 1: The ten 00292 couplings, re-checked

### R1. Event catalogue: STILL TRUE, grown. Class A

- `src/constants/events.py:24-69`: `EventType` is a literal list of Claude Code hook names. The `Status` wire name
  differs from the catalogue `json_key` `StatusLine` (`events.py:30-33`, `188-202`, `565-570`).
- 34 `EventIDMeta` entries now exist (`events.py:217-562`). 31 are wired. Three are not: `DirectoryAdded`
  (`:477`), `PreModelSwitch` (`:537-549`) and `PostModelSwitch` (`:551-562`). The model-switch events are new since
  00292 and are documented as "Claude Code v2.1.251" (`:544`). 00292 said 31 of 32; the count is now 31 of 34.
  `.claude/hooks/` holds 31 forwarders plus a `handlers/` directory.
- New host-quirk fields on `EventIDMeta` (`events.py:123-169`): `raw_stdout`, `requires_client_translation` (the
  Stop exit-code translation), `daemon_down_stdout`, `daemon_down_exit_code` and `daemon_loading_stdout`. Each one
  encodes how Claude Code reads one hook's stdout or exit code. Derived from them are `relay_eligible` (`:171-186`),
  `relay_ineligible_bash_keys()` (`:595-604`) and `raw_stdout_bash_keys()` (`:607-619`).
- The per-event handler registry is keyed by event directory: `src/handlers/registry.py:57` (`EVENT_TYPE_MAPPING`,
  `"pre_tool_use": EventType.PRE_TOOL_USE`, ...). The handler counts per directory are pre_tool_use 82,
  session_start 36, status_line 25, post_tool_use 17, stop 7, subagent_stop 7, user_prompt_submit 10, and fewer
  than 4 for each remaining event.
- Why A: names and flags are data. Two of the flags (`raw_stdout`, `requires_client_translation`) describe Claude
  Code quirks that a second host's table would carry with different values. That is a parallel table, not a model
  change.

### R2. `HookInput` / `ToolInput` models: CHANGED. Class A

- `src/core/event.py` shrank to 164 lines. `ToolInput` is at `:20`. `HookInput` (`:37-60`) now splits each alias
  into a validation alias and a serialization alias (`toolName`, `toolInput`, `sessionId`, `transcriptPath`). The
  Claude-tool accessors `is_bash_tool` / `is_write_tool` / `is_edit_tool` / `is_read_tool` are at `:126-141`.
- Most handlers do not go through these models. They read raw `hook_input` dict keys named in
  `src/constants/protocol.py:44-133` (`HookInputField`). That catalogue grew a lot after 00292, and every new field
  is a Claude Code payload field:
  - `scratchpad_dir` (`:52`)
  - `tool_response` and `tool_use_id` (`:83-84`)
  - `session_name`, `session_metadata` and `session_statistics` (`:91-93`)
  - `agent_id`, `agent_type` and `agent_transcript_path` (`:96-98`)
  - `session_crons` (`:103`) and `background_tasks` (`:109`), both described as "CONDITIONAL"
  - `trigger` and `custom_instructions` (`:114-115`)
  - `permission_suggestions` (`:123`) and `error` (`:133`)
- Four fields are daemon-stamped, not host-sent: `hooks_daemon_hostname`, `hooks_daemon_raw_text`,
  `terminal_columns`/`terminal_lines` and `hooks_daemon_peer_pid` (`:58-71`).
- Why A: an adapter can populate the same dict keys. But this is more of a payload than 00292 assessed, and several
  of its fields (crons, background tasks, agent transcript) feed class-D features (B5, B8, B19).

### R3. Verdict-to-wire response contract: STILL TRUE, larger. Class A (serializers), N (`Decision`/`HookResult`)

- `src/core/hook_result.py` is 1,280 lines. The internal `Decision` enum (`:18-28`) and `HookResult` stay
  host-neutral.
- The per-event closed sets are at `:86` (`_TOP_LEVEL_BLOCK_EXTRA_EVENTS`), `:100` (`_HSO_CONTEXT_EXTRA_EVENTS`) and
  `:104` (`_CONTINUE_FALSE_EVENTS`). `REFUSAL_CAPABLE_EVENTS` is at `:127-160`. `_build_wire_response` starts at
  `:565`.
- The per-event formatters:
  - PreToolUse `:676`, with `permissionDecision`, `updatedInput` (`:699`, new since 00292) and `defer`. A top-level
    `continue:false`/`stopReason` halt is also new (`:709-712`).
  - PostToolUse `:715`
  - Stop `:743`, with the `stop_hook_active` loop-breaker that still cites "Sev-1 shipped in v3.31.0" (`:751-795`)
  - PermissionRequest `:796`, DUAL-CHANNEL at `:812`
  - UserPromptSubmit `:837`
  - top-level block `:869`
  - `continue:false` `:904`
  - context-only `:926`
  - SessionStart `:957`, with `systemMessage` plus `additionalContext`
  - systemMessage-only `:989`
- Two events do not answer in decision JSON. Status returns `{"text"}` (`:609-627`). WorktreeCreate returns
  `{"worktreePath"}` (`:80`, `:629-633`).
- New since 00292: `src/core/response_schemas.py` (554 lines, per-event JSON schemas) and
  `src/core/decision_capability.py` (151 lines). The latter states "Only 13 events have a bespoke response schema;
  the other 18 wired events fall back to `_permissive_response_schema()`" (`:14-20`).
- New since 00292: the vendored Claude Code hook contracts in `contracts/claude-code-hooks/*.json` (see B1).
- Why A and not D: the 00292 conclusion holds. A second host needs a second serializer behind the same `HookResult`.
  The size of that serializer (about 450 lines plus the schemas) is the cost.

### R4. Front controller stdin/stdout loop: CHANGED. Class N

- `FrontController.run()` still exists (`src/core/front_controller.py:183-225`). It reads `stop_hook_active` at
  `:216-217` and `terminal_columns` at `:222`.
- The live hot path is now the socket server: `src/daemon/server.py:2475` `_process_request`, with the envelope
  `event`/`hook_input` at `:2507-2508`. The same two Claude-specific reads are repeated there (`:2578-2584`) and in
  `src/daemon/controller.py:1361-1369`.
- Why N: dispatch is generic. The two reads are optional fields.

### R5. settings.json registration: STILL TRUE. Class D (mechanism), A (per-event data)

- `install.py:756` `create_settings_json` and `install.py:356` `_DAEMON_FORWARDER_HOOKS` (still a hand-kept copy;
  `:779-788` admits it).
- `src/utils/hook_registration.py:337`: `HOOK_COMMAND_TEMPLATE = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/{bash_key}'`.
- `src/install/settings_merge.py:56-57` (the `hooks` and `statusLine` keys), plus `src/utils/settings_repair.py`,
  `src/utils/hook_command_migration.py` and the SessionStart `hook_registration_checker`.
- The live `.claude/settings.json` registers each event as
  `[{"hooks":[{"type":"command","command":"bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/<key>","timeout":60}]}]`. The
  status line is registered as `statusLine` with `refreshInterval: 1`.
- Why D: the host reads this file and spawns the commands. Without an equivalent registration surface on the other
  host, nothing fires.

### R6. `init.sh` and the bash forwarders: CHANGED. Class A (the exit-2 translation is D)

- `.claude/init.sh` grew from 1,269 to 3,780 lines. The lifecycle code is still host-neutral: `ensure_daemon`
  `:2733`, `start_daemon` `:1973` and `_get_hostname_suffix` `:1462`.
- The Claude-specific parts:
  - The status request is stamped `hook_event_name='Status'` and given `COLUMNS`/`LINES` (`:3511-3518`, citing
    "Claude Code clients (\<2.1.153)").
  - `forward_stop_event` (`:3666-3780`) still turns a block verdict into exit 2 plus stderr text, citing "Claude Code
    v2.1.114".
  - `emit_hook_error` (`:639`) messages tell the agent to use "Skill tool: skill=hooks-daemon".
- Forwarders are now generated by `src/install/forwarder_generator.py`:
  - a relay hot-path guard (`:256` `build_relay_guard_block`)
  - a bash status fast path (`:415`, Plan 00542)
  - project-root absolute paths baked in (`:615` `normalise_project_root`)
- A forwarder now carries host knowledge in bash too. See `.claude/hooks/status-line`, which builds JSON in bash and
  expects a `\x1e` sentinel reply. `.claude/hooks/stop` exits 2 on block.
- Why A: a new forwarder family per host. The exit-code contract is per host, so it is D in that only Claude Code's
  version is known.

### R7. Transcript-path convention: CHANGED, much deeper. Class D

- 00292 listed about 10 consumers. Now about 90 modules mention `transcript_path`.
- The largest new use is not reading transcripts. It is `transcript_path` as the per-agent identity key.
  `src/core/disclosure_tracker.py:11-26` ("Per-agent via transcript_path: session_id is shared across all Task ...
  transcript_path IS per-agent") drives the "verbose the first time, terse after" output of most PreToolUse
  handlers. Examples are `src/handlers/pre_tool_use/sed_blocker.py:436-450` and `plan_number_helper.py:182-189`.
- The JSONL parsing assumes Claude Code's record shapes (`src/core/transcript_reader.py:222-223`, `:321-345`,
  `:389-399`: `type` = message/assistant/user/tool_use and `content` blocks), with a 1 MiB tail window (`:34`).
- The parser has 18 direct users, plus `src/utils/transcript_tail.py` (context size per agent),
  `transcript_spend.py` (token spend) and `session_load.py`.
- Where Claude Code keeps transcripts is resolved by `src/utils/claude_config.py:1-30` (`$CLAUDE_CONFIG_DIR` or
  `~/.claude/projects`).
- Why D: the stop gates (B4), the sub-agent context budget (B8) and spend tracking all read a Claude Code JSONL file.
  The disclosure-tracker identity use could be met by any per-agent id, so that part alone is A.

### R8. Status line: STILL TRUE, larger. Class D

- There are now 25 modules in `src/handlers/status_line/`.
- `settings_reader.py:42-47` now resolves the user settings file through `claude_config_dir()`, so
  `$CLAUDE_CONFIG_DIR` is honoured. That is a fix to 00292's "no abstraction point", but the file is still Claude
  Code's.
- `model_context.py:3-34` still holds the Haiku/Sonnet/Opus colours and reads `hook_input["effort"]["level"]`, with
  `effortLevel` as a fallback.
- New: `src/core/usage_snapshot.py:4-10`, `:56` reads `rate_limits.five_hour` and `seven_day` from the status-line
  payload. That snapshot feeds the usage-pause machinery (B18), so the status-line payload is now load-bearing for
  enforcement, not just display.
- Why D: the feature is a Claude Code UI surface fed by a Claude Code payload.

### R9. `permission_mode` vocabulary: STILL TRUE. Class A

`src/utils/permission_mode.py:1-31` recognises five Claude Code mode strings. The only one acted on is
`bypassPermissions` (`:18`). Anything unknown fails safe.

### R10. Rust socket relay: CHANGED. "Pure byte pump" no longer holds. Class N, with a small A carve-out

- `relay/hooks_relay.rs:11-29` lists one policy carve-out. On a failed PreToolUse exchange the relay fabricates a deny
  in Claude Code's `hookSpecificOutput.permissionDecision` shape (`:222-260`). It knows the event only from the
  socket filename `pre-tool-use.sock` (`:222-224`). It also carries a minimal JSON parser for validating responses
  (`:404-504`).
- Other host-specific details in the relay:
  - the `.claude/hooks-daemon/bin/hooks-daemon` launcher path (`:115`)
  - a `.claude` parent check (`:310`, `:343`)
  - `HANDOFF_TIMEOUT_MS` (`:98-103`), sized "before Claude Code cancels the hook"
- Raw-stdout and Stop events are excluded from the relay by `relay_eligible` (R1).
- The server binds one listener per wired event (`src/daemon/server.py:1738-1792`) and stamps the peer pid from
  `SO_PEERCRED` (`:241-254`).
- Why N with an A carve-out: the transport still works for any host that execs a command per event. The fail-closed
  deny body and the launcher paths would need a per-host variant.

## Part 2: Couplings new since (or missed by) 00292

### B1. Vendored Claude Code contracts. Class A

- `contracts/claude-code-hooks/` holds one JSON per event (33 events) plus `ALLOWLIST.yaml` and
  `INPUT-ALLOWLIST.yaml`.
- `META.json` records the source: `docs_url` `https://code.claude.com/docs/en/hooks.md`,
  `last_audited_claude_code_version` `2.1.296`, and the refresh procedure in
  `docs/guides/HOOK-CONTRACT-REFRESH.md`.
- `contracts/claude-code-instructions/` holds `FACTS.json` and `META.json`, sourced from
  `https://code.claude.com/docs/en/memory` at 2.1.302.
- SessionStart `contract_staleness` checks freshness, and the tests validate against these contracts.
- A second host needs its own contract set and refresh routine. This is a good pattern to copy.

### B2. Claude Code tool vocabulary in handlers. Class A for file and shell tools

- `src/constants/tools.py:25-102` defines `ToolName`:
  - Bash, Write, Edit, Read, Glob, Grep, WebSearch, WebFetch
  - Task and Agent, the two names for sub-agent dispatch (`:58-61`, `SUBAGENT_DISPATCH_TOOL_NAMES` at `:140`)
  - Workflow, TaskCreate/Update/Get/List/Output/Stop, SendMessage, Skill
  - EnterPlanMode/ExitPlanMode, AskUserQuestion, NotebookEdit, LSP, Artifact
  - CronCreate/Delete/List, ToolSearch
- 74 handler modules match a tool by name or field, including 59 of the 81 PreToolUse modules (a file-level grep count; `__init__.py` excluded).
- `ToolInput` field names are Claude's: `command`, `file_path`, `content`, `old_string`, `new_string`.
- Why A: the core guards (destructive git, sed, pipe, secret file, TDD, QA suppression, sensitive content, plan
  number) need only "shell command" and "file write/edit with path and content". A host whose file-edit tool uses a
  different shape (for example a patch format) would need the adapter to synthesise `content`/`new_string`. That is
  real work, but it is adapter work.
- The Claude-only tools are split out as B27.

### B3. Guidance prose naming Claude Code tools. Class A

- Deny and advisory texts tell the agent to "Use the Edit tool" or to call the `Read` tool with offset/limit (seen
  in this session's sed_blocker deny).
- `init.sh:639` `emit_hook_error` says "Skill tool: skill=hooks-daemon".
- The rule tables injected into CLAUDE.md (B12) name `Write`/`Edit`/`Task`/`CronCreate` throughout.
- A host-aware renderer, or neutral wording, would cover this. The amount of text is large.

### B4. The stop-gate family: Stop/SubagentStop block-and-re-enter. Class D

- `src/handlers/stop/auto_continue_stop.py` (1,507 lines) does the following:
  - parses the last assistant message for `STOPPING BECAUSE:` (`:1-23`)
  - reads the transcript (`:263`) and `stop_hook_active` (`:1313`)
  - exempts `AskUserQuestion` (`:732`, `:783`)
  - includes the `[awaiting-human]` stand-in requirement (CronCreate, `:430`)
- Other Stop handlers: `cron_stop_enforcer`, `idle_workable_issue_stop_gate`, `usage_pause_stop_gate`,
  `background_task_recorder` and `teammate_reap_advisor`. SubagentStop has 6 handlers (B8).
- Everything depends on three Claude Code behaviours:
  1. A Stop hook can refuse the stop.
  2. The refusal reason is fed back to the model as its next turn.
  3. `stop_hook_active` marks the re-entry (the loop-breaker is in `hook_result.py:743-795`; the exit-2 path is in
     `init.sh:3705`).
- Without all three, the "agent must explain its stop" contract cannot be enforced.

### B5. Session crons. Class D

- The machinery:
  - `persistent_cron_assertor` (SessionStart) tells the agent to call `CronCreate` (`:3`, `:189`).
  - `cron_record_keeper` (PostToolUse on CronCreate/CronDelete) records what was created.
  - `cron_stop_enforcer` reads `session_crons` (`:249`), with conditional semantics described in
    `src/utils/cron_enforcement.py:4-14`.
  - `cron_subagent_stop_enforcer` and `subagent_cron_delete_blocker` (PreToolUse) cover sub-agents.
  - Helpers: `src/utils/cron_tick.py` (the `[tick:...]` prompt sentinel), `cron_records.py`, `cron_refresh.py`,
    `stand_in_cron.py` and `session_thread_group.py`.
  - `failsafe_cron_blockage_suppressor` (UserPromptSubmit) blocks a delivered tick prompt.
- It all depends on Claude Code's in-session cron tools and on the `session_crons` Stop field. It drives the
  unattended loop, the failsafe tick and the `[awaiting-human]` stand-in.

### B6. `/goal` injection and the goal ledger. Class D

- `src/utils/goal_ledger.py:3` (812 lines): "Claude Code's `/goal` slot holds exactly ONE session-scoped condition".
- `src/handlers/post_tool_use/goal_injection.py:1-12`: a PLAN.md Status flip to In Progress writes a
  `<session>.goal-intent` file. The ccy supervisor then types `/goal ...` into the chat (B7). Resume handling relies
  on Claude Code `--resume`/`--continue` keeping the session id (`:55-56`).
- This is a Claude Code slash command delivered by TUI typing.

### B7. The ccy supervisor. Class D

- `.claude/ccy/claude-supervise.py:8` is "a standalone, stdlib-only PTY supervisor for wrapping `claude`" (`import pty` at `:208`). It injects text when Claude Code's TUI is idle with an empty input box (`:23-24`, `:55`).
- Supporting code:
  - `src/utils/ccy_supervisor.py:1-40` (liveness and arming; launcher name `claude-supervise`, env
    `CCY_CLAUDE_WRAPPER`)
  - `src/install/ccy_supervisor.py`
  - the SessionStart `ccy_supervisor_integrity` handler
  - the signal files it consumes: `session_actions_signal.py`, `usage_pause.py` and the goal intent from B6
- This screen-scrapes and types into one specific TUI. Porting it means a new supervisor or an API-driven equivalent.

### B8. Sub-agent machinery. Class D

- SubagentStop handlers:
  - `subagent_report_persistence` saves `last_assistant_message` (`:164`) keyed by `agent_id`/`agent_type`
    (`:181-182`).
  - `subagent_report_size_blocker` and `subagent_report_path_verifier`
  - `subagent_handoff_gate` (`agent_id` `:87`)
  - `subagent_cache_aggregator` (reads the transcript)
- PreToolUse guards: `subagent_context_budget` (uses `transcript_tail`), `resume_guard` (SendMessage) and
  `spawn_rate_advisor`.
- Resolvers:
  - `src/utils/subagent_tool_resolution.py` reads `.claude/agents/*.md` frontmatter.
  - `agent_dispatch_registry.py` maps name to definition type.
  - `dispatch_tier.py` encodes "Claude Code resolves a subagent's model in a fixed order (sub-agents.md)".
- All of this rests on Claude Code's Task/Agent tool, its SubagentStop payload and per-agent transcripts.

### B9. `AskUserQuestion` and the unattended mode. Class D

`src/handlers/pre_tool_use/ask_user_question_blocker.py:187` matches `ToolName.ASK_USER_QUESTION` and reads the
transcript (`:278`). It uses `scratchpad_dir` as a context signal (`:28`) and `src/utils/human_presence.py` for
presence detection. The stop gate exempts this tool (B4).

### B10. `plansDirectory` sync. Class A

`src/handlers/pre_tool_use/markdown_organization.py:123-129` and `:533-534` handle "flat file writes ... written by
Claude Code when plansDirectory is set". `src/config/models.py:989-1023` has `enforce_claude_code_sync`. This
targets one Claude Code settings key and can be switched off per host.

### B11. Plan workflow assets themselves. Class N

- The pieces are `src/install/templates/mkplan.bash`, `_planlib.inc.bash`, the templates, `src/plan_qa/`, the plan
  journal, and `bin/hooks-daemon find-plan`. These are bash, Python and git.
- The enforcement is host-neutral as long as the host offers PreToolUse-style gates on shell commands and file
  writes:
  - PreToolUse `plan_number_helper`, `plan_journal_guard`, `plan_qa_edit`, `plan_time_estimates` and
    `plan_close_approval`
  - commit-time `plan_qa_commit_gate`
- The parts that are not host-neutral are the delivery of guidance (B12) and the `/goal`/stop gates (B4, B6).

### B12. CLAUDE.md generated block. Class A

- `src/core/claude_md_injector.py:1-11`, with the tags at `:33-34`, writes `<hooksdaemon>...</hooksdaemon>` into
  the project `CLAUDE.md` on daemon start.
- Facts about which instruction files Claude Code loads are vendored in `contracts/claude-code-instructions/` (B1).
- The target filename and the loader rules are per host. The content is generated from handlers and is neutral,
  apart from the tool names in B3.

### B13. Skills, agents and rules deployment. Class A

- Skills: `src/install/skills.py:4`, `:80` ("Claude Code discovers skills by ..."), `:107`.
- Agents: `src/install/agent_assets.py:4`.
- `src/install/client_owned_assets.py:158-182` ("Claude Code discovers skills under .claude/skills/"; "discovers
  sub-agents only under .claude/agents/").
- `.claude/rules/*.md` is used for path-scoped rules, as shown by the system reminders in this session.
- Agent frontmatter fields (`tools`, `model`) follow the Claude Code schema.
- A second host needs its own deploy targets and its own frontmatter dialect.

### B14. `.claude/` as the install root. Class A

- `src/constants/paths.py:24` (`CLAUDE_DIR = ".claude"`) and `:111` (`.claude/worktrees`, "Claude Code managed
  worktrees (not configurable)").
- 57 source modules contain the literal `".claude"`.
- `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon/` (the clone), `.claude/init.sh` and `.claude/hooks/` all live
  there.
- The daemon could keep `.claude/` for its own files on any host. Only the host-discovered paths move.

### B15. Claude Code config-dir knowledge. Class A

`src/utils/claude_config.py:1-30` locates user settings, user agents and skills, transcripts and plugins under
`$CLAUDE_CONFIG_DIR` or `~/.claude`. One module, so it is easy to give a per-host twin.

### B16. Claude Code plugins. Class A

`src/utils/claude_plugins.py`, `plugin_hooks.py`, the SessionStart `plugin_hooks_advisor` and the PreToolUse
`installed_plugin_edit_advisor` model Claude Code's plugin system. All are advisory, so they can be dropped per host.

### B17. Anthropic model and pricing vocabulary. Class D (but optional)

- The modules involved:
  - `src/utils/model_tiers.py` (the family rank table)
  - `model_downgrade_signal.py` ("Claude Code records its own safety-classifier model substitutions")
  - `model_fallback_records.py` and the `model_fallback_detector` handler
  - `prompt_cache_ttl.py` (Claude Code's per-request cache TTL)
  - `transcript_spend.py` and `spend_ledger.py`
  - the PostToolUse handlers `dispatch_model_recorder` and `model_downgrade_recorder`
- These features exist because of Claude and Anthropic behaviour. On another host they are either rebuilt against
  that host's provider data or switched off. No core guard depends on them.

### B18. Usage ceiling and usage pause. Class D

- The chain: `usage_snapshot.py` reads `rate_limits` from the status-line payload (R8). Then `host_usage_ceiling.py`
  applies the limit, `usage_pause_gate.py` decides, and the `usage_pause_gate` UserPromptSubmit handler and the
  `usage_pause_stop_gate` Stop handler act.
- While paused, PreToolUse allows only CronCreate/CronDelete/CronList/SendMessage/TaskStop/ToolSearch (rule
  R-USAGE-PAUSE-TOOL in CLAUDE.md).
- Every link depends on Claude subscription telemetry and Claude Code tools.

### B19. Background tasks and teammates. Class D

- Stop's `background_tasks` (`protocol.py:105-109`, "an in-process teammate that has gone IDLE is still listed with
  status running") feeds `session_load.py`, `background_task_recorder` and `teammate_reap_advisor`.
- TeammateIdle and TaskCompleted use the `continue:false` refusal (`hook_result.py:104`, `:904`).
- These are Claude Code agent-team concepts.

### B20. Worktree events. Class A (the event's raw-stdout quirk is D)

- WorktreeCreate expects a raw path on stdout (`hook_result.py:629-633`; `events.py:123-130`, Plan 00188).
- `src/handlers/worktree_create/worktree_create_handler.py` reads `name`, `cwd` and `session_id` (`:47`,
  `:108-111`).
- The naming, seeding and reaping logic (`src/core/worktree_*.py`) is neutral and git-based.

### B21. Peer pid and session thread grouping. Class N

`server.py:241-254` uses `SO_PEERCRED`. `src/utils/session_thread_group.py` tells threads of one session apart. Both
assume one hook process per event, which is true of any exec-per-event host.

### B22. `scratchpad_dir` allowance. Class A

`src/handlers/pre_tool_use/project_containment.py:114`, `:477` allow writes into the scratch directory the harness
names. A host without one falls back to `untracked/scratch/`.

### B23. PermissionRequest auto-approve. Class A

The `src/handlers/permission_request/auto_approve_reads.py` handler emits the dual-channel response
(`hook_result.py:796-836`). This only matters if the host has a permission-prompt hook.

### B24. Limits, quota and StopFailure. Class D

`stop_failure_recorder` (StopFailure), `stop_failure_resolver` (UserPromptSubmit), `quota_resume_recorder`
(Notification) and `src/utils/limit_events.py` / `stop_failure_records.py` all record Claude Code's usage-limit kill
and resume behaviour.

### B25. Daemon lifecycle, hostname-suffixed sockets, venv. Class N

`init.sh` `ensure_daemon` (`:2733`), `_get_hostname_suffix` (`:1462`), `validate_venv` (`:1666`), the per-event
socket directory (`server.py:1760`) and `scripts/venv_bootstrap.sh` carry no host knowledge.

### B26. Install, upgrade and provision paths. Class A

- `install.sh`, `install.py` (`create_all_hooks` `:700`, `create_settings_json` `:756`), `provision.sh`,
  `scripts/upgrade.sh` and `src/install/*` all write the Claude Code registration surface (R5) and the deploy targets
  (B13).
- The documented install route is an LLM driving `CLAUDE/LLM-INSTALL.md` through the `hooks-daemon` skill.
- The transport setup (`transport_toggle.py`, `relay_deploy.py`, `transport_verify.py`) is neutral.

### B27. Claude-only tool features. Class D

- Several handlers exist only because Claude Code has the tool:
  - `artifact_publish_blocker` (Artifact)
  - `src/utils/workflow_fanout.py` (Workflow scripts' `agent()` calls fire no PreToolUse)
  - the `lsp_enforcement` redirect to the LSP tool
  - `tool_disable_advisor`
  - the ToolSearch allowance in the usage pause
  - `resume_guard` (SendMessage)
- There is nothing to port unless the other host has the same tools.

### B28. SessionStart context delivery. Class A

- SessionStart answers with `systemMessage` plus `hookSpecificOutput.additionalContext` (`hook_result.py:957-987`).
- There are 36 SessionStart handlers, many of them advisories. Tiering is in `src/core/session_start_tiers.py`.
- `session_actions_signal.py` routes the must-do list through the supervisor because of a Claude Code delivery
  problem (Plan 00416).
- A host needs some way to inject context at session start.

### B29. Compaction. Class A

The PreCompact `compaction_signal` and `disclosure_reset_pre_compact` handlers read `trigger` and
`custom_instructions`. PostCompact is wired with no handlers. A host with any compaction hook could be mapped onto
these.

### B30. Acceptance and probe harnesses. Class A

`src/core/cli_acceptance_test.py`, `acceptance_test.py`, `daemon/hook_probe.py`, `daemon/synthetic_traffic.py` and
the `acceptance-test` skill ("execute handler tests via real Claude Code tool calls"). The probes send Claude-shaped
payloads. A host-specific test harness is needed.

### B31. Timeout budget tuned to Claude Code. Class A

The settings `timeout: 60` and the relay caps (`hooks_relay.rs:70-77`, `:98-103`: a 45 s cap and a 10 s handoff "ends
before Claude Code cancels the hook -- a cancelled PreToolUse hook lets the call run unjudged"). The values are per
host. Whether the other host treats a cancelled pre-hook as allow or deny decides how much this matters.

## Counts

41 couplings: 10 re-checked from 00292 plus 31 new.

| Class                          | Count | Items                                                                                                |
| ------------------------------ | ----- | ---------------------------------------------------------------------------------------------------- |
| N: host-neutral core           | 5     | R4, R10, B11, B21, B25                                                                               |
| A: thin adapter could cover    | 22    | R1, R2, R3, R6, R9, B1, B2, B3, B10, B12, B13, B14, B15, B16, B20, B22, B23, B26, B28, B29, B30, B31 |
| D: deep Claude Code dependency | 14    | R5, R7, R8, B4, B5, B6, B7, B8, B9, B17, B18, B19, B24, B27                                          |

| 00292 refresh verdict | Items                                                                                                                                                                       |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| STILL TRUE            | R1 (grown to 34 catalogued / 31 wired), R3 (grown), R5, R8 (grown), R9                                                                                                      |
| CHANGED               | R2 (payload catalogue much wider), R4 (hot path moved to `server.py`), R6 (init.sh x3, generated forwarders), R7 (now an identity key), R10                                 |
| GONE                  | 00292's claims that the relay is "a pure byte pump" with "no host-specific knowledge" (R10) and that the event count is "31 of 32" (R1). No 00292 coupling has disappeared. |

Two caveats on these counts:

- **Weighting.** Most of the 22 A items are small. R3 (the serializers) and B2 (tool-input shapes across 59
  PreToolUse handlers) are not small.
- **Where the D items sit.** They cluster in the autonomy and supervision layer: stop gates, crons, `/goal`, ccy,
  sub-agents and the usage pause. The safety-guard layer (PreToolUse on shell and file writes) is almost entirely A.
  The daemon's two halves are therefore unequally portable.

## The 10 most load-bearing couplings

Ranked by how much of the daemon stops working if the coupling cannot be met.

01. **R5, hook registration** (`install.py:756`, `hook_registration.py:337`). Nothing runs without a host-side "run
    this command for this event" surface.
02. **A blocking pre-tool hook carrying tool name and input** (R3 PreToolUse `hook_result.py:676-713`; B2
    `tools.py:25-102`). This feeds 59 of the 81 PreToolUse handler modules, which are the daemon's core value. The host
    must be able to deny, and ideally rewrite (`updatedInput`).
03. **R3, the response serializers** (`hook_result.py:565-1021`). Every verdict passes through them. A second host
    needs its own serializer.
04. **B4, Stop block-and-re-enter** (`auto_continue_stop.py`, `hook_result.py:743-795`, `init.sh:3705`). This
    carries the stop-explanation contract and the gates in B5, B18 and B19.
05. **R7, `transcript_path`** (`disclosure_tracker.py:11-26`, `transcript_reader.py:222-345`). It is both a per-agent
    identity and the only view of the conversation the stop gates have.
06. **R1, the event catalogue and registry** (`events.py`, `handlers/registry.py:57`). Every subsystem derives from
    it: settings, forwarders, schemas, the relay exclusion list and completeness tests.
07. **B8, the sub-agent payload** (`agent_id`, `agent_type`, `last_assistant_message`, `.claude/agents`). Report
    persistence, handoff and the context budget depend on it.
08. **B5, session crons plus `session_crons`** (`cron_stop_enforcer.py:249`, `persistent_cron_assertor.py:189`). The
    unattended and failsafe loop depends on them.
09. **R6/R10, the transport** (`init.sh`, the generated forwarders, `hooks_relay.rs`). This is neutral underneath.
    The per-host parts are the exit-code contract, raw-stdout events and the fail-closed deny body.
10. **B12/B13, the agent-guidance channel** (`claude_md_injector.py`, `.claude/skills`, `.claude/agents`). This is
    how the agent learns the rules that the guards enforce. Without it, denies arrive without the context that makes
    them recoverable.

Close behind: B7 (the ccy supervisor) and R8/B18 (the status-line payload feeding the usage pause). Each is
load-bearing for one subsystem but optional for the daemon as a whole.

## Implications for the options paper (Task 2.3)

- 00292's architectural conclusion still stands: keep `HookResult` as the internal model and add a per-host
  serializer and forwarder family (Option A), with refusal-capability degradation (Option D). The degradation
  vocabulary has since been strengthened by `src/core/decision_capability.py` and the vendored contracts (B1).
- The work has grown since 00292. A host adapter now also has to supply four things:
  1. a per-agent identity (for the disclosure tracker)
  2. a sub-agent stop payload
  3. a cron or tick mechanism
  4. a stop re-entry contract
- A natural first increment is a host adapter for the safety-guard layer only (PreToolUse/PostToolUse on shell and
  file tools, SessionStart context, CLAUDE.md-equivalent guidance). The class-D autonomy layer would be marked
  unsupported per host until each piece is mapped.

## Gaps

- I did not read handler-by-handler to tell whether each of the 74 tool-matching handlers uses
  `HookInput` accessors or raw dict keys. The 59/74 figures are file-level grep counts.
- I checked the transcript-consumer total (about 90 modules) with a grep for `transcript_path`. Many of those
  modules use the field only as a disclosure key, not to parse the file. The 18 direct parser users are the firmer
  figure.
- I did not re-check the `docs/` and `CLAUDE/` documentation's own Claude Code assumptions (LLM-INSTALL, skills
  prose). They are covered only as B3, B13 and B26.
