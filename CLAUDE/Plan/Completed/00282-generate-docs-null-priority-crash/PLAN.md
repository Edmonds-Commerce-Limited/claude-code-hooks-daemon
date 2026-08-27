# Plan 00282: generate-docs / generate-playbook null-priority crash

**Status**: Complete
**Created**: 2026-08-27
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (small, well-scoped bug fix)
**Type**: Bug Fix

## Overview

A field report (see `FIELD-REPORT.md` in this folder, generalised) found that
`generate-docs` and `generate-playbook` both abort with
`'<' not supported between instances of 'NoneType' and 'int'` when **any**
handler entry in a client's `.claude/hooks-daemon.yaml` is present but omits
(or leaves empty) the `priority:` key.

Root cause: the generators read `handler_config.get(ConfigKey.PRIORITY, instance.priority)`, but `config.handlers.model_dump()` materialises the
**unset** `priority` field as an explicit `None`, so the `.get()` default is
unreachable — `None` reaches the sort key and the comparison raises. The
runtime dispatch path (`registry.py`) already guards this correctly
(`config_priority is not None`); only the two generators do not.

Reproduced in-process against this codebase:
`HandlerConfig(enabled=True).model_dump()` → `{'enabled': True, 'priority': None, 'options': {}}`, and sorting on that `None` raises.

## Goals

- Both generators produce output when a handler config omits/empties `priority`,
  falling back to the handler class's own `instance.priority`.
- One shared priority-resolution rule (DRY) reused by both generators AND the
  existing `registry.py` guard — three sites, one source of truth.
- A regression test that builds a null-priority `HandlerConfig` and asserts both
  generators still produce output (the DBF guard the dogfood config can't
  trigger, because this repo always sets `priority`).
- Secondary: the generator CLI wrappers log a diagnosable error (traceback /
  handler context), not just the bare `TypeError` string.

## Non-Goals

- NOT switching the `model_dump()` call sites to `exclude_none=True` — that is
  the broader change and risks other consumers that rely on the null keys
  being present; the targeted null-guard is the narrower, safer fix.
- NOT changing `src/claude_code_hooks_daemon/config/validator.py`'s
  membership-form priority check: it
  operates on the RAW parsed YAML (where an omitted key is genuinely absent),
  so the membership form is correct there. The misleading guidance is in the
  `constants/config.py` module docstring, which is what gets fixed.

## Technical Decisions

### Decision 1: Shared helper, not a third inline copy

`registry.py` inlines `if config_priority is not None`. Adding a third copy at
each generator would violate DRY. Add one helper (next to `ConfigKey` in
`constants/config.py`) that resolves a config priority against a fallback,
treating both absent AND `None` as "use the fallback", and use it at all three
sites. Refactoring `registry.py` to the helper is behaviour-preserving and
covered by existing runtime tests.

### Decision 2: Fix the misleading docstring at the source

`constants/config.py` lines 13-15 recommend `if ConfigKey.PRIORITY in handler_config`, which is wrong against a `model_dump()` result (the key IS
present, holding `None`). Correct the docstring so the next consumer does not
repeat the bug.

## Tasks

### Phase 1: Reproduce + RED

- [x] ✅ **Task 1.1**: In-process repro confirmed (see Overview).
- [x] ✅ **Task 1.2**: RED tests — two-handler configs (a one-element sort never
  compares) with a null priority crash both generators with the reported
  `TypeError`; helper unit tests. (`test_docs_generator.py`,
  `test_playbook_generator.py`, `test_config.py`.)

### Phase 2: Fix (GREEN)

- [x] ✅ **Task 2.1**: Added `resolve_priority` helper in `constants/config.py`
  (absent AND None both fall back; explicit 0 respected) + fixed the misleading
  module docstring.
- [x] ✅ **Task 2.2**: Used it at `docs_generator.py`, `playbook_generator.py`,
  and refactored `registry.py` to the same helper (one rule, three sites).
- [x] ✅ **Task 2.3**: Secondary — both generator CLI wrappers now
  `logger.exception(...)` the full traceback, not just the bare message.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: Daemon restarted RUNNING; `generate-docs` and
  `generate-playbook` exit 0 on this repo with no doc drift. Full QA green —
  25/25 PASSED, 14900 tests, coverage 95.1%.

## Success Criteria

- [x] Both generators produce output with a null/absent-priority handler entry.
- [x] One helper is the single source of truth across the three sites.
- [x] Regression test fails before the fix and passes after.
- [x] Full QA green; daemon restarts RUNNING.

## Dependencies

- Relates to: Plan 00070 (PyYAML parses empty `priority:` as `None`).

## Delivery & Milestones

- Fix delivered in commit `86ca861a` (shared `resolve_priority` helper; three
  sites; docstring correction; CLI traceback logging; two-handler regression
  tests). QA 25/25 green at delivery.
- Plan completed and archived in the follow-up commit alongside this line.
