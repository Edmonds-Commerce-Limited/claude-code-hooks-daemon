# Plan 00034: Library/Plugin Separation and QA Sub-Agent Integration

**Status**: Not Started
**Created**: 2026-02-09
**Owner**: TBD
**Priority**: High

## Overview

Fix architectural issue where `dogfooding_reminder` was created as a library handler instead of a plugin, and integrate library/plugin separation checking into the existing QA sub-agent workflow (defined in @CLAUDE/AgentTeam.md).

## Goals

- Move `dogfooding_reminder` from library to plugin system
- Add library/plugin separation check to QA Agent role
- Update `run_all.sh` to indicate sub-agent QA still needed
- Create `CLAUDE/QA.md` documenting complete QA pipeline (automated + sub-agents)

## Non-Goals

- Creating new QA scripts (use existing sub-agent system via Task tool)
- Changing agent team workflow (follow @CLAUDE/AgentTeam.md)
- Adding future speculative checks

## Context & Background

### The Problem

Created `dogfooding_reminder` as library handler:
```
src/claude_code_hooks_daemon/handlers/session_start/dogfooding_reminder.py
```

**This is wrong**:
- ❌ References project docs (@CLAUDE/CodeLifecycle/Bugs.md)
- ❌ Uses "dogfooding" language specific to this project
- ❌ Only useful when developing hooks daemon itself
- ❌ Pollutes library with project-specific concerns

**Should be plugin**:
```
.claude/hooks/handlers/session_start/dogfooding_reminder.py
```

### Existing QA Workflow (from @CLAUDE/AgentTeam.md)

**Automated QA** (`./scripts/qa/run_all.sh`):
1. Magic value check
2. Format check (black)
3. Linter (ruff)
4. Type check (mypy)
5. Tests (pytest, 95% coverage)
6. Security check (bandit)
7. Dependency check (deptry)

**Sub-Agent QA** (via Task tool, per @CLAUDE/AgentTeam.md):
- **QA Agent** (Gate 2): Runs automated QA + daemon restart verification
- **Senior Reviewer** (Gate 3): Checks architecture and completeness
- **Honesty Checker** (Gate 4): Detects theater and verifies real value

### What's Missing

QA agents don't currently check for library vs plugin separation. Need to add this check to QA Agent role.

## Tasks

### Phase 1: Move Dogfooding Handler to Plugin

- [ ] ⬜ **Task 1.1: Create plugin structure**
  - [ ] ⬜ Create `.claude/hooks/handlers/session_start/` directory
  - [ ] ⬜ Add `__init__.py` for plugin discovery

- [ ] ⬜ **Task 1.2: Move handler to plugin**
  - [ ] ⬜ Copy handler to `.claude/hooks/handlers/session_start/dogfooding_reminder.py`
  - [ ] ⬜ Test imports work as plugin
  - [ ] ⬜ Remove from `src/claude_code_hooks_daemon/handlers/session_start/`

- [ ] ⬜ **Task 1.3: Update tests**
  - [ ] ⬜ Keep tests in `tests/unit/handlers/session_start/test_dogfooding_reminder.py`
  - [ ] ⬜ Update imports to reference plugin location
  - [ ] ⬜ Run tests: `pytest tests/unit/handlers/session_start/test_dogfooding_reminder.py -v`

- [ ] ⬜ **Task 1.4: Remove from library constants**
  - [ ] ⬜ Remove `DOGFOODING_REMINDER` from `constants/handlers.py`
  - [ ] ⬜ Remove priority from `constants/priority.py`
  - [ ] ⬜ Remove from `handlers/session_start/__init__.py`

- [ ] ⬜ **Task 1.5: Remove from library config**
  - [ ] ⬜ Remove from `daemon/init_config.py`
  - [ ] ⬜ Remove from test expectations in `test_init_config.py`

- [ ] ⬜ **Task 1.6: Register as plugin**
  - [ ] ⬜ Update `.claude/hooks-daemon.yaml` plugins section:
    ```yaml
    plugins:
      paths: [".claude/hooks"]
      plugins:
        - event_type: session_start
          handler: dogfooding_reminder
          enabled: true
          priority: 35
    ```

- [ ] ⬜ **Task 1.7: Verify**
  - [ ] ⬜ Run QA: `./scripts/qa/run_all.sh`
  - [ ] ⬜ Restart daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ Check status: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`
  - [ ] ⬜ Verify plugin loads and handler works

### Phase 2: Create QA.md as Primary Source of Truth

- [ ] ⬜ **Task 2.1: Extract QA workflow from AgentTeam.md**
  - [ ] ⬜ Create `CLAUDE/QA.md`
  - [ ] ⬜ Move QA Agent role definition from AgentTeam.md to QA.md
  - [ ] ⬜ Move QA verification criteria to QA.md
  - [ ] ⬜ Document sub-agent QA workflow (spawning, reporting, criteria)

- [ ] ⬜ **Task 2.2: Add library/plugin separation check**
  - [ ] ⬜ Add to QA sub-agent checklist in QA.md:
    ```
    8. Library/Plugin Separation:
       - Scan src/claude_code_hooks_daemon/handlers/
       - Flag handlers that reference @CLAUDE/ paths
       - Flag "dogfooding" language
       - Flag project-specific functionality
       - Report violations found
    ```

- [ ] ⬜ **Task 2.3: Update AgentTeam.md to reference QA.md**
  - [ ] ⬜ Replace QA Agent definition with: "See CLAUDE/QA.md for QA Agent role"
  - [ ] ⬜ Keep agent team-specific notes (gates, verification flow)
  - [ ] ⬜ Note that QA.md is primary source of truth for QA workflow

### Phase 3: Update run_all.sh Output

- [ ] ⬜ **Task 3.1: Modify run_all.sh success message**
  - [ ] ⬜ After "Overall Status: ✅ ALL CHECKS PASSED", add:
    ```
    ⚠️  IMPORTANT: Automated QA is complete, but full QA requires sub-agent review.

    Run QA sub-agents for architecture and quality review.
    See CLAUDE/QA.md for complete workflow.
    ```

### Phase 4: Create CLAUDE/QA.md

- [ ] ⬜ **Task 4.1: Document complete QA pipeline**
  - [ ] ⬜ Create `CLAUDE/QA.md`
  - [ ] ⬜ Section 1: Automated QA (run_all.sh)
  - [ ] ⬜ Section 2: Sub-Agent QA (Task tool + AgentTeam.md roles)
  - [ ] ⬜ Section 3: When to run which checks
  - [ ] ⬜ Section 4: Library vs Plugin separation criteria

- [ ] ⬜ **Task 4.2: Document library vs plugin decision matrix**
  - [ ] ⬜ Library criteria (generic, reusable)
  - [ ] ⬜ Plugin criteria (project-specific, dogfooding)
  - [ ] ⬜ Examples of each type
  - [ ] ⬜ How QA Agent checks this

- [ ] ⬜ **Task 4.3: Cross-reference AgentTeam.md**
  - [ ] ⬜ Link to QA Agent role
  - [ ] ⬜ Link to verification gates
  - [ ] ⬜ Reference prompt templates

## Technical Decisions

### Decision 1: Use Existing Sub-Agent System, Not New Scripts
**Context**: Need library/plugin checking in QA.

**Decision**: Add to existing QA Agent role via Task tool, not create new .sh scripts.

**Rationale**:
- @CLAUDE/AgentTeam.md already defines QA Agent role
- Sub-agents spawned via Task tool (not shell scripts)
- Consistent with existing workflow
- LLM-based semantic analysis (better than regex)

**Date**: 2026-02-09

### Decision 2: Keep Tests in tests/unit/ Even for Plugins
**Context**: Where should plugin tests live?

**Decision**: Keep in `tests/unit/handlers/` with library tests.

**Rationale**:
- Tests run same way regardless of handler location
- Keeps test structure consistent
- pytest discovers them automatically
- Coverage reporting works same way

**Date**: 2026-02-09

## Library vs Plugin Criteria

### Library Handlers (src/claude_code_hooks_daemon/handlers/)

✅ Generic safety enforcement
✅ Generic QA enforcement
✅ Generic workflow patterns
✅ Tool usage guidance
✅ Reusable by any project
✅ No project-specific references

**Examples**: `destructive_git`, `tdd_enforcement`, `sed_blocker`, `eslint_disable`

### Project Plugins (.claude/hooks/handlers/)

⚠️ Project-specific functionality
⚠️ Dogfooding language/concepts
⚠️ References @CLAUDE/ documentation
⚠️ Specific to developing this project
⚠️ Not reusable by other projects

**Examples**: `dogfooding_reminder`

## Success Criteria

- [ ] `dogfooding_reminder` moved to plugin system and works
- [ ] Library has no project-specific handlers
- [ ] QA Agent template includes library/plugin check
- [ ] `run_all.sh` indicates sub-agent QA needed
- [ ] `CLAUDE/QA.md` documents complete pipeline
- [ ] All automated QA passes
- [ ] Daemon restarts successfully with plugin loaded

## Notes & Updates

### 2026-02-09
- Plan created after dogfooding_reminder library pollution
- Using existing sub-agent system from AgentTeam.md
- No new scripts - leverage Task tool for sub-agents
