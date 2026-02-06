# Plan 00030: Agent Team Workflow Documentation

**Status**: Not Started
**Created**: 2026-02-06
**Owner**: To be assigned
**Priority**: High
**Type**: Documentation

## Overview

Create `CLAUDE/AgentTeam.md` with project-specific guidance for running agent teams with worktrees. This captures lessons learned from the Wave 1 POC execution (Plans 00016-00027) and provides a definitive reference for future agent team work.

## Goals

- Document the complete agent team workflow for this project
- Hard-link to CLAUDE/Worktree.md for worktree mechanics
- Capture lessons learned from Wave 1 POC
- Provide copy-paste agent prompts that are self-sufficient
- Document daemon isolation requirements (link to Plan 00028)
- Define team lead vs agent responsibilities clearly

## Non-Goals

- Replacing Worktree.md (AgentTeam.md extends it with team-specific guidance)
- Generic Claude Code team docs (project-specific)

## Tasks

### Phase 1: Gather Lessons Learned

- [ ] **Task 1.1**: Document daemon isolation issues encountered
  - Cross-kill between worktree daemons
  - Daemon restart command confusion
  - Solution: explicit --pid-file/--socket flags (Plan 00028)

- [ ] **Task 1.2**: Document agent autonomy issues
  - Agents hitting turn limits before committing
  - Team lead micromanagement (checking every idle)
  - Solution: complete self-sufficient prompts with QA+commit

- [ ] **Task 1.3**: Document markdown handler blocking memory writes
  - Memory writes blocked by markdown_organization handler
  - Solution: fix handler scope (Plan 00029)

### Phase 2: Write Documentation

- [ ] **Task 2.1**: Create `CLAUDE/AgentTeam.md` with sections:
  - Overview and when to use agent teams
  - Prerequisites (python3-venv, worktree docs)
  - Team setup checklist
  - Agent prompt template (self-sufficient, includes QA+commit)
  - Daemon isolation (link to Worktree.md and Plan 00028)
  - Team lead responsibilities (setup, merge, don't micromanage)
  - Agent responsibilities (stay in worktree, own venv, QA, commit)
  - Merge protocol (QA pass required, user approval for main)
  - Troubleshooting common issues
  - Lessons learned from Wave 1 POC

- [ ] **Task 2.2**: Update CLAUDE/Worktree.md to cross-reference AgentTeam.md

### Phase 3: QA

- [ ] **Task 3.1**: Review documentation for completeness
- [ ] **Task 3.2**: Verify all cross-references work
- [ ] **Task 3.3**: `./scripts/qa/run_all.sh`

## Success Criteria

- [ ] CLAUDE/AgentTeam.md exists with comprehensive guidance
- [ ] Hard links to Worktree.md throughout
- [ ] All POC lessons captured
- [ ] Agent prompt template is copy-paste ready
- [ ] QA passes
