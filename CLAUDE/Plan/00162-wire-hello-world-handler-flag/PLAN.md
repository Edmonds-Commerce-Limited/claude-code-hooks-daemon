# Plan 00162: wire hello world handler flag

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The `daemon.enable_hello_world_handlers` global flag is **dead code**. It is
defined in the config schema (`config/schema.py`), the config model with
`default=False` (`config/models.py:567`), the install template which writes
`enable_hello_world_handlers: false` (`daemon/init_config.py:49,111`), and a
named constant (`constants/config.py:57`). Every one of the 10 `hello_world`
handlers (one per event type) carries the docstring line
"Controlled by global config: daemon.enable_hello_world_handlers". **But no
loader, router, or FrontController code consumes the flag.** The handlers are
gated only by the ordinary per-handler `enabled` config, which defaults to
enabled (`get_default_enabled() → True`, not overridden). So the test handlers
load in every project regardless of the flag — contradicting both its documented
intent and its `false` default.

The visible cost: `hello_world_stop` injects `✅ Stop hook system active` context
on every Stop, which makes Claude Code grant another turn. During this session's
19 consecutive idle recovery ticks that doubled every tick into two stops (38
wasted turns — the finding that motivated Plan 00161). More broadly, every normal
project gets `✅ <event> hook system active` noise injected on every hook event,
despite the daemon claiming (via default + template) these are off.

This plan fixes the bug by **wiring the existing flag** so it actually gates the
`HandlerTag.TEST` handlers: when `enable_hello_world_handlers` is false (the
default), the test handlers do not run. This is DRY (one purpose-built toggle for
all 10 handlers, honouring the documented contract) and default-false, so normal
projects — and this repo, whose config already sets it false — stop loading them.
Anyone can flip it `true` to restore the `✅ hook active` confirmations when
actively debugging the hook system.

## Goals

- Make `daemon.enable_hello_world_handlers` actually gate all `HandlerTag.TEST`
  handlers; default `false` means they do not load/dispatch.
- Eliminate the field-side and idle-tick doubled-stop by removing the always-on
  `hello_world_stop` context injection from normal (and this) projects.
- Keep the handlers available for on-demand dogfooding/debugging via the flag.
- Full QA green; daemon restart RUNNING; acceptance + dogfooding suites updated
  to reflect the flag-gated behaviour.

## Non-Goals

- Not deleting the hello_world handlers — they remain for opt-in debugging.
- Not the housekeeping feature itself (Plan 00161) — this only removes the
  doubled-stop root cause that plan surfaced.
- No change to any non-TEST handler's enablement.

## Tasks

### Phase 1: TDD the flag wiring

- [ ] ⬜ **Task 1.1**: Confirm the consumer gap and the exact enablement path
  (where per-handler `enabled` and `get_default_enabled()` are resolved into the
  dispatch set) so the flag is gated at the correct single choke point.
- [ ] ⬜ **Task 1.2**: RED — test that with `enable_hello_world_handlers: false`
  no `HandlerTag.TEST` handler is in the active dispatch set for any event, and
  with `true` they all are.
- [ ] ⬜ **Task 1.3**: GREEN — wire the flag at the resolved choke point; keep
  the per-handler `enabled` semantics intact (flag is an AND-gate over TEST
  handlers). REFACTOR.

### Phase 2: Reconcile config, docs, tests

- [ ] ⬜ **Task 2.1**: Update the 10 handler docstrings if wording drifts; update
  generated `.claude/HOOKS-DAEMON.md` via `generate-docs` (test handlers should
  no longer list as active here, since this repo's flag is false).
- [ ] ⬜ **Task 2.2**: Fix any acceptance/dogfooding tests that assumed the test
  handlers were unconditionally active; add a `config-changes` manifest entry if
  the observable default changes for clients.
- [ ] ⬜ **Task 2.3**: Full QA (`./scripts/qa/llm_qa.py all`); daemon restart
  RUNNING; verify `✅ Stop hook system active` no longer injected on stop here.

## Success Criteria

- [ ] `enable_hello_world_handlers: false` (default) ⇒ zero TEST handlers active;
  `true` ⇒ all active. Covered by tests.
- [ ] No `✅ <event> hook system active` context injected in a default-config
  project; the idle-tick doubled-stop is gone.
- [ ] QA green, daemon RUNNING, HOOKS-DAEMON.md regenerated.

## Notes & Updates

### 2026-07-14

- Root-caused from Plan 00161's brainstorm: the doubled-stop is
  `hello_world_stop` injecting context on every Stop. Investigation found the
  purpose-built `enable_hello_world_handlers` flag exists but is never consumed
  (dead). Chosen fix: wire it (DRY, honours the documented contract), default
  false. See Plan 00161 Decision 3.
- Failsafe recovery cron for this session: `a8af59d9` (`:37` hourly,
  non-durable). Reused — not duplicated.
