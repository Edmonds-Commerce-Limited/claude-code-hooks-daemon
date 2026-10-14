# Plan 00526: supervisor plugin relay result

**Status**: Not Started
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #119

## Overview

The ccy supervisor's plugin API (Plan 00487) is version 1.0
(`_PLUGIN_API_VERSION = (1, 0)` in `.claude/ccy/claude-supervise.py`). A
plugin's worker half has one hook, `on_idle(tick)`, which runs only when the
supervisor could inject. It may return only `ExitForRestart` or `Notify`, and
`Notify` has a closed kind and an optional integer, with no text. So a plugin
that bridges an external message source (a chat bus shared by several agent
sessions and humans) cannot put a message's content into the session, and
cannot act at all while the session is busy.

#119 proposes an additive API 1.1:

- A `Relay` result carrying 1..N entries, each a closed, validated header
  plus an untrusted, length-capped body.
- An `on_relay(tick)` hook called on every tick, busy or idle. Claude Code
  queues typed input until the turn ends, so no Esc is needed.
- A supervisor-rendered envelope: a per-relay nonce, a fixed provenance line,
  and the body quoted as a JSON string.
- Confirmation of the keys typed, so a plugin consumes its spool exactly once.
- Caps on bytes, entries, one relay in flight, and an hourly limit.
- No typing into a half-typed input line.
- Harness support for testing all of this.

This is the first route by which text the supervisor did not write reaches
the session as typed input, so it opens a prompt-injection surface. The
envelope and provenance line mark the text as data, but they cannot stop a
model from acting on it. The issue-sdlc runbook routes a new safety-relevant
capability to the owner.

## Owner decision needed

1. **Build it at all?** Should external text be typed into the session through
   the supervisor, or should agents keep pulling messages themselves (one
   model turn per poll)?
2. **Trust boundary:** if built, is the envelope plus provenance line enough,
   or should relayed text also be restricted, e.g. allowed only from senders
   on a configured list, or only into sessions that opt in per plugin?
3. **Busy delivery:** should a relay type into a busy session (queued by Claude
   Code until the turn ends), or wait for idle as `on_idle` does today?

## Goals

- If approved: a plugin can deliver capped, enveloped, attributed external
  text into the session exactly once per message, with confirmation, and API
  1.0 plugins are unaffected.

## Non-Goals

- Any inbound network listener in the supervisor or the daemon.
- Letting a plugin supply envelope, provenance or notice text itself.

## Tasks

### Phase 1: Design (after the owner's rulings)

- [ ] ⬜ **Task 1.1**: Write the API 1.1 contract into this plan from the
  rulings: types, hook timing, envelope rendering, caps, confirmation and
  version negotiation.

### Phase 2: Build (TDD, supervisor suite)

- [ ] ⬜ **Task 2.1**: RED: tests for envelope escaping (a body that tries to
  close the envelope), every cap, one relay in flight, the half-typed-line
  hold, busy and idle delivery as ruled, confirmation, and an API 1.0 plugin
  unchanged.
- [ ] ⬜ **Task 2.2**: GREEN: the implementation, `PluginTestHarness` support,
  and a release note.

## Success Criteria

- [ ] The owner's rulings are recorded, and the API 1.1 contract matches them.
- [ ] Relayed text is always enveloped, capped and attributed, and an
  API 1.0 plugin behaves exactly as before, proven by tests that failed first.
- [ ] Release-bound consequences recorded in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00526-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #119; no live plan overlaps (prior art:
  Plan 00487, the plugin API).
