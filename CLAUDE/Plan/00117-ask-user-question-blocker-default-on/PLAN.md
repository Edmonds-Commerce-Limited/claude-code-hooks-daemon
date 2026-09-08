# Plan 00117: Enable ask_user_question_blocker (dogfood → default-on)

**Status**: Complete
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
  source(s) so new installs and upgrades get the guard rail out of the box. **(DONE —
  see Task 2.2: the runtime default was already `true` for every install; the template
  was missing an explicit entry, now fixed.)**
- **G3** — Audit the prefix-positive guidance for clarity (the live DENY reason already
  lists tautological-question examples; confirm it's the message we want as default-on).
  **(DONE — Plan 00234's independent handler-value audit already reviewed this exact
  message, verdict KEEP/high value.)**
- **G4** — Regression coverage: a test pinning that the shipped default config has
  `ask_user_question_blocker.enabled: true` (so it cannot silently regress to off).
  **(DONE — see Task 2.3.)**
- **G5** — Decide whether default-on warrants a dedicated upgrade-guide note (a new
  PreToolUse block existing users will newly hit) and the next release's changelog entry.
  **(DECIDED — see Task 3.1: no note needed, no new block, default was already live.)**

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

- [x] **Task 2.1**: Locate the install/upgrade config source of truth for default handler
  enablement — `ConfigTemplate.generate_full()` in
  `src/claude_code_hooks_daemon/daemon/init_config.py`, written by `cmd_init_config`
  (default mode `full`). Found the handler was entirely absent from that template.
- [x] **Task 2.2**: Flip the shipped default to `enabled: true`; keep the disable escape
  hatch documented. The RUNTIME default was already `true` for every install —
  `HandlerRegistry.discover()` resolves an absent handler config key via
  `handler_config.get(ConfigKey.ENABLED, True)`, a fallback present since the initial
  commit, long predating this handler. Added an explicit
  `ask_user_question_blocker: {enabled: true, priority: 10}` line to `generate_full()`
  for template completeness/discoverability; no runtime behaviour changed. See JOURNAL.
- [x] **Task 2.3**: Regression test pinning the shipped default = enabled (G4). The
  drift-guard test named in the base class docstring
  (`tests/unit/daemon/test_default_enabled_template_consistency.py`) already existed
  and already covers this (the plan's original premise that it was missing was wrong —
  verified by running it). Added a direct per-handler pin
  (`test_default_enabled_is_true`) to `test_ask_user_question_blocker.py`, matching the
  convention ~12 other opt-out handlers already use. Also removed two now-incorrect
  "opt-in" exemptions (`tests/daemon/test_init_config.py::EXCLUDED_HANDLERS`,
  `tests/integration/test_dogfooding_config.py::opt_in_handlers`) that were masking the
  Task 2.2 template gap.
- [x] **Task 2.4**: Run full QA (`./scripts/qa/llm_qa.py all`). Daemon restart NOT
  performed — this worktree may not restart the shared project daemon (isolation rule);
  runtime enablement was verified by code inspection (Task 2.2) and the passing test
  suite instead. See JOURNAL for the QA run log.

### Phase 3: Docs & release

- [x] **Task 3.1**: Decide upgrade-guide note + changelog entry for the new default-on
  block (G5). Decision: none needed — there is no new block. `git log -S` on the
  registration fallback plus the handler's own history (commit `15211df5`, Plan 00108,
  CHANGELOG v3.14.0 / 2026-05-15) show it has been functionally enabled-by-default since
  it shipped; the CHANGELOG's contemporaneous "Disabled by default" line and the
  handler's own module docstring were themselves inaccurate (also flagged separately by
  Plan 00234's audit). Fixed the docstring today. See the Success Criteria line below
  and JOURNAL for the full trace.
- [x] **Task 3.2**: Regenerate `.claude/HOOKS-DAEMON.md` so the handler appears in the
  active-handlers table. No action needed — it is auto-generated on daemon restart (per
  its own header) and already lists `ask_user_question_blocker` (priority 23, TERMINAL)
  as of the project's most recent restart.

## Success Criteria

- [x] New installs and upgrades get `ask_user_question_blocker` enabled by default.
- [x] A test prevents the default silently regressing to off.
- [x] Full QA passes; daemon restarts RUNNING; handler fires live. Full-suite run
  (`llm_qa.py all`): 23/26 PASSED. The 3 failures (`magic_values`, `tests`,
  `error_hiding`) all trace to one pre-existing defect in
  `src/claude_code_hooks_daemon/install/transport_verify.py` (`git blame` → commit
  `0613c331e1`, Plan 00295, same day, a file this plan never touches) — confirmed by
  `git blame`/`git log`, out of this plan's scope to fix. Every check touching this
  plan's 5 changed files passes. Daemon restart NOT performed here (worktree isolation
  rule forbids restarting the shared project daemon); Phase 1 already verified the
  handler firing live against a real daemon restart, and nothing in Phase 2/3 changes
  runtime behaviour (see Tasks 2.2/3.1).
- [x] Upgrade impact documented for existing users. N/A — the default was already live
  before this plan's changes, so there is no new impact to document (see the criterion
  below).
- [x] This plan has no release-bound consequences: `ask_user_question_blocker` has been
  functionally enabled by default since it shipped in **v3.14.0** (2026-05-15, Plan
  00108, commit `15211df5`) — `HandlerRegistry.discover()`'s fallback
  (`handler_config.get(ConfigKey.ENABLED, True)`) predates the handler itself, and it has
  never overridden `get_default_enabled()`. Today's changes (template entry, docstring
  fix, stale test-exemption removal, a direct regression-pin test) make that already-true
  fact visible and protected; they change no existing or fresh install's behaviour, so no
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` callout is warranted (its own README:
  "test-only and internal refactors usually do not" need one).

## Notes & Updates

- Phase 1 delivered this session: config flipped to `enabled: true`, daemon restarted
  (PID 126030), live probe confirmed the DENY + `ASKING BECAUSE:` guidance. Commit hash
  to be recorded with the project-config commit.
- Phase 2/3 delivered in a worktree session: see `JOURNAL/00117-Journal-26-09-08.md` for
  the full investigation trail (drift-guard test already existed, template gap, runtime
  registration-fallback trace, CHANGELOG/docstring staleness, QA run).
