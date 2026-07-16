# Plan 00170: Universal Hook Coverage + Hook-Support Enforcement

**Status**: In Progress
**Created**: 2026-07-16
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**Intercepting Claude Code hook events is this daemon's entire reason to exist.**
If Claude Code fires a hook event the daemon doesn't wire, that event is silently
invisible — no forwarding, no dispatch, and — critically — **no way for a client
project to attach a handler to it.** That is a raison-d'être bug, not a nice-to-have.

Ground truth (2026-07-16): the official spec
([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)) documents
**31 hook events**. The daemon wires **10** of them (`constants/events.py`:
PreToolUse, PostToolUse, SessionStart, SessionEnd, Stop, SubagentStop,
UserPromptSubmit, PreCompact, Notification, PermissionRequest — plus the separate
StatusLine surface). **~21 documented events are unwired** (see §Coverage Gap).

This plan establishes a durable principle and the machinery to enforce it:

> **Wire every hook event, unconditionally.** Whether or not the daemon ships a
> built-in handler for an event, the event MUST be forwarded and dispatchable so a
> client project can attach its own handler. A newly-discovered upstream event is
> wired **first** (coverage is non-negotiable); *what to do with it* — whether to
> ship a built-in handler — is a **separate** decision captured as its own plan.

Two deliverables: (1) a **completeness enforcement system** (a TDD/QA gate that
FAILS if any known event is not fully wired, plus drift-detection so new upstream
events get discovered), and (2) the **rollout** that actually wires the missing
events with safe zero-handler passthrough.

Cross-links: grew out of the Plan 00169 research pass — see
[Completed/00169-.../FEATURE-BACKLOG.md](../Completed/00169-prior-art-sota-research-and-feature-brainstorm/FEATURE-BACKLOG.md)
(§"newer hook-spec capabilities we underuse") and
[RESEARCH-FINDINGS.md §1](../Completed/00169-prior-art-sota-research-and-feature-brainstorm/RESEARCH-FINDINGS.md).
Several newly-wired events unlock backlog features (F3 StopFailure recovery, F6
PostCompact hygiene, F11 SubagentStart spawn-budget, F19 InstructionsLoaded
dead-guidance audit, F20 ConfigChange guard) — those are follow-up plans, not this one.

## Goals

- Establish the **canonical hook-event registry** as the single source of truth for
  *all* Claude Code hook events (not just the ones we currently handle), with
  per-event metadata (block capability, response contract, category, spec version).
- Ship a **completeness enforcement gate**: a deterministic test (wired into QA)
  that FAILS if any registry event lacks a forwarder, installer entry, settings
  registration, router dispatch, input schema, or a safe passthrough response — and
  fails on orphans (wired things not in the registry).
- **Wire every currently-unwired documented event** with safe zero-handler
  passthrough, so client projects can attach handlers to any event today.
- Add **drift detection** so newly-introduced upstream events are discovered
  (runtime unknown-event logging + version-pinned spec audit + a coverage-checker
  advisory), and an **onboarding scaffolder** so wiring a new event is one command.
- Preserve the invariant: **coverage is unconditional; built-in-handler decisions
  are separate** (each new event → its own triage plan/backlog entry).

## Non-Goals

- **Not** building built-in handlers for the newly-wired events. Wiring +
  passthrough only. Handler ideas are triaged into follow-up plans (see §Triage).
- Not changing the response contracts of the 10 already-wired events.
- Not the Plan 00169 feature backlog wholesale — only the hook-*coverage* substrate
  and the enforcement system. Feature handlers graduate separately.

## Context & Background

**How a hook is wired today** (four coupled layers, currently hand-maintained):

1. **SSoT enum** — `src/claude_code_hooks_daemon/constants/events.py` (`EventID` +
   `EventIDMeta` with enum/config/bash/json name forms; `EventKey` Literal).
2. **Bash forwarder** — `.claude/hooks/<bash-key>` sources `init.sh`, `ensure_daemon`,
   `send_request_stdin "<JsonKey>"` (near-identical per event; only the event literal
   differs — a DRY smell at 21× new scripts).
3. **Settings registration** — `.claude/settings.json` maps each event → the daemon
   wrapper (audited today by `hook_registration_checker`).
4. **Installer + router** — `install.py` writes the forwarder set; FrontController /
   EventRouter dispatches by `hook_event_name`; input schemas in
   `constants/` / `core/input_schemas.py`; response validation in
   `tests/integration/test_all_handlers_response_validation.py`.

There is **no single test that asserts these four layers agree with the full set of
Claude Code events** — drift is invisible until a user notices a missing hook.

### Coverage Gap (authoritative, 2026-07-16)

Wired (10 documented + StatusLine): SessionStart, UserPromptSubmit, PreToolUse,
PermissionRequest, PostToolUse, Notification, SubagentStop, Stop, PreCompact,
SessionEnd.

**Unwired (21):**

| Event                 | Can block?        | Notes / first-use idea                                  |
| --------------------- | ----------------- | ------------------------------------------------------- |
| `Setup`               | No                | `--init`/`--maintenance` `-p` runs; needs mode plumbing |
| `UserPromptExpansion` | Yes               | slash-command expansion interception                    |
| `PermissionDenied`    | No                | auto-mode classifier denial (retryable)                 |
| `PostToolUseFailure`  | Yes               | tool-error recovery advisory (Plan 00101 class)         |
| `PostToolBatch`       | Yes               | mitigates batched-cancellation footgun                  |
| `MessageDisplay`      | No (display-only) | rewrite displayed text                                  |
| `SubagentStart`       | No                | subagent spawn-budget (F11)                             |
| `TaskCreated`         | Yes               | plan-workflow enforcement on Task system                |
| `TaskCompleted`       | Yes               | plan-completion enforcement                             |
| `StopFailure`         | No                | event-driven recovery (F3) — beats hourly poll          |
| `TeammateIdle`        | Yes               | supervisor / idle-housekeeping tie-in                   |
| `InstructionsLoaded`  | No                | dead-guidance audit (F19)                               |
| `ConfigChange`        | Yes               | config-drift guard (F20)                                |
| `CwdChanged`          | No                | cwd-aware context                                       |
| `FileChanged`         | No                | needs `watchPaths` config                               |
| `WorktreeCreate`      | Yes               | worktree provisioning                                   |
| `WorktreeRemove`      | No                | worktree teardown                                       |
| `PostCompact`         | No                | post-compaction hygiene / context save (F6)             |
| `Elicitation`         | Yes               | MCP form interception                                   |
| `ElicitationResult`   | Yes               | MCP form result                                         |

## Brainstorm — ideas to handle hooks

*(The design space the user asked to explore. Decisions are deferred to the tasks;
this section is the option menu.)*

### A. Canonical hook-event registry (SSoT-first)

Grow `EventID`/`EventIDMeta` from "events we handle" to "**every** Claude Code
event," adding metadata per entry: `can_block`, `category` (tool/lifecycle/session/
task/team/compaction/worktree/mcp/display), `response_contract` (the valid response
shape + the *do-nothing* passthrough for it), `spec_version`/`spec_status` (when it
appeared → version-aware drift), `ships_builtin_handler` (bool; false = passthrough-
only, still wired). Everything else — forwarders, settings, installer, router,
schemas, docs, the completeness test — **derives** from this SSoT (NO MAGIC / SINGLE
SOURCE OF TRUTH).

### B. Completeness enforcement gate (the "fail if not all wired" TDD)

One test iterating the registry, asserting per event: forwarder exists +
executable + sources init.sh + calls `send_request_stdin "<JsonKey>"`; installer's
event list == registry; `settings.json` registers it → daemon wrapper; router
dispatches it (no "unknown event"); an input schema (or permissive default) exists;
a valid no-handler passthrough response exists. **And the reverse** — no orphan
forwarder/registration for a non-registry event. Wire into `scripts/qa/` as a
blocking check. This is the deterministic "catches and fails if we don't have all
hooks wired" the user wants.

### C. Zero-handler passthrough (the enabler for client handlers)

The router must cleanly handle an event with **no matching handler** by returning
that event's *do-nothing* response (approve/empty/exit-0 per contract) — never
fail-closed. This is precisely what lets "a client project create handlers for it
even if we don't." Project-handlers register against any wired event.

### D. Drift detection (discovering NEW upstream events) — defence in depth

1. **Runtime unknown-event logger** — daemon logs (advisory) any inbound
   `hook_event_name` not in the registry. Catches partial drift (event registered +
   fired but absent from SSoT). Limitation: an *unregistered* event never reaches
   the daemon.
2. **Version-pinned spec audit** — pin the registry to a Claude Code version; a
   SessionStart advisory (or `version_check`) flags when installed Claude Code is
   newer than the pin and prompts a hooks-doc re-audit. Optional
   `daemon-cli audit-hooks` that WebFetches the official hooks doc and diffs event
   names vs the registry (networked; opt-in tool, not an offline gate).
3. **Introspection scan** — if Claude Code exposes its known-hook list (schema/CLI),
   compare to the registry; a loud SessionStart "coverage degraded" advisory mirrors
   `project_handler_load_checker`.

### E. Onboarding scaffolder

`daemon-cli add-hook-event <JsonKey>` generates from one registry entry: forwarder,
settings entry, schema stub, passthrough test, docs row — so wiring a newly-
discovered event is one command that leaves the completeness gate green. *Then* a
separate triage decides whether to ship a built-in handler.

### F. Forwarder DRY

21 near-identical new bash scripts is a duplication smell. Options: (i) keep
per-event scripts but generate them from one template keyed by the registry (verify
the installer already does this); (ii) a single parameterised dispatcher
`.../hooks/dispatch <Event>` if `settings.json` commands can carry an arg — 21
scripts → 1 + registry. Investigate the settings command-arg capability before
committing.

### G. Categorised, staged rollout (not all events are equal)

- **Forward-only batch** (no block): Setup, PermissionDenied, MessageDisplay,
  SubagentStart, StopFailure, InstructionsLoaded, CwdChanged, FileChanged,
  WorktreeRemove, PostCompact — cheap, low-risk passthrough; ship first.
- **Blocking batch** (can deny): UserPromptExpansion, PostToolUseFailure,
  PostToolBatch, TaskCreated, TaskCompleted, TeammateIdle, ConfigChange,
  WorktreeCreate, Elicitation, ElicitationResult — wire with a **safe approve/no-op
  default**; blocking only if a handler opts in. Extra care: a wrong default here
  could break a live session, so response-contract correctness + acceptance tests
  per event are mandatory.

### H. Blast-radius guards

Wiring 21 forwarders + settings entries touches the install path and the live
session's `settings.json`. Mitigations: passthrough defaults provably safe (return
the event's do-nothing response); **fail-open, never fail-closed** on an
unknown/zero-handler event; per-event acceptance tests; staged rollout
(forward-only, then blocking). `hook_registration_checker` extended to assert the
new registrations.

## Tasks

### Phase 1: Canonical registry (SSoT)

- [ ] ⬜ **Task 1.1**: Enumerate all 31 events into `EventID` with metadata
  (`can_block`, `category`, `response_contract`, `spec_version`,
  `ships_builtin_handler`). TDD: registry-shape tests first.
- [ ] ⬜ **Task 1.2**: Decide the forwarder strategy (per-event generated vs single
  parameterised dispatcher) — investigate settings command-arg support first
  (Decision 1).

### Phase 2: Completeness enforcement gate (TDD)

- [ ] ⬜ **Task 2.1**: Write the completeness test (forwarder/installer/settings/
  router/schema/passthrough per event + orphan check). RED against today's gap.
- [ ] ⬜ **Task 2.2**: Wire it into `scripts/qa/` as a blocking check.

### Phase 3: Zero-handler passthrough + wiring

- [ ] ⬜ **Task 3.1**: Router returns the correct do-nothing response per event
  contract when no handler matches (fail-open). TDD per contract type.
- [ ] ⬜ **Task 3.2**: Wire the **forward-only** batch (§G) — forwarders, installer,
  settings, schemas. Completeness gate goes GREEN for those.
- [ ] ⬜ **Task 3.3**: Wire the **blocking** batch (§G) with safe defaults +
  per-event acceptance tests.

### Phase 4: Drift detection + onboarding

- [ ] ⬜ **Task 4.1**: Runtime unknown-`hook_event_name` advisory logger.
- [ ] ⬜ **Task 4.2**: Version-pinned spec-audit advisory (+ optional
  `audit-hooks` CLI) and coverage-degraded SessionStart alert.
- [ ] ⬜ **Task 4.3**: `add-hook-event` scaffolder CLI.

### Phase 5: Triage, docs, dogfood, rollout

- [ ] ⬜ **Task 5.1**: For each newly-wired event, create a backlog/triage entry
  (own follow-up plan) deciding built-in-handler value — wiring already done.
- [ ] ⬜ **Task 5.2**: Docs (`HOOKS-DAEMON.md` regen, architecture, PROJECT_HANDLERS
  extension points), dogfood via daemon restart, client-rollout note +
  config-changes manifest.

## Dependencies

- **Related**: [Plan 00169](../Completed/00169-prior-art-sota-research-and-feature-brainstorm/PLAN.md)
  (this plan graduated from its hook-coverage finding).
- **Feeds**: follow-up feature plans for individual events (F3/F6/F11/F19/F20 etc.).

## Technical Decisions

### Decision 1: Forwarder strategy — per-event vs single dispatcher

**Context**: 21 new near-identical forwarders is a DRY smell.
**Options**: (A) generate per-event scripts from a template keyed by the registry;
(B) one parameterised `dispatch <Event>` script if settings commands accept an arg.
**Decision**: TBD — resolve in Task 1.2 after verifying Claude Code settings
command-arg support and forwarder-generation in the installer.

## Success Criteria

- [ ] `EventID` registry enumerates all 31 documented events with metadata.
- [ ] Completeness gate FAILS on any unwired/orphaned event and PASSES only at full
  coverage; wired into QA.
- [ ] Every documented event is forwarded + dispatchable with safe zero-handler
  passthrough; a project-handler can attach to any event (proven by a test).
- [ ] Drift detection + onboarding scaffolder in place; new upstream events are
  discoverable and one command from full wiring.
- [ ] Coverage-unconditional / handler-decision-separate invariant documented;
  per-event triage entries created.
- [ ] QA green, daemon restarts RUNNING, dogfooded live.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is SSoT for "when"). -->

- Plan scaffolded; recovery coverage via the session's existing cron `4c8c64ca`
  (Plan 00169) — no duplicate cron created.
