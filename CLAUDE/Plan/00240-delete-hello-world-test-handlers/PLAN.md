# Plan 00240: delete hello world test handlers

**Status**: Not Started
**Created**: 2026-08-14
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The `hello_world` handlers — one per event type — inject `✅ <event> hook system active` context to confirm the hook pipeline is alive. They date from the
project's earliest days, and the maintainer's judgement is that they have been
superseded.

They are already inert. Plan 00162 wired the `daemon.enable_hello_world_handlers`
flag that had been dead config, and that shipped in v3.40.0: `registry.py:336`
now skips every `HandlerTag.TEST` handler unless the flag is true, and the flag
defaults false in both the model and the install template. So no client project
has been loading them since v3.40.0, and this repo's own config sets it false.
This plan is therefore removal of DORMANT code, not a fix for live noise — a
distinction worth keeping straight when judging urgency.

Nothing is lost by deleting them, because the job they were built for is already
done better elsewhere. `scripts/qa/run_smoke_test.sh` probes the LIVE daemon
through the production hook scripts with three real payloads (a Stop, a Stop with
a transcript, and a `PreToolUse` carrying a destructive git command) and asserts
the decisions. That runs in every QA pass, exercises real handlers rather than a
canary, and proves strictly more than a `✅ hook active` echo ever did.

## Goals

- Delete the `hello_world` handler modules and every reference that would
  dangle without them.
- Delete `daemon.enable_hello_world_handlers` — schema, model, install
  template, constant, registry gate and the `DocsGenerator` threading — since
  its only purpose was gating the handlers being removed.
- Register the removal so an existing client daemon does not degrade: retired
  handler registry entries, a removed-config-key manifest, and an upgrade note.
- Leave the framework's own "handlers load" coverage intact, replacing any test
  that depended on a `hello_world` handler existing rather than deleting it.

## Non-Goals

- Not removing `HandlerTag.TEST` itself if anything else uses it.
- Not touching the plugin or project-handler example handlers, which are a
  separate teaching surface.
- Not changing `run_smoke_test.sh` — it already covers the canary's job and
  needs no extension for this.

## Context & Background

Plan 00162 deliberately kept the handlers ("Non-Goals: not deleting the
hello_world handlers — they remain for opt-in debugging"). That judgement is now
reversed by the maintainer. The reversal is recorded rather than glossed,
because the earlier reasoning was sound at the time and the thing that changed
is the cost/benefit, not a discovered error: an opt-in nobody opts into is
carrying ten modules, a config key across four files, a registry branch and a
docs-generator branch.

Plan 00162's remaining task was "ship in the next release, then close the plan".
The work shipped in v3.40.0 and the plan was never closed, which is why it has
been sitting stale. It is closed as part of this plan's first task rather than
being repurposed — its goal succeeded, and deleting the handlers is a later,
separate decision.

## Tasks

### Phase 1: Close the predecessor and take inventory

- [x] ✅ **Task 1.1**: Plan 00162 closed and archived. The "shipped in v3.40.0"
  claim was VERIFIED rather than taken from its notes — `git tag --contains`
  on the wiring commit `ca03facb` returns v3.40.0 as the first tag. Its success
  criteria were re-checked against the live daemon too (a real `SessionStart`
  through the production forwarder injects zero occurrences of the canary
  text), so the plan was closed on evidence rather than on its own say-so
- [x] ✅ **Task 1.2**: Surface enumerated. **10 handler modules** (one per event
  type: notification, permission_request, post_tool_use, pre_compact,
  pre_tool_use, session_end, session_start, stop, subagent_stop,
  user_prompt_submit). **12 other `src/` files** reference them: `config/models.py`,
  `config/schema.py`, `constants/config.py`, `constants/handlers.py`,
  `constants/priority.py`, `core/hook_result.py`, `daemon/cli.py`,
  `daemon/controller.py`, `daemon/docs_generator.py`, `daemon/init_config.py`,
  `handlers/registry.py`, `utils/naming.py`. **16 test files**, of which two are
  dedicated and get deleted (`test_hello_world.py`, `test_hello_world_config.py`)
  and fourteen get amended
- [x] ✅ **Task 1.3**: Two references are DOCUMENTATION, not dependencies, and
  must be reworded rather than deleted — `core/hook_result.py:370` names
  `hello_world_stop` in a docstring explaining unconditional advisory handlers,
  and `utils/naming.py:32/61/80` uses `HelloWorldPreToolUseHandler` as the
  worked example for all three naming conversions (with `tests/unit/utils/test_naming.py`
  asserting against it). Both need a replacement example that still exists.
  `.claude/HOOKS-DAEMON.md` counts are generated and already exclude TEST
  handlers, so they need only a regenerate. The retired-handler registry is
  `RETIRED_HANDLERS: dict[str, str]` at `constants/handlers.py:669`, mapping
  handler id to a user-facing explanation, consumed by `config/validator.py` —
  ten entries needed

### Phase 2: Remove

- [x] ✅ **Task 2.1**: 10 modules `git rm`'d, exports and registry entries gone
- [x] ✅ **Task 2.2**: Config key removed end to end — model, schema, constant,
  install template, `register_all` parameter, controller call site,
  `DocsGenerator` threading, and this repo's own `.claude/hooks-daemon.yaml`
- [x] ✅ **Task 2.3**: Tests amended, coverage replaced rather than dropped.
  The notable one: `test_controller.py::test_process_request` used the canary
  purely to guarantee handler output; it now routes a command `destructive_git`
  DENIES, which is a stronger vehicle because it exercises matching and the
  deny path as well as routing. Only tests whose entire subject was the removed
  feature were deleted. Also renamed `Priority.HELLO_WORLD` →
  `Priority.TEST_HANDLER` (same value): it is used across the suite for
  purpose-built fixtures, so it outlives the handlers — only the name was wrong
  - The two dedicated files (`test_hello_world.py`,
    `test_hello_world_config.py`) were deleted; 14 others amended

### Phase 3: Register the removal and verify

- [x] ✅ **Task 3.1**: Ten `RETIRED_HANDLERS` entries, one per event type, so a
  client config still carrying `hello_world_*:` blocks validates cleanly
  instead of tipping the daemon into DEGRADED MODE
- [x] ✅ **Task 3.2**: `UNRELEASED/config-changes/v3.53.0.yaml` records the
  removed key with a migration note, including the replacement way to verify
  hooks are wired (send a command a real handler denies)
- [x] ✅ **Task 3.3**: `.claude/HOOKS-DAEMON.md` regenerated (85 handler rows,
  13 event sections). Priority-range docs updated in `CLAUDE.md`,
  `CONTRIBUTING.md`, `CLAUDE/HANDLER_DEVELOPMENT.md`,
  `docs/guides/CONFIGURATION.md` and `docs/guides/HANDLER_REFERENCE.md`; the
  `GETTING_STARTED.md` "enable the canary to check hooks work" section is
  replaced by one that sends a command a real handler blocks
- [ ] ⬜ **Task 3.4**: Full QA; daemon restart RUNNING; client-mode
  verification that a config still carrying the removed key starts cleanly

## Success Criteria

- [ ] No `hello_world` module, handler ID, or config key remains in the tree
- [ ] A client config that still sets `enable_hello_world_handlers` starts the
  daemon without error, verified in the dummy client repo
- [ ] QA green with no hardcoded-count regressions; daemon RUNNING
- [ ] Framework coverage that previously leaned on a `hello_world` handler is
  replaced, not dropped

## Delivery & Milestones

- Supersedes the "keep them for opt-in debugging" non-goal of
  [Plan 00162](../Completed/00162-wire-hello-world-handler-flag/PLAN.md)
