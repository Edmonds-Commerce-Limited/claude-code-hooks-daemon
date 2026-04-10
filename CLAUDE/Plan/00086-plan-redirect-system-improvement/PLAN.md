# Plan 86: Fix Plan Redirect System Using plansDirectory

**Status**: Not Started
**Created**: 2026-03-11
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Sonnet

## Overview

The plan redirect system writes a stub to `~/.claude/plans/random-words.md`, so ExitPlanMode shows the stub (not the plan) to the user during approval. This breaks the review flow.

**Key finding**: Claude Code has a native `plansDirectory` setting that controls where plans are stored. By setting it to `"./CLAUDE/Plan"`, Claude Code writes plans directly to the project folder. Combined with handler changes, this eliminates the redirect problem entirely.

## Goals

- User sees full plan content during ExitPlanMode approval
- Plans are written directly to project version control (no redirect)
- Handler creates numbered folder structure alongside the flat plan file
- Config sync between `plansDirectory` and hooks daemon `track_plans_in_project`
- Clean up flat plan files after approval

## Non-Goals

- Changing Claude Code internals
- Removing the plan numbering system

---

## Phase 0: Local Testing (Pre-Implementation)

**Goal**: Verify `plansDirectory` works as expected before writing code.

- [ ] **Task 0.1**: Add `"plansDirectory": "./CLAUDE/Plan"` to `.claude/settings.json`
- [ ] **Task 0.2**: Restart session (settings.json read at startup)
- [ ] **Task 0.3**: Enter plan mode and verify:
  - Claude Code assigns path under `./CLAUDE/Plan/` (not `~/.claude/plans/`)
  - Write tool call targets `./CLAUDE/Plan/random-words.md`
  - ExitPlanMode shows full plan content
- [ ] **Task 0.4**: Document findings and edge cases
- [ ] **Task 0.5**: Test Edit tool on plan file (incremental edits)

**Questions to answer**:

- Does the path include `./` prefix or is it bare `CLAUDE/Plan/`?
- Does it create the directory if it doesn't exist?
- What happens if the handler DENYs the write - does ExitPlanMode still show content?
- Can the agent Edit the plan file after initial Write?

---

## Phase 1: Update Handler for New Flow (TDD)

**Goal**: Handler creates numbered folder alongside flat file, returns ALLOW.

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`

### New Flow

```
1. plansDirectory = "./CLAUDE/Plan" (in .claude/settings.json)
2. Claude writes to ./CLAUDE/Plan/random-words.md
3. Handler intercepts:
   a. Creates CLAUDE/Plan/NNNNN-random-words/PLAN.md (numbered folder + content)
   b. Returns ALLOW (lets Claude Code write the flat file too)
   c. Adds context: "Plan also saved to CLAUDE/Plan/NNNNN-random-words/PLAN.md"
4. ExitPlanMode reads ./CLAUDE/Plan/random-words.md → shows FULL content ✓
5. After approval: agent renames numbered folder, deletes flat file
```

### Tasks

- [ ] **Task 1.1**: Update `is_planning_mode_write()` to detect writes to configured plansDirectory

  - Currently checks `/.claude/plans/` - need to also check project-relative plan dir
  - Read `plansDirectory` from `.claude/settings.json` or use daemon config path

- [ ] **Task 1.2**: Change `handle_planning_mode_write()` to return ALLOW instead of DENY

  - Still create numbered folder with PLAN.md
  - Return ALLOW so Claude Code writes the flat file (ExitPlanMode can read it)
  - Add context message about the numbered folder location

- [ ] **Task 1.3**: Handle Edit tool for plan files

  - When agent edits flat file, also apply edit to numbered folder PLAN.md
  - Return ALLOW (Claude Code applies edit to flat file)
  - Both copies stay in sync

- [ ] **Task 1.4**: Remove rename instructions from handler response

  - Rename happens after approval, not during write

- [ ] **Task 1.5**: Tests for all new behaviour

---

## Phase 2: Config Sync Enforcement

**Goal**: Ensure `plansDirectory` in `.claude/settings.json` matches `track_plans_in_project` in hooks daemon config.

### Options

**Option A**: SessionStart handler checks sync, warns if mismatch
**Option B**: Installer/init sets both configs together
**Option C**: Handler reads plansDirectory at runtime from settings.json

- [ ] **Task 2.1**: Add check in handler init or SessionStart

  - Read `.claude/settings.json` for `plansDirectory`
  - Compare with `track_plans_in_project` from daemon config
  - Warn if mismatch

- [ ] **Task 2.2**: Update installer to set plansDirectory when enabling plan tracking

---

## Phase 3: Cleanup and Documentation

- [ ] **Task 3.1**: Update PlanWorkflow.md

  - Document: rename folder after approval, delete flat file
  - Document: plansDirectory config requirement

- [ ] **Task 3.2**: Update CLAUDE.md plan mode section

- [ ] **Task 3.3**: Add plansDirectory to `.claude/settings.json` (permanent config)

---

## Phase 4: QA & Verification

- [ ] **Task 4.1**: Run full QA suite
- [ ] **Task 4.2**: Daemon restart verification
- [ ] **Task 4.3**: Manual E2E test: enter plan mode → write plan → verify approval shows content

## Key Files

| File                                            | Changes                                          |
| ----------------------------------------------- | ------------------------------------------------ |
| `.claude/settings.json`                         | Add `plansDirectory: "./CLAUDE/Plan"`            |
| `src/.../pre_tool_use/markdown_organization.py` | Update detection + change DENY→ALLOW + Edit sync |
| `tests/.../test_markdown_organization.py`       | Update tests for new flow                        |
| `CLAUDE/PlanWorkflow.md`                        | Document new flow                                |

## Success Criteria

- [ ] `plansDirectory` set in `.claude/settings.json`
- [ ] ExitPlanMode shows full plan content to user
- [ ] Numbered folder created alongside flat file
- [ ] Edit tool keeps both copies in sync
- [ ] Config sync check warns on mismatch
- [ ] All existing tests pass, 95%+ coverage
- [ ] Daemon restarts successfully

## Supporting Documents

- `CONTEXT-DUMP.md` - Full analysis, research, and session context
