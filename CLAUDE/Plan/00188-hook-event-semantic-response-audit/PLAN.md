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

- [x] ✅ **Task 1.1**: Obtain authoritative Claude Code response contract for every
  wired event (claude-code-guide agent + https://code.claude.com/docs/en/hooks +
  direct WebFetch of `hooks.md`).
- [x] ✅ **Task 1.2**: Build the per-event audit matrix (see table below): parse
  mode, `{}` verdict, current daemon behaviour.
- [x] ✅ **Task 1.3**: Probe the live daemon for each event's actual returned JSON
  (via the forwarder scripts) → `scratchpad/event-probe.txt`.
- [x] ✅ **Task 1.4**: Rank findings by severity. Result: 1 BROKEN
  (`WorktreeCreate`), 2 safe-but-subtle (`UserPromptExpansion`, `Elicitation`),
  28 safe.

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

## Audit Matrix (Phase 1 — COMPLETE)

**Sources:** authoritative Claude Code hooks docs (https://code.claude.com/docs/en/hooks

- `hooks.md`, fetched 2026-07-24) cross-checked against an empirical probe of every
  forwarder (`scratchpad/event-probe.txt`).

**The governing distinction:** Claude Code parses a hook's stdout in one of two
ways. **Decision/context events** parse stdout as a JSON object → an empty `{}`
means "no decision / no added context" → **SAFE fail-open**. **Data-return
events** parse stdout as a raw value → `{}` is taken literally as that value →
**corrupts the feature**. Only `WorktreeCreate` returns a raw value (the worktree
path), which is why it is the sole genuinely-broken event: `{}` becomes the path
`/workspace/{}`.

| Event               | Parse mode                | `{}` verdict   | Current daemon | Note                                                                                                                                       |
| ------------------- | ------------------------- | -------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| WorktreeCreate      | RAW PATH (stdout)         | 🚫 BROKEN      | `{}`           | Only true break. Hook must `git worktree add` + print abs path; `{}`→`/workspace/{}` fails creation                                        |
| WorktreeRemove      | side-effect only          | ✅ SAFE        | `{}`           | CC removes the dir itself; hook is informational                                                                                           |
| UserPromptExpansion | JSON decision / raw text  | ⚠️ SAFE-SUBTLE | `{}`           | `{}` is valid JSON = no decision = expansion proceeds. A client handler that prints RAW text replaces the prompt — must not emit `{}` then |
| Elicitation         | JSON `hookSpecificOutput` | ⚠️ SAFE-SUBTLE | `{}`           | `{}` = no auto-response → dialog proceeds to user normally. Not broken; a handler wanting to auto-answer must emit `action`/`content`      |
| ElicitationResult   | JSON `hookSpecificOutput` | ✅ SAFE        | `{}`           | `{}` = user response passes through unchanged                                                                                              |
| PreToolUse          | JSON decision             | ✅ SAFE        | `{}`/deny      | `{}` = allow                                                                                                                               |
| PostToolUse         | JSON decision             | ✅ SAFE        | `{}`           | `{}` = no feedback                                                                                                                         |
| PermissionRequest   | JSON decision             | ✅ SAFE        | `{}`           | `{}` = defer to normal prompt (auto_approve_reads relies on this)                                                                          |
| PermissionDenied    | observe                   | ✅ SAFE        | `{}`           | notification-only                                                                                                                          |
| Stop                | JSON decision             | ✅ SAFE        | block/`{}`     | `{}` = allow stop                                                                                                                          |
| StopFailure         | observe                   | ✅ SAFE        | `{}`           | notification-only                                                                                                                          |
| SubagentStart       | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| SubagentStop        | JSON decision/context     | ✅ SAFE        | ctx/`{}`       |                                                                                                                                            |
| SessionStart        | context                   | ✅ SAFE        | ctx            | `{}` = no added context                                                                                                                    |
| SessionEnd          | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| Setup               | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| UserPromptSubmit    | context                   | ✅ SAFE        | ctx            |                                                                                                                                            |
| Notification        | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| MessageDisplay      | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| TaskCreated         | JSON decision             | ✅ SAFE        | `{}`           | `{}` = allow                                                                                                                               |
| TaskCompleted       | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| TeammateIdle        | JSON decision             | ✅ SAFE        | `{}`           | `{}` = no directive                                                                                                                        |
| InstructionsLoaded  | context                   | ✅ SAFE        | `{}`           | `{}` = no injected instructions                                                                                                            |
| ConfigChange        | JSON decision             | ✅ SAFE        | `{}`           | `{}` = accept change                                                                                                                       |
| CwdChanged          | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| FileChanged         | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| PreCompact          | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| PostCompact         | observe                   | ✅ SAFE        | `{}`           |                                                                                                                                            |
| Status (statusLine) | RAW text                  | ✅ SAFE        | rendered line  | Real handler renders the line; works correctly                                                                                             |

**Headline:** 1 genuinely broken (`WorktreeCreate`), 2 safe-but-subtle
(`UserPromptExpansion`, `Elicitation` — safe today, land-mines for a future
client handler), 28 safe. The Plan 00170 "wire everything as `{}` passthrough"
model is sound for every JSON-parsed event and wrong only for the raw-value
events; `WorktreeCreate` is the one raw-value event wired as if it were a
decision event.

## Success Criteria

- [ ] `isolation: "worktree"` sub-agents launch successfully (WorktreeCreate fixed).
- [ ] Every event in the audit matrix has a verdict; every BROKEN one is fixed.
- [ ] A regression test guards each mandatory-response contract.
- [ ] Full QA passes; daemon restarts RUNNING.
- [ ] Scratch report `untracked/hooks-daemon-worktree-bug.md` resolved/removed.

## Delivery & Milestones

- Plan created; recovery cron `7a4541bc` (hourly :37).
