# Code Lifecycle Documentation

**CRITICAL**: This directory defines the rigorous "Definition of Done" for all code changes.

> **Run every command below from the PROJECT ROOT.** Paths like
> `./bin/hooks-daemon` and `./scripts/qa/...` are relative to it, and resolve to
> nothing from anywhere else (`exit 127`).

## Purpose

These documents prevent shipping broken code by enforcing a complete testing pyramid:

- Unit tests (TDD, 95%+ coverage)
- Integration tests (component interactions)
- **Daemon load verification** (catches import errors)
- Acceptance tests (real-world behaviour)
- Live testing (actual Claude Code sessions)

## Documents

### By Change Type

- **@CLAUDE/CodeLifecycle/Features.md** - New features and handlers (most rigorous)
- **@CLAUDE/CodeLifecycle/Bugs.md** - Bug fixes (reproduce → fix → verify)
- **@CLAUDE/CodeLifecycle/General.md** - General code changes

### Supporting Documentation

- **@CLAUDE/AcceptanceTests/GENERATING.md** - Acceptance test generation
- **@CLAUDE/PlanWorkflow.md** - Planning workflow and templates

## The Critical Gap This Solves

**Real Example**: 5 handlers shipped with:

- ✅ Unit tests passing (100% coverage)
- ✅ QA checks passing (format, lint, types, security)
- ❌ **Daemon couldn't load them** (wrong import: `constants.decision` vs `core.Decision`)

**Root Cause**: No daemon restart verification between commits.

**Solution**: Every change MUST restart daemon successfully before commit.

## Quick Start

```bash
# MANDATORY for every change (no exceptions)
./bin/hooks-daemon restart
./bin/hooks-daemon status
# Expected: Status: RUNNING
```

If daemon fails to start, **your change is not done** - fix it before committing.

## Navigation

Start with the document for your change type:

| Change Type    | Read This                         |
| -------------- | --------------------------------- |
| New handler    | @CLAUDE/CodeLifecycle/Features.md |
| New feature    | @CLAUDE/CodeLifecycle/Features.md |
| Bug fix        | @CLAUDE/CodeLifecycle/Bugs.md     |
| Refactoring    | @CLAUDE/CodeLifecycle/General.md  |
| Documentation  | @CLAUDE/CodeLifecycle/General.md  |
| Config changes | @CLAUDE/CodeLifecycle/General.md  |

## Existing Testing Infrastructure

This project has comprehensive testing already:

- **Unit Tests**: `tests/unit/` (pytest, 95%+ coverage required)
- **Integration Tests**: `tests/integration/` (component interactions)
- **Acceptance Tests**: Generated from code (see `CLAUDE/AcceptanceTests/GENERATING.md`)
- **Dogfooding Tests**: `tests/integration/test_dogfooding*.py` (auto-verification)
- **QA Suite**: `./scripts/qa/llm_qa.py all` (LLM-optimised; `./scripts/qa/run_all.sh` is the same suite, verbose, for a human at a terminal — the runner is the single source of truth for which checks exist, do not hardcode a count)

Each lifecycle document (Features.md, Bugs.md, General.md) includes its own Definition of Done checklist.
