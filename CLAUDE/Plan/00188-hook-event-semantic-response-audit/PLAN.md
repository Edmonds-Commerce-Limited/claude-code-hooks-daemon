# Plan 00188: hook event semantic response audit

**Status**: In Progress
**Created**: 2026-07-24
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00170 achieved **structural** hook-coverage completeness: every Claude Code
hook event is catalogued in `EventID`, has a forwarder script, an input+response
schema, and a `settings.json` registration. The completeness gate
(`tests/integration/test_hook_coverage_completeness.py`) enforces that wiring.

However, structural wiring only proves an event is *dispatchable* — it does NOT
prove the daemon's response is **semantically correct** for that event's Claude
Code contract. Most events are safe to "fail-open" (return an empty `{}` when no
handler matches: allow/continue). But some events have a **mandatory response
contract**: Claude Code expects the hook to return specific data, and an empty
`{}` breaks the feature.

**Confirmed instance (High severity):** `WorktreeCreate`. Launching an Agent with
`isolation: "worktree"` fails with `WorktreeCreate hook returned a path that is not a directory: /workspace/{}. The hook must create the directory before echoing its path.` The daemon returns `{}` (empty passthrough) because no handler exists —
but this event REQUIRES the hook to create the git worktree directory and echo its
absolute path. Fail-open is wrong here. (Original scratch report:
`untracked/hooks-daemon-worktree-bug.md`.)

This plan audits **every** wired hook event against its real Claude Code response
contract, classifies each as *fail-open-safe* vs *mandatory-response*, fixes every
mis-handled event (starting with `WorktreeCreate`), and adds an enforcement layer
so semantic-contract regressions are caught the same way structural drift is.

## Goals

- Produce an authoritative per-event audit matrix: for each wired event, its
  Claude Code response contract and whether the daemon's current default
  behaviour (`{}` passthrough) satisfies it.
- Fix `WorktreeCreate` so `isolation: "worktree"` sub-agents work (create dir +
  echo absolute path), with TDD + regression test + live dogfood.
- Fix every other event the audit flags as mandatory-response.
- Add a semantic-contract enforcement layer (test + optionally a
  `response_schemas` requirement) so a mandatory-response event can never silently
  regress to `{}` passthrough.
- Dogfood every wired event where dogfooding is possible in this session, and
  document the ones that are not directly triggerable.

## Non-Goals

- NOT adding rich feature handlers for events that are genuinely fail-open-safe
  (YAGNI — a client project attaches those). We only guarantee *correct default
  response contract*, not bespoke behaviour.
- NOT editing anything under `.claude/hooks-daemon/` (this repo IS the upstream;
  fixes land in `src/`).
- NOT changing the Plan 00170 structural completeness gate's intent (it stays).

## Context & Background

- `constants/events.py` — `EventID` catalogue (SSoT). `can_block` and `category`
  per event. All events currently `wired=True`, `EXPECTED_UNWIRED` empty.
- `core/event.py` — `EventType` dispatch enum.
- `core/router.py` / `core/chain.py` — a no-handler chain yields the default
  allow/continue result → serialised as `{}`.
- `core/response_schemas.py` / `core/input_schemas.py` — schema registries.
- `.claude/hooks/<bash_key>` — thin forwarders (relay stdin to socket).
- Probe result: `echo '{"hook_event_name":"WorktreeCreate",...}' | bash .claude/hooks/worktree-create` → `{}` (confirms empty passthrough).

## Tasks

### Phase 1: Audit (research + classify)

- [ ] 🔄 **Task 1.1**: Obtain authoritative Claude Code response contract for every
  wired event (claude-code-guide agent + https://code.claude.com/docs/en/hooks).
- [ ] ⬜ **Task 1.2**: Build the per-event audit matrix (see table below): contract,
  fail-open-safe? mandatory-response? current daemon behaviour, verdict.
- [ ] ⬜ **Task 1.3**: Probe the live daemon for each event's actual returned JSON
  (via the forwarder scripts) to confirm current behaviour empirically.
- [ ] ⬜ **Task 1.4**: Rank findings by severity (breaks a feature > cosmetic).

### Phase 2: Fix WorktreeCreate (confirmed High)

- [ ] ⬜ **Task 2.1**: RED — failing test: `WorktreeCreate` response must (a) create
  the worktree dir, (b) echo an absolute path under the repo, (c) contain no
  `{`/`}` template placeholder.
- [ ] ⬜ **Task 2.2**: GREEN — implement a built-in `WorktreeCreate` handler (and
  `WorktreeRemove` teardown) that materialises the worktree and returns its path.
- [ ] ⬜ **Task 2.3**: REFACTOR + coverage ≥95%.
- [ ] ⬜ **Task 2.4**: Restart daemon; live-dogfood an `isolation: "worktree"` agent.

### Phase 3: Fix other mandatory-response events flagged in Phase 1

- [ ] ⬜ **Task 3.1**: For each flagged event, TDD fix (one checkpoint commit each).

### Phase 4: Enforcement

- [ ] ⬜ **Task 4.1**: Add a `mandatory_response` marker to `EventIDMeta` (or an
  equivalent registry) and a test that fails if a mandatory-response event's
  default behaviour is empty passthrough.
- [ ] ⬜ **Task 4.2**: Extend the completeness gate docs to cover the semantic layer.

### Phase 5: Dogfood + close

- [ ] ⬜ **Task 5.1**: Dogfood each triggerable event; document the untriggerable.
- [ ] ⬜ **Task 5.2**: Full QA, daemon restart RUNNING, clean up scratch report.

## Audit Matrix (populated in Phase 1)

| Event                         | can_block | Claude Code response contract                 | Fail-open `{}` safe? | Current daemon | Verdict         |
| ----------------------------- | --------- | --------------------------------------------- | -------------------- | -------------- | --------------- |
| WorktreeCreate                | true      | MUST create worktree dir + echo absolute path | ❌ NO                | `{}`           | 🚫 BROKEN — fix |
| _(rest populated in Phase 1)_ |           |                                               |                      |                |                 |

## Success Criteria

- [ ] `isolation: "worktree"` sub-agents launch successfully (WorktreeCreate fixed).
- [ ] Every event in the audit matrix has a verdict; every BROKEN one is fixed.
- [ ] A regression test guards each mandatory-response contract.
- [ ] Full QA passes; daemon restarts RUNNING.
- [ ] Scratch report `untracked/hooks-daemon-worktree-bug.md` resolved/removed.

## Delivery & Milestones

- Plan created; recovery cron `7a4541bc` (hourly :37).
