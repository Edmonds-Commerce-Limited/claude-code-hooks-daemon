# Plan 00158 — what `subagentStatusLine` renders against

Decision document only. The Blocker line says resuming Phases 2 and 4 "needs a
fresh decision about what `subagentStatusLine` renders against, not a re-point
at another plan" (`PLAN.md:4`). This is that decision. It does not change the
status header.

## Decision

Do not cancel. `subagentStatusLine` renders against its OWN stdin payload — the
`tasks[]` array Claude Code sends on every refresh tick — exactly as the main
bar renders against its payload. No artefact store, no daemon-side subagent
registry, and nothing Plan 00174 was designing is needed. The blocker was a
misattribution; Phases 2–4 are unblocked and should resume with the rescoping
below.

## Reasoning

**The surface still exists, and its contract is richer than the plan
recorded.** Verified today against the primary source
(`https://code.claude.com/docs/en/statusline`): "The `subagentStatusLine`
setting renders a custom row body for each subagent shown in the agent panel
below the prompt ... The command runs once per refresh tick and receives all
visible subagent rows as a single JSON object on stdin. The input includes the
base hook fields, a `columns` field with the usable row width, and a `tasks`
array. Each task has `id`, `name`, `type`, `status`, `description`, `label`,
`startTime`, `model`, `effort`, `contextWindowSize`, `tokenCount`,
`tokenSamples`, and `cwd`." `model` and `contextWindowSize` require v2.1.205+
and "are omitted for a task whose model isn't resolved yet"; `contextWindowSize`
"is that model's context window in tokens, computed the same way as the main
status line's `context_window.context_window_size`, so you can render a
per-row percentage from `tokenCount`." The plan's Research Findings §C
(`PLAN.md:74-89`, v2.1.207) match except that `effort` has since been added
per task — the contract has only grown.

**Rendering is a pure function of that payload.** Every one of the twelve main
bar handlers reads only its own `hook_input`, which is why Confirmed Truth #6
found the concurrent-session render safe (`PLAN.md:379-401`). The rows are the
same shape: `tasks[i].tokenCount / tasks[i].contextWindowSize` is the per-row
context percentage; `tasks[i].model` is the model segment; `name`, `type`,
`status` are the identity the main bar lacks. Nothing needs to be remembered
between ticks.

**Plan 00174 was never this plan's dependency.** 00174 was a cache for the
MAIN bar's expensive, system-derived segments (the git subprocess at 5–50 ms,
`Cancelled/00174-.../PLAN.md:12-41`, `:74-80`). It mentions Plan 00158 exactly
once, as "Related ... the LAG lever" (`:344`) — a sibling, not a prerequisite.
The Blocker line was written in the plan-hygiene commit `64be8e84`, whose
message says "00158's blocker named 00174 and would have been left pointing
into the archive"; the earlier blocker text was inherited, not derived from
either plan's design. Plan 00175's conclusion that the artefact store should
not be built ("Claude Code's 1s refresh floor caps any benefit a cheaper
render could unlock", `00175-.../PLAN.md:34-36`) concerns render COST and
says nothing about whether rows can be rendered. `refreshInterval: 1` is live
(`.claude/settings.json:13`), so a per-tick row render already runs at the
floor.

**What else the daemon knows, and why it is optional.** The brief asked
whether `background_process_tracker` or the `session_crons`/agent payload
data could be rendered against. Neither is needed and one is irrelevant:

- `background_process_tracker` (`handlers/post_tool_use/background_process_tracker.py:1-20`)
  records backgrounded BASH processes to a JSONL file; it knows nothing about
  Task-tool subagents and has no per-agent identity.
- `SubagentStart` / `SubagentStop` payloads carry `agent_id` and `agent_type`
  (`contracts/claude-code-hooks/SubagentStart.json`, `SubagentStop.json`), and
  `dispatch_declaration` sees the Task-tool prompt at dispatch. These could
  ENRICH a row later — for example the plan folder a subagent was dispatched
  for — but they are not what the row renders against, and building a
  registry from them would reintroduce the per-session shared-state hazards
  Truth #6 warned about, for data the panel already sends resolved.

The daemon's own `Status` payload does carry `agent_type` and the handlers
already read it (`CLAUDE/Architecture/StatusLine.md:183`) — used to exclude
pre-warmed spares from the 🧵 count (`PLAN.md:418-428`). That is main-bar
work, already done.

### Rescoping Phases 2–4

- **Task 2.1** stands: a second top-level settings key, mirroring
  `statusLine` (`PLAN.md:298-301`): forwarder `.claude/hooks/subagent-status-line`,
  event `SubagentStatus`, wired the way `Status` is — outside the `hooks`
  block. The response is multi-row JSON lines `{"id","content"}`, so
  `send_request_stdin` and the `HookResult` join gain a second Status-like
  shape rather than reusing `{"text": ...}`.
- **Task 2.2** stands and gets its answer: one row per `tasks[]` entry;
  reuse the `model_context` segment's percentage formatting; when `model` /
  `contextWindowSize` are absent (unresolved task or pre-v2.1.205), render
  `name · type · tokenCount` and no percentage; truncate to `columns`.
- **Task 2.3** is closed by this document: no per-thread state. The row is a
  pure function of the tick's payload.
- **Phase 3** stands, with two invariants to carry: the completeness gate
  treats `StatusLine` as a bespoke non-hook surface
  (`tests/integration/test_hook_coverage_completeness.py:82-87`) and
  `SubagentStatus` needs the same carve-out; `hook_registration_checker`
  must not read the new key as a stray registration. Deployment is free: the
  installer copies the daemon's own `.claude/settings.json` verbatim
  (`00175-.../PLAN.md:71-75`), so adding the key here ships it.
- **Phase 4** stands; the truth-changes and config-changes entries go into
  `CLAUDE/UPGRADES/UNRELEASED/` as the plan's own tasks, per the definition of
  done.

## Cost, and who bears it

A new surface in every client: one forwarder, one settings key, one response
shape, one bespoke carve-out in the completeness gate and the registration
checker. The render runs once per second per session while the agent panel is
visible, on a payload with no expensive segment (no git, no filesystem) — well
under the ~39 ms main-bar render Plan 00175 measured. Maintainers bear the
build and the ongoing surface; users bear nothing they can notice except the
rows changing.

## Strongest argument against

The built-in row (`name · description · token count`) already exists and is
adequate; the only thing the daemon adds is visual consistency and a per-row
context percentage. Every new settings key is a surface the installer must
deploy, the checkers must tolerate, and upgrades must carry — for a cosmetic
gain. That is a fair description of the value, and if the owner no longer
wants the surface, the honest disposition is Cancelled with that reason, not
Dormant. What this argument does not do is make the blocker real: the plan is
technically buildable today.

## Does a human gate remain?

Not a fresh one. "What does it render against?" has one answer. The standing
question — is a consistent per-row render worth a new client surface — is a
product preference, and the owner already expressed it by scoping this plan's
Goals to "render a first-class per-thread row via `subagentStatusLine`"
(`PLAN.md:20-24`, `:115-118`). A plan's scope is the human's to set
(`CLAUDE/core/PlanWorkflow.core.md:534-535`); until the owner withdraws that
scope, resuming it needs no new permission.
