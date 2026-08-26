# Plan 00269: supervisor goal message injection

**Status**: In Progress
**Created**: 2026-08-26
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Claude Code now supports the `/goal` slash command. This plan gives the ccy PTY
supervisor (Plan 00135's `.claude/ccy/claude-supervise.py`) a new injection
capability: when plan execution starts, inject a pre-formatted, machine-marked
`/goal` message into the Claude Code chat — roughly "work on Plan NNNNN until
completion" — optionally followed by additional configured lines (e.g.
encouraging specialist sub-agents, mandating QA/code-review sub-agents that log
reports to the plan folder).

The message template is config-driven under a `goal_injection` options block:
a default line set with placeholders (`{plan_number}`, `{plan_title}`,
`{plan_path}`), which project config can extend or fully override via the
established `mode: additive|replace` paradigm already used by `command_hints`.

Delivery reuses the existing daemon-as-sensor / supervisor-as-actuator split:
the daemon detects the trigger and writes a validated goal-intent signal file
(the same transport family as `<session>.compacting`); the supervisor consumes
it at its single injection choke point, subject to every existing rail (idle
gate, empty-input-box gate, foreground-identity scoping, cooldown/cap,
decision.log). All design analysis is in
[BRAINSTORM.md](BRAINSTORM.md) — read it before executing.

## Goals

- A `/goal` message is injected into the foreground Claude Code chat when plan
  execution starts, carrying the `🤖 [ccy-supervisor]` machine-origin marker.
- Primary trigger: the daemon detects a `PLAN.md` `**Status**:` flip to
  `In Progress` (PostToolUse on Write/Edit) and writes a goal-intent signal.
- Manual fallback: `bin/hooks-daemon inject-goal NNNNN` writes the same signal
  on demand.
- Message content is templated from config: default lines + placeholders, with
  `mode: additive|replace` mirroring `command_hints`, and per-line ids so a
  project entry can override a single built-in line.
- The supervisor validates every goal payload before typing it (prefix,
  length, line count, charset) and logs the decision (or the NOOP reason) to
  `decision.log`.
- The optional "you are authorised to use sub-agents" line is OFF by default
  and documented as a projection of the project's `standing_authorisations`
  config, never free-standing consent.
- All new behaviour opt-in, TDD-first, QA green, daemon restart verified.

## Non-Goals

- NOT fixing the Plan 00168 live-verification blocker (its NOOP-reason logging
  is already shipped and is reused here; its dormant live-fire task remains
  external).
- NOT a general free-text injection channel — only the goal-intent shape,
  validated at the supervisor choke point.
- NOT injecting on plan *creation* (`mkplan.bash`) — creation is not execution
  (see BRAINSTORM.md Detection).
- NOT changing the release/consent rules: an injected message can never
  constitute human authorisation for anything (release, publish, unproven
  branch deletion).
- NOT background-thread injection — foreground-only, per Plan 00160's model.

## Context & Background

Four prior plans supply the infrastructure (dedupe scout confirmed overlap is
infrastructural, not duplicative):

- **Plan 00135** (`00135-event-driven-send-keys-injection/`, In Progress) —
  the PTY supervisor architecture (ARCH-B), the safety model (allowlist,
  idle gate, cooldown, cap, loop guard, `🤖 [ccy-supervisor]` marker), and the
  daemon-as-sensor / supervisor-as-actuator boundary. This plan adds a new
  payload family to that actuator; Technical Decision 2 below records how the
  frozen-allowlist principle is extended rather than broken.
- **Plan 00160** (Dormant) — foreground-identity resolution and dead-file
  reaping. Goal signals ride the same sidecar directory and must be reaped and
  session-scoped the same way. Its own-session signal scoping shipped under
  **Plan 00166** (Dormant — implementation complete, live two-terminal
  verification outstanding), which is the mechanism the Risks table relies on.
- **Plan 00168** (Dormant) — the known injection-reliability gaps (stale
  sidecar for background threads, idle/input-box deferral, own-session
  filtering) and the NOOP-reason logging that makes deferrals diagnosable.
  Goal injection inherits these gates deliberately; BRAINSTORM.md assesses the
  inherited risk.
- **Plan 00170** (Dormant) — universal hook coverage; relevant only in that
  the trigger here uses already-wired events (PostToolUse), so this plan does
  not depend on it.

Config paradigm precedent: `command_hints`
(`src/claude_code_hooks_daemon/handlers/post_tool_use/command_hints.py`) —
`options.mode: additive|replace`, entries keyed by `id`, project entry with a
matching `id` overrides the built-in. Consent precedent:
`standing_authorisations` (UserPromptSubmit) — recorded standing requests ship
disabled and are enabled only by the repository owner.

## Tasks

### Phase 1: Design lock-in and signal contract

- [x] ✅ **Task 1.1**: Confirm `/goal` behaviour in the current Claude Code
  build — static findings recorded in
  [SIGNAL-CONTRACT.md](SIGNAL-CONTRACT.md); the LIVE probe was not possible
  from the executing worktree agent and folds into Task 4.2's dogfood pass.
  The design does not depend on unverified `/goal` semantics.
- [x] ✅ **Task 1.2**: Lock the goal-intent signal schema
  (`<session>.goal-intent` JSON: `{ts, session_id, plan_number, rendered_lines, source}`), its directory (the existing context-sidecar dir), TTL, and
  reap policy (reuse Plan 00160's reaper) — see
  [SIGNAL-CONTRACT.md](SIGNAL-CONTRACT.md).
- [x] ✅ **Task 1.3**: Lock the config schema under
  `handlers.post_tool_use.goal_injection.options` (see BRAINSTORM.md
  Templating): `mode`, `lines` (list of `{id, text, enabled}`), placeholder
  vocabulary, `once_per_plan_per_session` latch.

### Phase 2: Daemon side (TDD)

- [x] ✅ **Task 2.1**: RED — tests for a `goal_injection` PostToolUse handler:
  detects a `PLAN.md` write whose resulting `**Status**:` reads `In Progress`
  (Write/Edit under the plan directory, excluding `Completed/`), renders the
  configured lines with validated placeholders, writes the signal atomically,
  latches once-per-plan-per-session, `get_default_enabled()` → `False`, never
  blocks. NOTE the deliberate semantics: the handler cannot see a TRANSITION
  (it observes single writes, and the latch is in-memory), so the trigger is
  "first qualifying write per `(plan, session)`" — meaning the first edit to
  an already-In-Progress plan in a NEW session re-fires. That is intended: it
  is what makes the goal survive session restarts, and it subsumes the
  "resumed sessions" case otherwise left to the CLI fallback.
- [x] ✅ **Task 2.2**: GREEN — implement the handler; placeholder values
  strictly validated (`plan_number` = 5 digits; `plan_title`/`plan_path`
  sanitised to a conservative charset, length-capped).
- [x] ✅ **Task 2.3**: RED/GREEN — `bin/hooks-daemon inject-goal NNNNN` CLI
  subcommand writing the same signal (manual fallback and the primary
  debugging tool). The signal file is session-keyed, so the CLI must resolve
  the target session id from `CLAUDE_CODE_SESSION_ID` in its environment (set
  when run from a Claude Code Bash tool; the same variable the supervisor's
  own-session scan keys on) and refuse with a clear message when it is unset
  or the plan folder does not exist. Cross-session retargeting stays an open
  question (BRAINSTORM.md §6 Q4).
- [x] ✅ **Task 2.4**: Config plumbing: HandlerID/Priority constants, exports,
  config template + example, `get_claude_md()`, `get_acceptance_tests()`.

### Phase 3: Supervisor side (TDD, stdlib-only)

- [x] ✅ **Task 3.1**: RED — tests for goal-signal consumption in
  `claude-supervise.py`: fresh in-scope signal + idle + empty input box →
  inject `/goal 🤖 [ccy-supervisor] ...` and consume (unlink) the signal;
  stale/foreign/oversized/malformed signal → NOOP with logged reason;
  validation gate rejects payloads failing prefix/length/charset rules —
  including ANY payload containing a newline (Decision 2 corollary).
- [x] ✅ **Task 3.2**: GREEN — implement consumption through the existing
  injection choke point and state machine; dry-run mode injects the visible
  marker variant, `--arm` injects the real `/goal`.
- [x] ✅ **Task 3.3**: Regression tests — compaction machine behaviour
  unchanged; a pending goal signal never starves or reorders a
  compact/continue decision.

### Phase 4: Verification

- [x] ✅ **Task 4.1**: Full QA `./scripts/qa/llm_qa.py all` → 22/23 PASSED in
  the execution worktree; the single failure is `smoke_test`, which requires
  a RUNNING daemon and is inseparable from the daemon-restart check.
  Supervisor smoke under system python3 passed (imports clean, `--help`
  usage renders, goal constants present). **Daemon restart → RUNNING is
  DEFERRED to the merge reviewer on main** — the worktree must not touch the
  dogfood daemon serving the main checkout.
- [ ] ⬜ **Task 4.2**: Live dogfood — flip a scratch plan to In Progress and
  observe the injected `/goal` (dry-run first, then armed), including the
  deferral path with a non-empty input box (decision.log names the gate).
  DEFERRED to main: needs the live supervisor + an interactive session; also
  carries the Task 1.1 live `/goal` semantics probe.
- [x] ✅ **Task 4.3**: Update docs (HANDLER_REFERENCE section + summary row,
  regenerated `.claude/HOOKS-DAEMON.md`); milestones recorded below.

## Dependencies

- Depends on: Plan 00135 supervisor architecture (shipped and armed in this
  repo); Plan 00160/00166 foreground and own-session scoping (shipped in code;
  live multi-thread verification dormant on both); Plan 00168 Phase 1
  NOOP-reason logging (shipped).
- Inherits risk from: Plan 00168's dormant live-verification (Task 5.3) — the
  same idle/foreground gates gate this feature; see Risks.
- Related: `command_hints` (config paradigm), `standing_authorisations`
  (consent model), `recovery_cron_advisor` (plan-lifecycle detection
  precedent).

## Technical Decisions

### Decision 1: Trigger = status flip to In Progress (primary) + CLI (fallback)

**Context**: candidate triggers were mkplan.bash invocation, PLAN.md status
flip, an explicit CLI command, and a recovery_cron_advisor-style advisory.
**Decision**: primary = PostToolUse detection of a `PLAN.md` write whose
resulting `**Status**:` reads `In Progress` (first qualifying write per plan
per session — see Task 2.1 for why this is state-based, not transition-based);
manual fallback = `bin/hooks-daemon inject-goal NNNNN`. Creation is not
execution; an advisory cannot inject. Full weighing in BRAINSTORM.md.
**Date**: 2026-08-26

### Decision 2: Daemon renders, supervisor validates (extends the allowlist principle)

**Context**: Plan 00135's safety model froze the injectable set to exact
allowlist members and banned interpolating event data into payloads. A goal
message necessarily carries per-plan data, so a closed allowlist cannot
express it.
**Decision**: the daemon renders the full message from config using strictly
validated placeholder values; the supervisor accepts a goal payload only when
it passes a structural validation gate (mandatory
`/goal 🤖 [ccy-supervisor] ` prefix, line/length caps, printable-charset
whitelist, no control bytes) — a *shape* allowlist replacing the *member*
allowlist for this one payload family. Compact/continue payloads keep the
frozen member allowlist unchanged.

**Corollary — the injected payload is ONE physical line.** A newline is a
control byte, and the Plan 00135 Bug #3 delivery contract (one literal chunk,
then a single separate `\r` submit) means an embedded newline would SUBMIT an
intermediate, unmarked bare prompt — precisely the free-text injection the
gate forbids. So configured lines are LOGICAL lines: the daemon joins them
with a fixed separator (`—`) into one physical line before writing the
signal, the line-count cap applies to logical lines pre-join, and the
supervisor's charset gate rejects any payload containing a newline. True
multi-line delivery is deferred until Task 1.1 establishes how Claude Code
accepts multi-line input safely. Alternatives and residual risk in
BRAINSTORM.md. **Date**: 2026-08-26

### Decision 3: Authorisation lines are config projections, not free-text consent

**Context**: an optional line like "you are authorised to use sub-agents"
could read as consent the human never gave.
**Decision**: such lines ship disabled; documentation states that enabling one
is the same deliberate repository-owner act as enabling a
`standing_authorisations` entry, and the recommended default text for the
sub-agent line references the standing authorisation rather than asserting
new authority. The injected message always opens with the machine-origin
marker and a "not human authorisation" clause. **Date**: 2026-08-26

## Success Criteria

- [ ] Flipping a plan to In Progress (with the feature enabled) results in
  exactly one injected `/goal` message per plan per session, visibly
  machine-marked.
- [ ] `bin/hooks-daemon inject-goal NNNNN` produces the same injection on
  demand.
- [x] Project config can add lines, override a built-in line by id, or replace
  the whole set (`mode: additive|replace`), verified by tests.
- [x] The supervisor refuses malformed/oversized/foreign goal payloads and
  logs the reason; compact/continue behaviour is regression-tested unchanged.
- [x] Feature is opt-in (`get_default_enabled()` → `False`); default config
  behaviour is unchanged.
- [ ] QA fully green; daemon restart RUNNING; supervisor tests pass under
  system python3.

## Risks & Mitigations

| Risk                                                                     | Impact | Probability | Mitigation                                                                                                             |
| ------------------------------------------------------------------------ | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------------- |
| Injection silently deferred forever (Plan 00168's known gates)           | Medium | Medium      | Reuse NOOP-reason logging; goal TTL generous; CLI fallback re-issues; dogfood the deferral path explicitly             |
| Injected text mistaken for human instruction/authorisation               | High   | Low         | Mandatory `🤖 [ccy-supervisor]` prefix + "not human authorisation" clause; Decision 3 config gating                    |
| Payload channel abused to inject arbitrary text                          | High   | Low         | Supervisor-side structural validation gate; daemon-side placeholder sanitisation; signal dir is daemon-owned untracked |
| Goal injected into the wrong Agent-View thread                           | Medium | Low         | Foreground-identity scoping + own-session filter (Plans 00160/00166) applied to goal signals identically               |
| Loop: injected /goal edits nothing, but a re-save of PLAN.md re-triggers | Low    | Medium      | Once-per-plan-per-session latch + signal consumption (unlink) + cooldown                                               |
| Feature creep into a general remote-typing channel                       | Medium | Low         | Non-goal stated; validation gate is goal-shaped only; hostile-review focus item in BRAINSTORM.md                       |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00269-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan + brainstorm authored, awaiting human review before any implementation.
- Contract locked (SIGNAL-CONTRACT.md) at ca58823b.
- Daemon sensor delivered (handler + registration + docs) at 679d150a; CLI
  fallback at 0a5b3e8b.
- Supervisor actuator delivered (validation gate, cap, reaper, worker
  round-trip) at f53478c2.
- QA fixes + classifications at 584ec909; QA 22/23 in the execution worktree
  (smoke_test needs a running daemon — deferred with daemon-restart
  verification to the merge review on main, alongside Task 4.2's live
  dogfood).
