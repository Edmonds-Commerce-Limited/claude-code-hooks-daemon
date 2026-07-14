# Plan 00162: wire hello world handler flag

**Status**: In Progress
**Created**: 2026-07-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The `daemon.enable_hello_world_handlers` global flag is **dead code**. It is
defined in the config schema (`src/claude_code_hooks_daemon/config/schema.py`),
the config model with `default=False`
(`src/claude_code_hooks_daemon/config/models.py`), the install template which
writes `enable_hello_world_handlers: false`
(`src/claude_code_hooks_daemon/daemon/init_config.py`), and a named constant
(`src/claude_code_hooks_daemon/constants/config.py`). Every one of the 10 `hello_world`
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

- [x] ✅ **Task 1.1**: Confirmed the consumer gap — the flag is defined in
  schema/model/template/constant and every hello_world docstring, but no loader
  code reads it. The choke point is `HandlerRegistry.register_all` pass 2
  (per-handler `enabled` at line 279; tag filters at 292).
- [x] ✅ **Task 1.2**: RED — added registry tests asserting default-off gates all
  `HandlerTag.TEST` handlers and `enable_hello_world_handlers=True` restores them.
- [x] ✅ **Task 1.3**: GREEN — added `enable_hello_world_handlers` param to
  `register_all` (default False), gating TEST handlers alongside the existing tag
  filters; `DaemonController.initialise` passes `self._config.enable_hello_world_handlers`.

### Phase 2: Reconcile config, docs, tests

- [x] ✅ **Task 2.1**: Regenerated `.claude/HOOKS-DAEMON.md` — the 10 test
  handlers are gone from the active list. Threaded the flag through `DocsGenerator`
  (it enumerated all discovered handlers with the same blind spot) so the doc
  reflects the daemon's real active set. Handler docstrings already say
  "Controlled by global config: daemon.enable_hello_world_handlers" — now TRUE, no
  change needed.
- [x] ✅ **Task 2.2**: Fixed the 2 tests that assumed test handlers were always
  active (`test_daemon_smoke.test_daemon_processes_pre_tool_use_hook` → asserts the
  benign no-op shape; `test_controller.test_process_request` → enables the canary
  explicitly). Added a `config-changes/v3.40.0.yaml` entry documenting the flag now
  takes effect.
- [x] ✅ **Task 2.3**: Full QA 13/13 (9923 passed, 95.6% cov); daemon restarted
  RUNNING; live-probed the Stop hook — `✅ Stop hook system active` injection is
  gone (only the `auto_continue_stop` block remains).

### Phase 3: Release

- [ ] ⬜ **Task 3.1**: Ship in the next release (changes are unreleased); then
  close the plan (git mv to Completed/, README move + stats).

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
- Implementation delivered: `register_all` + `DaemonController` gate (registry
  choke point), `DocsGenerator` + `generate-docs` CLI gate, 2 test fixes, doc
  regen, config-changes manifest. QA 13/13 (9923 passed, 95.6%); daemon RUNNING;
  Stop-hook injection confirmed gone by live probe. Unreleased — Phase 3 ships it.
