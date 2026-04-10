# Plan 00095: /optimise Skill for Config Analysis and Recommendations

**Status**: Complete (2026-03-30)
**Created**: 2026-03-30
**Owner**: Claude Code
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Add a `/optimise` skill to the hooks daemon that analyses a project's configuration and
usage patterns, scores it across five areas, and recommends specific improvements to make
best use of the daemon's capabilities.

The skill is a shell script that prints a comprehensive instruction set for Claude to
follow. Claude reads the config, profiles the project (languages, tests, CI, plans),
scores five areas (Safety, Stop Quality, Plan Workflow, Code Quality, Daemon Settings),
outputs a scored report with recommendations, and optionally applies them.

This follows the exact pattern established by the `/configure` skill — an `invoke.sh`
heredoc that tells Claude what to do step-by-step.

## Goals

- Detect under-utilised handlers and recommend enabling them
- Profile the project to give context-aware advice
- Score five areas with PASS/WARN/FAIL ratings
- Allow one-command application of all recommendations
- Follow the SSOT skill pattern (no duplication from canonical docs)

## Non-Goals

- Does not modify any Python source code in `src/`
- Does not add new handlers or Python features
- Does not replace `/configure` — it complements it

## Tasks

### Phase 1: Plan Document

- [x] **Task 1.1**: Create `CLAUDE/Plan/00095-config-optimise-skill/PLAN.md`

### Phase 2: Skill Files

- [x] **Task 2.1**: Create `.claude/skills/optimise/SKILL.md` following SSOT rule
- [x] **Task 2.2**: Create `.claude/skills/optimise/invoke.sh` with full instruction set

### Phase 3: Plan Index Update

- [x] **Task 3.1**: Update `CLAUDE/Plan/README.md` — add to Completed Plans, update stats

### Phase 4: Commit

- [x] **Task 4.1**: Commit all files with standard message

## Success Criteria

- [x] `invoke.sh` is executable and prints instructions when run
- [x] Instructions cover all 5 analysis areas with specific handler checks
- [x] Report format is clear, scannable, and actionable
- [x] Apply step gives Claude exact CLI commands to enable handlers
- [x] SKILL.md follows SSOT rule — references canonical docs, no duplication
- [x] Plan README updated correctly

## Notes & Updates

### 2026-03-30

- Implemented as shell script + instruction heredoc (no Python changes needed)
- Five analysis areas: Safety (7 handlers), Stop Quality (4), Plan Workflow (7),
  Code Quality (6), Daemon Settings (5) = 29 total check points
- Apply step uses `$PYTHON -m claude_code_hooks_daemon.daemon.cli` CLI commands
