# Plan 00223: standing subagent authorisation system prompt overrides

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

A session's system prompt carried `Do not call the Agent tool unless the user requested it`. The agent then declined to dispatch sub-agents on its own
initiative, in a project whose `CLAUDE.md` calls sub-agent orchestration a
default execution strategy and whose standing instruction is to dogfood as
much as possible. The user had to grant permission per task.

The instruction is not wrong — it says *unless the user requested it*, and a
user who wants free delegation has simply already requested it. The problem is
that the request is made once, in conversation, and is gone by the next
session, while the restriction is reasserted every session from a position the
project cannot reach.

So this is not about defeating a guardrail. It is about giving a project a
durable place to record standing authorisations it has genuinely granted, and
having the daemon replay them where the agent will actually read them.

## Goals

- A config-driven, default-on mechanism for a project to declare standing
  authorisations (`daemon.system_prompt_overrides` or similar), shipped with a
  small default set and fully user-editable
- Delivery at the highest-leverage injection point the daemon can reach, chosen
  on evidence rather than convenience
- One authoritative statement per authorisation, so a project cannot end up
  with the CLAUDE.md block and the injected context disagreeing

## Non-Goals

- No attempt to defeat or suppress safety instructions. This replays
  authorisations a project's owner has actually given; it is not a jailbreak
  surface and must never become one.
- No shipping of a curated catalogue of "instructions to override". Anthropic
  deleted 80%+ of the Claude Code system prompt for Claude 5, including the
  most-complained-about lines, so a hardcoded list would be stale on arrival
  and would fight text that may no longer exist (see Research).
- No new supervisor injection machinery. Plans 00135 and 00168 own that.

## Context & Background

### Where each lever actually sits

Measured against this repository and the published docs, not assumed:

| lever                                 | position                     | machinery needed         |
| ------------------------------------- | ---------------------------- | ------------------------ |
| `--append-system-prompt` at launch    | highest — inside the prompt  | supervisor change        |
| supervisor-injected user-role message | high — reads as the user     | Plans 00135 / 00168      |
| SessionStart `additionalContext`      | mid — system-reminder        | **none, already exists** |
| UserPromptSubmit `additionalContext`  | mid, but repeated + freshest | **none, already exists** |
| daemon's `CLAUDE.md` block            | LOWEST of all                | none                     |

The `CLAUDE.md` block was the user's second suggestion and is the weakest
option: published guidance puts the system prompt highest in the hierarchy and
`CLAUDE.md` lowest, so directives there lose by structural position rather
than by content. It remains worth writing as the *documented* home of the
setting — just not as the delivery mechanism.

`hook_result.py` already emits `hookSpecificOutput.additionalContext` for both
SessionStart and UserPromptSubmit, and handlers already use it
(`critical_thinking_advisory`, `post_clear_auto_execute`). So the middle two
rows cost no new machinery at all.

### Research (2026-08-12)

- Anthropic removed 80%+ of the Claude Code system prompt for Claude 5,
  swapping e.g. "default to writing no comments. Never write multi-paragraph
  docstrings" for "write code that reads like the surrounding code". Several
  historically-overridden instructions no longer exist.
- The live complaint is the "Output Efficiency" section suppressing reasoning
  ("Go straight to the point… Be extra concise"), reported with a patch and
  closed as not planned (anthropics/claude-code#45704).
- Sources: `Piebald-AI/claude-code-system-prompts` (tracks the prompt per
  release), the Agent SDK "Modifying system prompts" docs, and a
  priority-hierarchy write-up placing `CLAUDE.md` lowest.
- Verified locally: ccy does NOT inject the agent restriction — it is not ours
  to delete at source.

## Technical Decisions

### Decision 1: config declares, hooks deliver, CLAUDE.md documents

**Context**: four candidate levers, three of them requiring new machinery.

**Decision**: put the authorisations in config, deliver them through the
existing SessionStart/UserPromptSubmit `additionalContext` path, and document
the setting in the CLAUDE.md block WITHOUT relying on it to carry the
instruction. Recommended rather than settled — Phase 1 measures before
committing.

**Why not lead with the supervisor**: it is the highest-leverage option and it
is also owned by two in-progress plans, one of which exists because injection
*stopped firing*. Building on it now couples this work to an unstable base for
a benefit the middle rows may already deliver.

### Decision 2: phrase as a RECORDED REQUEST, never as a countermand

**Context**: the instruction says "unless the user requested it".

**Decision**: the injected text states that the project owner has standing-
requested the behaviour, and names where it is configured so it can be
audited and revoked. It must never instruct the agent to disregard its own
instructions — that is both a worse prompt and a mechanism nobody should ship.

## Tasks

### Phase 1: Measure which injection point actually lands

- [ ] ⬜ **Task 1.1**: Establish the baseline — confirm the restriction's
  wording in the current session's prompt and capture how it presents
- [ ] ⬜ **Task 1.2**: Trial SessionStart `additionalContext` and observe
  whether free delegation follows without a per-task grant
- [ ] ⬜ **Task 1.3**: Trial UserPromptSubmit (repeated, freshest position) and
  compare. Measure BOTH before choosing — Plan 00216 measured a prompt
  contract three ways and position beat emphasis every time
- [ ] ⬜ **Task 1.4**: Record which landed, in a supporting doc, with the
  actual observed behaviour rather than an assumption

### Phase 2: The config surface

- [ ] ⬜ **Task 2.1**: Schema + defaults for the overrides block, default-on
- [ ] ⬜ **Task 2.2**: A first-class entry for sub-agent authorisation, with
  the text phrased per Decision 2
- [ ] ⬜ **Task 2.3**: `config-changes/` manifest entry so existing installs are
  told the option exists (it would otherwise ship dormant)

### Phase 3: Delivery

- [ ] ⬜ **Task 3.1**: Handler emitting the enabled authorisations via the
  winning event from Phase 1
- [ ] ⬜ **Task 3.2**: `get_claude_md()` documenting the setting and pointing at
  the config, without duplicating the authorisation text itself
- [ ] ⬜ **Task 3.3**: Rate-limiting if UserPromptSubmit wins, so it does not
  re-inject on every turn

### Phase 4: Verify

- [ ] ⬜ **Task 4.1**: Full QA suite passes
- [ ] ⬜ **Task 4.2**: Client-mode verification — this adds deployed config
- [ ] ⬜ **Task 4.3**: Dogfood: confirm a fresh session delegates without a
  per-task grant, and that disabling the option restores the prior behaviour

## Success Criteria

- [ ] A fresh session in this project dispatches sub-agents without needing a
  per-task grant, on the strength of the recorded standing request alone
- [ ] Setting the option to false restores the previous behaviour exactly
- [ ] The injected text reads as a recorded authorisation, never as an
  instruction to disregard the system prompt
- [ ] Existing installs learn the option exists, via `config-changes/`
- [ ] Full QA passes and the daemon restarts RUNNING

## Dependencies

- Related: Plan 00135 (supervisor injection architecture) and Plan 00168
  (compaction injection not firing) — both own the supervisor lever this plan
  deliberately does not build on yet.
- Related: Plan 00216, whose measured finding was that a prompt instruction's
  POSITION beat its emphasis. Phase 1 exists because of it.

## Risks & Mitigations

| Risk                                                 | Impact | Probability | Mitigation                                                                                     |
| ---------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------- |
| Becomes a general "ignore your instructions" surface | High   | Low         | Decision 2 fixes the framing; Non-Goals forbid a catalogue; keep it to recorded authorisations |
| Injected context loses to the system prompt anyway   | Medium | Medium      | Phase 1 measures before any code is written, and reports a null result honestly                |
| Ships dormant in existing installs                   | Medium | High        | Task 2.3 — this is exactly what `config-changes/` with `recommended: true` is for              |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00223-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened after a session in which the restriction required per-task permission
  grants in a project whose own docs make delegation the default strategy
