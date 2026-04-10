# Plan 00097: Project Handler Upgrade Resilience

**Status**: Complete (2026-04-02)
**Created**: 2026-04-02
**Owner**: Claude
**Priority**: High (Hotfix)
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

v2.30.0 made `get_claude_md()` an abstract method on the `Handler` base class. Any project-level
handler written before v2.30.0 that does not implement it is now silently treated as abstract
by Python and filtered out by `inspect.isabstract()`, producing the unhelpful error
"No Handler subclass found in project handler file" rather than "missing abstract method
get_claude_md (added in v2.30.0)".

Worse, `discover_handlers()` in `controller.py:356` has no try/except — a single broken
project handler crashes the entire daemon at startup. The TIER 1 FAIL FAST approach was
correct for bugs in built-in handlers (we own them), but is wrong for project handlers
(users own them; an upstream upgrade breaking their handler must not kill their session).

This plan fixes three things:

1. **Crash resilience**: broken project handlers skip gracefully, daemon always starts
2. **Actionable errors**: detect missing abstract methods by name, emit version-specific fix instructions pointing to upgrade guides
3. **Upgrade guide**: create `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/` documenting the `get_claude_md()` migration

A SessionStart advisory handler and release process improvements are out of scope here —
they can be follow-on plans once the hot path is fixed.

## Goals

- Daemon always starts even if all project handlers are broken
- Broken project handlers emit clear, actionable error messages with version context
- `validate-project-handlers` exits non-zero on failures and includes version guidance
- Upgrade guide exists for v2.29→v2.30 covering the `get_claude_md()` breaking change
- Release process Step 6.5 has a Handler ABC checklist item to prevent recurrence

## Non-Goals

- Fixing existing project handlers in user repos (out of scope — user's responsibility)
- SessionStart advisory that auto-validates handlers (follow-on plan)
- Automated migration scripts

## Context & Background

### The three bugs being fixed

**Bug 1 — Daemon crash**: `discover_handlers()` (`project_loader.py:193`) calls
`load_handler_from_file()` with no try/except. Any RuntimeError propagates to
`controller.py:356` (also no try/except), crashing daemon startup.

**Bug 2 — Silent abstract filtering**: `load_handler_from_file()` filters classes with
`inspect.isabstract(attr)` (line 89). A handler missing `get_claude_md()` is abstract,
silently filtered, then reported as "No Handler subclass found" — no mention of which
method is missing or when it was added.

**Bug 3 — No upgrade guide**: v2.30.0 released with a breaking Handler ABC change
(`get_claude_md()` → abstract) without a corresponding upgrade guide in
`CLAUDE/UPGRADES/v2/v2.29-to-v2.30/`, violating the release process Step 6.5.

### Abstract method version registry

To produce version-aware error messages, we need a small registry mapping abstract method
names to the daemon version that introduced them. This lives as a module-level constant
in `project_loader.py` (or a shared constants file) — no external dependency.

```python
_ABSTRACT_METHOD_VERSIONS: dict[str, str] = {
    "get_claude_md": "2.30.0",
    "get_acceptance_tests": "2.28.0",  # approximate — check git log
}
```

### Graceful degradation policy for project handlers

Built-in handlers: FAIL FAST is correct (we own them, failures = bugs in our code)
Project handlers: SKIP + WARN is correct (users own them, failures = upgrade mismatch or user error)

Broken project handlers should:

- Log a structured error with filename, reason, and fix guidance
- Be skipped (omitted from registered handlers)
- Cause `discover_handlers()` to return partial results (working handlers still load)
- Never propagate RuntimeError to caller

## Tasks

### Phase 1: Fix project_loader.py

- [x] **Task 1.1**: Add abstract method detection helper

  - \[x\]Add `_ABSTRACT_METHOD_VERSIONS` dict constant to `project_loader.py`
  - \[x\]Add `_get_missing_abstract_methods(cls)` helper that returns list of `(method_name, version)` tuples for any abstract methods not overridden
  - \[x\]Write tests for helper: returns empty list for concrete class, returns methods for abstract class
  - TDD: write tests first in `tests/unit/handlers/test_project_loader.py`

- [x] **Task 1.2**: Improve error message when no concrete handler found

  - \[x\]In `load_handler_from_file()`, before the "No Handler subclass found" raise, scan handler-shaped classes (subclasses of Handler, even abstract ones) and call `_get_missing_abstract_methods()`
  - \[x\]If missing methods found: raise with `"HandlerClass is missing abstract methods introduced in: get_claude_md (v2.30.0). Add: def get_claude_md(self) -> str | None: return None — see CLAUDE/UPGRADES/v2/v2.29-to-v2.30/"`
  - \[x\]If no abstract subclasses either: keep existing "No Handler subclass found" message
  - \[x\]Tests: missing get_claude_md produces version-specific message; class with all methods produces no such message

- [x] **Task 1.3**: Make discover_handlers() skip broken handlers (don't crash)

  - \[x\]Wrap `load_handler_from_file(py_file)` call in try/except RuntimeError in `discover_handlers()`
  - \[x\]On failure: log structured warning with filename + full error message; continue to next file
  - \[x\]Collect failures into a list; after loop, if any failures: log summary "N project handler(s) failed to load; daemon started with remaining handlers"
  - \[x\]Tests: a directory with one broken and one working handler loads the working one and logs a warning for the broken one

- [x] **Task 1.4**: Run QA and daemon restart

  - \[x\]`./scripts/qa/run_all.sh` — all checks must pass
  - \[x\]`$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && $PYTHON -m claude_code_hooks_daemon.daemon.cli status`

- [x] **Task 1.5**: Checkpoint commit

  - \[x\]`git add` specific files, commit `Fix: project handler load failures no longer crash daemon`

### Phase 2: Fix validate-project-handlers CLI command

- [x] **Task 2.1**: Exit non-zero on failures

  - \[x\]In `cmd_validate_project_handlers()` (`cli.py`), track a `has_failures` boolean
  - \[x\]When a handler fails to load (RuntimeError), set `has_failures = True`
  - \[x\]Return `1` from the command function if `has_failures` is True
  - \[x\]Tests: command returns 1 when a broken handler exists

- [x] **Task 2.2**: Surface version-specific guidance in CLI output

  - \[x\]When failure message contains a version string (e.g. "v2.30.0"), print an additional line: `→ Upgrade guide: CLAUDE/UPGRADES/v2/v2.29-to-v2.30/`
  - \[x\]This should be a general pattern — parse the version from the error message and construct the upgrade guide path
  - \[x\]Tests: output includes upgrade guide path when version is in error message

- [x] **Task 2.3**: Run QA and daemon restart

  - \[x\]`./scripts/qa/run_all.sh`
  - \[x\]Daemon restart verification

- [x] **Task 2.4**: Checkpoint commit

  - \[x\]`git add` specific files, commit `Fix: validate-project-handlers exits non-zero and shows upgrade guide on failure`

### Phase 3: Create upgrade guide for v2.29→v2.30

- [x] **Task 3.1**: Create upgrade guide directory and files

  - \[x\]`mkdir -p CLAUDE/UPGRADES/v2/v2.29-to-v2.30/`
  - \[x\]Create `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/README.md` following the template at `CLAUDE/UPGRADES/upgrade-template/README.md`
  - \[x\]Content must cover:
    - Summary: `get_claude_md()` is now abstract on Handler
    - Which versions are affected: any project handler written before v2.30.0
    - Exact fix: add `def get_claude_md(self) -> str | None: return None` to each handler
    - How to detect affected handlers: `$PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers`
    - Verification steps
  - \[x\]Create `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/verification.sh` that runs validate-project-handlers and checks exit code

- [x] **Task 3.2**: Update RELEASES/v2.30.0.md to reference upgrade guide

  - \[x\]Add `⚠️ BREAKING CHANGES` section if not present
  - \[x\]Add link to `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/`

- [x] **Task 3.3**: Checkpoint commit

  - \[x\]Commit `Add: upgrade guide v2.29→v2.30 for get_claude_md() breaking change`

### Phase 4: Update release process to prevent recurrence

- [x] **Task 4.1**: Add Handler ABC checklist to RELEASING.md Step 6.5

  - \[x\]In `CLAUDE/development/RELEASING.md`, in the "Breaking Changes Check" section, add a specific check:
    > **Handler ABC check**: If any abstract method was added to or removed from `Handler` in `core/handler.py`, the upgrade guide MUST document: the method name, the version it was added, the exact stub to add (`def method(self) -> ...: return ...`), and how to detect affected handlers via `validate-project-handlers`.
  - \[x\]Also add: before publishing, verify `_ABSTRACT_METHOD_VERSIONS` in `project_loader.py` is updated to include the new method

- [x] **Task 4.2**: Update `_ABSTRACT_METHOD_VERSIONS` to be accurate

  - \[x\]Verify `get_acceptance_tests` version in git log
  - \[x\]Ensure all current abstract methods are in the registry

- [x] **Task 4.3**: Final QA run and daemon restart

  - \[x\]`./scripts/qa/run_all.sh`
  - \[x\]Daemon restart + status check

- [x] **Task 4.4**: Final checkpoint commit

  - \[x\]Commit `Add: Handler ABC version registry and release process checklist`

## Dependencies

- Depends on: nothing
- Blocks: future patch release (v2.30.1) if warranted

## Technical Decisions

### Decision 1: Skip vs crash for project handler failures

**Context**: Current TIER 1 FAIL FAST applies to project handlers same as built-ins.
**Options**:

1. Keep FAIL FAST — users must fix before daemon starts
2. Skip + warn — broken handlers are ignored, daemon starts with remainder

**Decision**: Skip + warn. Rationale: project handlers are user code; an upstream breaking change to the Handler ABC should not make a user's entire dev session unusable. The daemon still starts, still protects them with all built-in handlers, and the warning clearly tells them what to fix.

### Decision 2: Version registry location

**Context**: Need to map abstract method names to versions for error messages.
**Options**:

1. Constants in `project_loader.py` (module-level dict)
2. Separate `constants/handler_api_versions.py`

**Decision**: Module-level constant in `project_loader.py`. It's the only consumer. Extract later if needed (YAGNI).

## Success Criteria

- [ ] Daemon starts successfully even when project handlers have missing abstract methods
- [ ] Error message for missing `get_claude_md()` names the method and the version (v2.30.0)
- [ ] `validate-project-handlers` exits with code 1 when any handler fails to load
- [ ] Upgrade guide exists at `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/`
- [ ] RELEASING.md Step 6.5 has Handler ABC checklist
- [ ] All QA checks pass
- [ ] Daemon restart verified after each phase

## Notes & Updates

### 2026-04-02

- Plan created after confirming `controller.py:356` has no try/except around discover_handlers
- Confirmed `inspect.isabstract()` filter silently drops handlers missing get_claude_md()
- Confirmed v2.30.0 release did not create upgrade guide (Step 6.5 violated)
