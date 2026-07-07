# Plan 00117: Enable ask_user_question_blocker (dogfood → default-on)

**Status**: Dormant (remaining: flip shipped default + regression test; awaiting scheduling)
**Created**: 2026-05-29
**Owner**: Claude (Opus) + user (joseph)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-threaded

## Overview

Dogfooding alert raised by the user mid-session: the agent stalled progress twice by
calling `AskUserQuestion` with tautological questions ("Should I push?", "How far should
I build?"). The `ask_user_question_blocker` handler exists precisely to stop this — it
enforces a prefix-positive policy (block unless every question begins with
`ASKING BECAUSE:`, mirroring the Stop handler's `STOPPING BECAUSE:` convention, shipped
in Plan 00108 / v3.14.0). But it shipped `enabled: false` ("flip to default-on after
dogfooding"), so it never fired and the pointless questions sailed through, pausing the
session for answers the agent already had.

This plan captures the dogfooding decision to turn it on: immediately in this project
(done + verified live), and then to flip the shipped install/upgrade default so every
project gets the guard rail.

## Goals

- **G1** — Enable `ask_user_question_blocker` in this project's `.claude/hooks-daemon.yaml`
  and verify it fires live. **(DONE — see Notes.)**
- **G2** — Flip the shipped default to `enabled: true` in the install/upgrade config
  source(s) so new installs and upgrades get the guard rail out of the box.
- **G3** — Audit the prefix-positive guidance for clarity (the live DENY reason already
  lists tautological-question examples; confirm it's the message we want as default-on).
- **G4** — Regression coverage: a test pinning that the shipped default config has
  `ask_user_question_blocker.enabled: true` (so it cannot silently regress to off).
- **G5** — Decide whether default-on warrants a dedicated upgrade-guide note (a new
  PreToolUse block existing users will newly hit) and the next release's changelog entry.

## Non-Goals

- Changing the prefix-positive policy logic itself (Plan 00108 owns that; this is purely
  the enablement/default decision).
- Removing the `enabled: false` escape hatch — projects that genuinely want unattended,
  question-free autonomy must still be able to opt out.

## Context & Background

- Handler: `src/claude_code_hooks_daemon/handlers/pre_tool_use/ask_user_question_blocker.py`
  (prefix-positive; priority 23; `requires_event: PreToolUse for AskUserQuestion`).
- Policy origin: Plan 00108 (v3.14.0) — replaced the old always-deny "autonomous mode"
  blocker with the `ASKING BECAUSE:` prefix-positive design; shipped `enabled: false`
  with the explicit intent to flip default-on after dogfooding. This plan is that flip.
- Live DENY reason (verified this session) already coaches: state the assumed answer and
  proceed; only retry with `ASKING BECAUSE:` when options are genuinely equally valid.

## Tasks

### Phase 1: Project enablement (DONE)

- [x] **Task 1.1**: Set `ask_user_question_blocker.enabled: true` in
  `.claude/hooks-daemon.yaml` (comment updated to describe the prefix-positive policy).
- [x] **Task 1.2**: Restart daemon; verify RUNNING.
- [x] **Task 1.3**: Live probe via `.claude/hooks/pre-tool-use` — unprefixed
  `AskUserQuestion` returns `permissionDecision: deny` with the prefix guidance.

### Phase 2: Ship default-on

- [ ] **Task 2.1**: Locate the install/upgrade config source of truth for default handler
  enablement (e.g. `hooks-daemon.yaml.example` / installer config template / install code).
- [ ] **Task 2.2**: Flip the shipped default to `enabled: true`; keep the disable escape
  hatch documented.
- [ ] **Task 2.3**: Regression test pinning the shipped default = enabled (G4).
- [ ] **Task 2.4**: Run full QA (`./scripts/qa/llm_qa.py all`); restart daemon RUNNING.

### Phase 3: Docs & release

- [ ] **Task 3.1**: Decide upgrade-guide note + changelog entry for the new default-on
  block (G5); write a post-upgrade-task file if existing users need a heads-up.
- [ ] **Task 3.2**: Regenerate `.claude/HOOKS-DAEMON.md` so the handler appears in the
  active-handlers table.

## Success Criteria

- [ ] New installs and upgrades get `ask_user_question_blocker` enabled by default.
- [ ] A test prevents the default silently regressing to off.
- [ ] Full QA passes; daemon restarts RUNNING; handler fires live.
- [ ] Upgrade impact documented for existing users.

## Notes & Updates

- Phase 1 delivered this session: config flipped to `enabled: true`, daemon restarted
  (PID 126030), live probe confirmed the DENY + `ASKING BECAUSE:` guidance. Commit hash
  to be recorded with the project-config commit.
