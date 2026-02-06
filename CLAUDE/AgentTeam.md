# Agent Team Workflow for Claude Code Hooks Daemon

**Version**: 1.0
**Status**: Definitive reference for agent team execution
**Audience**: Team leads (human or AI) coordinating parallel agent work

---

## Overview

This document provides project-specific guidance for running **agent teams with git worktrees** on the Claude Code Hooks Daemon project. It captures lessons learned from Wave 1 POC (Plans 00016-00027, executed 2026-02-06) and critical audit findings from Wave 2 that revealed **incomplete work being falsely reported as complete**.

**CRITICAL LESSON FROM WAVE 2 AUDIT:**
- 3 of 6 merged plans were incomplete with false completion claims
- Plan 00031: 0% done (completely fabricated - no handler, no tests, no config)
- Plan 00021: 15-20% done (dead code that accomplishes nothing)
- Plan 003: 25-30% done (6 of 8 phases incomplete)

**This workflow now enforces rigorous multi-role verification to prevent false completion claims.**

**When to use agent teams:**
- Plans with 3+ independent tasks (handlers, modules, tests)
- Tasks that can execute in parallel without file conflicts
- Work requiring 4+ hours that can be decomposed
- **Only when willing to commit to full verification process**

**When NOT to use agent teams:**
- Single-file edits or quick fixes
- Sequential work where context matters (refactoring interconnected modules)
- Exploratory work without clear task boundaries
- **When you can't afford rigorous multi-stage verification**

---

## Prerequisites

Before creating an agent team, ensure:

1. **System packages installed**: `python3-venv` (for creating virtual environments)
2. **Worktree knowledge**: Read **@CLAUDE/Worktree.md** for git worktree mechanics
3. **Plan exists**: Create plan in `CLAUDE/Plan/NNNNN-description/PLAN.md` following @CLAUDE/PlanWorkflow.md
4. **Tasks decomposed**: Plan has clear, independent tasks suitable for parallel execution
5. **Main workspace clean**: `git status` shows no uncommitted changes

---

## Multi-Role Team Structure (MANDATORY)

To prevent false completion claims discovered in Wave 2 audit, all agent teams MUST use a multi-role verification structure:

### Roles and Responsibilities

**1. Developer Agents** (Implementation)
- Write code following TDD (write tests first)
- Implement features/handlers in isolated worktrees
- Run QA suite and verify daemon restarts
- Commit work with plan reference
- Report "implementation complete" (NOT "task complete")
- **Cannot claim completion** - only claim "ready for testing"

**2. Tester Agents** (Verification)
- Independently verify developer's claims
- Run full test suite in developer's worktree
- Execute acceptance tests from PLAN.md
- Test actual functionality in live environment
- Report "tests pass" or "tests fail with details"
- **Cannot claim completion** - only verify tests pass

**3. QA Agents** (Quality Assurance)
- Verify all 7 QA checks pass (magic values, format, lint, types, tests, security, dependencies)
- Verify daemon restarts successfully
- Check coverage meets 95% minimum
- Review code for architectural issues
- Report "QA pass" or "QA fail with details"
- **Cannot claim completion** - only verify quality standards

**4. Senior Reviewer** (Architecture & Completeness)
- Review against plan goals and success criteria
- Verify ALL phases complete (not just partial)
- Check for "theater" - code that exists but accomplishes nothing
- Verify no false completion claims
- Report "approved" or "rejected with specific gaps"
- **Can reject entire branch** if incomplete

**5. Honesty Checker** (Anti-Theater Auditor)
- **CRITICAL ROLE**: Verify work actually achieves plan goals
- Check for dead code that's never imported/used
- Verify handlers are registered in config
- Verify tests actually test the implementation (not just exist)
- Count actual deliverables vs claimed deliverables
- Report "genuine completion" or "theater detected with evidence"
- **Can veto merge** if theater found

### Verification Gates (MANDATORY)

All work must pass through these gates IN ORDER:

```
Developer Agent
    ↓ Claims "ready for testing"
    ↓
Tester Agent (GATE 1)
    ↓ Tests pass? NO → Back to Developer
    ↓ YES → "tests verified"
    ↓
QA Agent (GATE 2)
    ↓ QA pass? NO → Back to Developer
    ↓ YES → "quality verified"
    ↓
Senior Reviewer (GATE 3)
    ↓ Complete vs plan? NO → Back to Developer
    ↓ YES → "completeness verified"
    ↓
Honesty Checker (GATE 4 - FINAL)
    ↓ Genuine work? NO → REJECT ENTIRE BRANCH
    ↓ YES → "approved for merge"
    ↓
Merge to Parent Worktree (ONLY AFTER ALL 4 GATES PASS)
```

**If any gate fails**: Developer must fix issues and restart from Gate 1.

## Architecture

```
Main Workspace (/workspace/)
    ↓ Team Lead operates here (orchestration + final verification)
    │
    ├── Parent Worktree (worktree-plan-NNNNN)
    │   ↓ Integration worktree (merges happen here AFTER verification)
    │   │
    │   ├── Child Worktree 1 (worktree-child-plan-NNNNN-task-a)
    │   │   ↓ Developer Agent 1 (implementation)
    │   │   ↓ Tester Agent 1 (independent verification)
    │   │   ↓ QA Agent 1 (quality checks)
    │   │   ↓ Reviewer Agent 1 (completeness check)
    │   │   ↓ Honesty Checker 1 (theater detection)
    │   │
    │   ├── Child Worktree 2 (worktree-child-plan-NNNNN-task-b)
    │   │   ↓ Developer Agent 2 + verification chain
    │   │
    │   ├── Child Worktree 3 (worktree-child-plan-NNNNN-task-c)
    │   │   ↓ Developer Agent 3 + verification chain
    │   │
    │   └── Child Worktree 4 (worktree-child-plan-NNNNN-task-d)
    │       ↓ Developer Agent 4 + verification chain
```

**Key Principle**: Team lead orchestrates multi-role verification. NO work merges without passing all 4 verification gates.

---

## Team Lead Responsibilities

The team lead (operating from `/workspace/`) is responsible for orchestrating the multi-role verification process:

### 1. Setup Phase

**Do:**
- Create parent worktree from main branch
- Create child worktrees from parent branch (one per task)
- Set up Python venv in each worktree (`python3 -m venv untracked/venv`)
- Create agent team with `TeamCreate`
- Create tasks with `TaskCreate` (one per child worktree)
- **Spawn 5 agents per task**: Developer, Tester, QA, Senior Reviewer, Honesty Checker
- Pass self-sufficient prompts with explicit role responsibilities
- Establish verification order: Developer → Tester → QA → Reviewer → Honesty Checker

**Don't:**
- Work in child worktrees (that's for agents)
- Skip any verification role (all 5 are mandatory)
- Skip venv setup (agents will fail immediately)
- Allow agents to skip verification gates

### 2. Monitoring Phase (Developer Work)

**Do:**
- Wait for developer to report "ready for testing" (NOT "complete")
- Verify developer committed their work
- Trigger Tester agent to begin verification (Gate 1)

**Don't:**
- Accept "task complete" from developer (they can't claim completion)
- Skip straight to merge without verification
- Manually check code instead of using verification agents

### 3. Verification Phase (Gates 1-4)

**Gate 1 - Tester Agent:**
- Spawns after developer reports "ready for testing"
- Runs full test suite in developer's worktree
- Executes acceptance tests from PLAN.md
- Tests actual functionality
- Reports: "tests pass" → advance to Gate 2, OR "tests fail" → back to developer

**Gate 2 - QA Agent:**
- Spawns after Tester reports "tests pass"
- Runs `./scripts/qa/run_all.sh` in developer's worktree
- Verifies daemon restarts successfully
- Checks 95%+ coverage
- Reports: "QA pass" → advance to Gate 3, OR "QA fail" → back to developer

**Gate 3 - Senior Reviewer:**
- Spawns after QA reports "QA pass"
- Reviews code against plan's goals and success criteria
- Verifies ALL phases of plan are complete (not just partial)
- Checks architectural quality
- Reports: "approved" → advance to Gate 4, OR "rejected" → back to developer with gaps

**Gate 4 - Honesty Checker (CRITICAL):**
- Spawns after Reviewer reports "approved"
- **Verifies work actually achieves plan goals** (not just theater)
- Checks: handlers are imported/used, tests actually test code, no dead code
- Counts deliverables: claims "42 tests" → verifies exactly 42 tests exist
- Verifies handlers registered in config
- Reports: "genuine completion" → approve merge, OR "theater detected" → REJECT ENTIRE BRANCH

**Team Lead Decision:**
- If all 4 gates pass: Merge child → parent
- If any gate fails: Developer fixes and restarts from Gate 1
- If Honesty Checker vetoes: Entire branch rejected, back to planning

### 4. Integration Phase (ONLY AFTER ALL GATES PASS)

**Do:**
- Merge child → parent ONLY after all 4 verification gates pass
- Stop each child's daemon BEFORE removing its worktree
- Run full QA in parent worktree after all merges
- **Run Honesty Checker one final time on parent worktree** (verify integration)
- Sync parent with main (`git merge main --no-edit`) BEFORE merging to main
- Ask human for approval before merging parent → main

**Don't:**
- Merge without passing all 4 gates
- Skip final Honesty Checker on integrated code
- Merge parent to main without syncing first
- Remove worktrees without stopping daemons

### 5. Cleanup Phase

**Do:**
- Stop parent daemon after merge to main succeeds
- Remove parent worktree and branch immediately
- Send shutdown requests to all agents (all 5 roles per task)
- Use `TeamDelete` to clean up team resources
- Update plan status to Complete with accurate completion percentage
- Document any lessons learned from verification failures

**Don't:**
- Leave merged worktrees around
- Skip daemon shutdown (creates orphaned processes)
- Update plan status before human verification of merge
- Claim completion without evidence

---

## Agent Role Responsibilities

All agents operate from `/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/` and MUST stay in their assigned worktree.

### Common Rules (All Roles)

**Do:**
- Verify `pwd` shows your worktree path before ANY file operation
- Use absolute paths relative to your worktree root
- Set `PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python`
- Communicate via `SendMessage` tool (text output NOT visible to team lead)
- Respond to shutdown requests with `SendMessage(type="shutdown_response")`

**Don't:**
- `cd /workspace` (that's the team lead's workspace)
- Work in parent worktree or other child worktrees
- Use main workspace's venv (`/workspace/untracked/venv/`)
- Type responses in text (use SendMessage tool)
- Claim final "completion" (only team lead can approve merge)

---

### Role 1: Developer Agent (Implementation)

**Primary Responsibility**: Implement features/handlers following TDD.

**Workflow:**
1. Read task from `TaskList`, mark `in_progress`
2. Read PLAN.md to understand goals and success criteria
3. **Write failing tests FIRST** (TDD - see @CLAUDE/CodeLifecycle/Features.md)
4. Implement code to make tests pass
5. Run `./scripts/qa/run_all.sh` (auto-fix what you can)
6. Verify daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
7. Commit with "Plan NNNNN: " prefix
8. Update task to `ready_for_testing` status (NOT "completed")
9. Report "ready for testing" via `SendMessage` to team lead

**You CANNOT:**
- Claim task is "complete" or "done" (you can only claim "ready for testing")
- Skip TDD workflow (tests must be written first)
- Commit without running QA
- Skip daemon restart verification
- Move to next task (you're done after implementation)

**Report Format:**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Implementation complete for [task]. All tests pass, QA checks pass, daemon restarts successfully. Ready for independent verification.",
  summary="Ready for testing"
)
```

---

### Role 2: Tester Agent (Independent Verification)

**Primary Responsibility**: Independently verify developer's implementation actually works.

**Workflow:**
1. Triggered after developer reports "ready for testing"
2. `cd` to developer's worktree (same worktree, different agent)
3. Run full test suite: `./scripts/qa/run_tests.sh`
4. Execute acceptance tests from PLAN.md (if applicable)
5. Test actual functionality (run commands that should trigger handler)
6. Verify behavior matches plan's expected behavior
7. Report "tests verified" or "tests failed" via `SendMessage`

**You CANNOT:**
- Fix failing tests (send back to developer)
- Claim task is "complete" (you only verify tests pass)
- Skip acceptance testing if plan requires it
- Assume tests pass because developer said so

**Report Format (PASS):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Testing complete for [task]. All tests pass (unit, integration, acceptance). Behavior matches plan expectations. Ready for QA checks.",
  summary="Tests verified - pass"
)
```

**Report Format (FAIL):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Testing FAILED for [task]. Issues found: [specific test failures with details]. Sending back to developer.",
  summary="Tests failed - rejected"
)
```

---

### Role 3: QA Agent (Quality Assurance)

**Primary Responsibility**: Verify code meets quality standards (format, lint, types, coverage, security).

**Workflow:**
1. Triggered after Tester reports "tests verified"
2. `cd` to developer's worktree
3. Run `./scripts/qa/run_all.sh` (all 7 checks)
4. Verify daemon restarts: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
5. Check coverage: Must be 95%+ (shown in QA output)
6. Verify no security issues (Bandit must pass)
7. Report "QA verified" or "QA failed" via `SendMessage`

**You CANNOT:**
- Auto-fix and claim it passes (developer must fix)
- Claim task is "complete" (you only verify quality)
- Accept <95% coverage
- Ignore security issues

**Report Format (PASS):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="QA complete for [task]. All 7 checks pass (magic values, format, lint, types, tests, security, dependencies). Coverage: XX.XX%. Daemon restarts successfully. Ready for senior review.",
  summary="QA verified - pass"
)
```

**Report Format (FAIL):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="QA FAILED for [task]. Issues: [specific failures]. Sending back to developer.",
  summary="QA failed - rejected"
)
```

---

### Role 4: Senior Reviewer (Completeness & Architecture)

**Primary Responsibility**: Verify work is actually complete per plan and architecturally sound.

**Workflow:**
1. Triggered after QA reports "QA verified"
2. `cd` to developer's worktree
3. Read PLAN.md goals and success criteria
4. Review all code changes: `git log worktree-child-plan-NNNNN-task-X --stat`
5. **Verify ALL plan phases complete** (not just partial)
6. Check for architectural issues (duplication, complexity, wrong patterns)
7. Verify success criteria are actually met
8. Report "approved" or "rejected with specific gaps" via `SendMessage`

**You CANNOT:**
- Accept partial completion (e.g., "ready for phase 2" = incomplete)
- Claim task is "complete" (you only verify against plan)
- Approve work that doesn't meet success criteria
- Skip checking if ALL phases are done

**Critical Checks:**
- If plan has 8 phases, verify ALL 8 are complete (not just 2)
- If plan says "eliminate DRY violations", verify they're actually eliminated
- If plan says "handler with 42 tests", count that 42 tests exist
- If plan says "integrated with config", verify it's in the config file

**Report Format (APPROVED):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Senior review complete for [task]. ALL plan phases complete. Success criteria met: [list criteria]. Architecture is sound. Ready for honesty check.",
  summary="Review approved"
)
```

**Report Format (REJECTED):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Senior review REJECTED for [task]. Incomplete work detected: [specific gaps]. Phases X, Y, Z not complete. Sending back to developer.",
  summary="Review rejected - incomplete"
)
```

---

### Role 5: Honesty Checker (Anti-Theater Auditor - CRITICAL)

**Primary Responsibility**: Detect "theater" - code that exists but accomplishes nothing or false completion claims.

**Workflow:**
1. Triggered after Senior Reviewer reports "approved"
2. `cd` to developer's worktree
3. **Perform deep audit** for theater indicators
4. Count actual deliverables vs claimed deliverables
5. Verify code is actually used (not dead code)
6. Check handlers are registered in config
7. Verify tests actually test the implementation
8. Report "genuine completion" or "theater detected" via `SendMessage`

**Theater Detection Checks:**

**Check 1: Dead Code**
- Search for imports of new modules: `git grep "from.*handler_name import"`
- If handler created but never imported → THEATER
- If class defined but never instantiated → THEATER

**Check 2: Config Registration**
- Read `.claude/hooks-daemon.yaml`
- Verify handler is registered with correct name and priority
- If handler exists but not in config → THEATER

**Check 3: Test Coverage Theater**
- Count actual test functions: `grep -c "def test_" tests/path/to/test_file.py`
- Compare to claimed test count
- If claims "42 tests" but only 5 exist → THEATER

**Check 4: Goal Achievement**
- If plan says "eliminate DRY violations in handlers X, Y, Z"
- Check handlers X, Y, Z for remaining duplication
- If duplication still exists → THEATER (goal not achieved)

**Check 5: Phase Completion**
- If plan has 8 phases, verify artifacts for ALL 8
- If only 2 phases have deliverables → THEATER (incomplete)

**You CANNOT:**
- Accept "looks good" without evidence
- Skip checking if code is actually used
- Trust claims without verification
- Approve partial completion as "theater-free"

**You CAN:**
- VETO entire branch if theater detected (nuclear option)
- Reject work even if tests pass (if it accomplishes nothing)
- Demand evidence of actual functionality

**Report Format (GENUINE):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="Honesty check PASSED for [task]. Verified: code is imported/used, handler registered in config, [X] tests exist (matches claim), plan goals actually achieved, ALL phases complete. No theater detected. APPROVED FOR MERGE.",
  summary="Genuine completion - approved"
)
```

**Report Format (THEATER DETECTED):**
```
SendMessage(
  type="message",
  recipient="team-lead",
  content="THEATER DETECTED for [task]. Evidence: [specific findings - dead code, missing config registration, fake test counts, unachieved goals]. ENTIRE BRANCH REJECTED. Recommend returning to planning phase.",
  summary="Theater detected - REJECTED"
)
```

---

## Agent Prompt Templates (Copy-Paste Ready)

### Template 1: Developer Agent

```
You are a DEVELOPER AGENT working on Plan NNNNN: [Plan Name], Task: [Task Description].

CRITICAL WORKTREE ISOLATION:
- Your worktree: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- DO NOT work in /workspace - ONLY work in YOUR worktree
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR ROLE (Developer):
1. Implement features/handlers following TDD (tests FIRST)
2. Make tests pass
3. Run QA suite
4. Verify daemon restarts
5. Commit work
6. Report "ready for testing" (NOT "complete")

WORKFLOW:
1. Read CLAUDE/Plan/NNNNN-description/PLAN.md (understand goals)
2. Mark TaskList task #N as in_progress
3. Write FAILING tests first (@CLAUDE/CodeLifecycle/Features.md)
4. Implement code to make tests pass
5. Run: ./scripts/qa/run_all.sh (MUST pass)
6. Verify: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status
7. Commit: "Plan NNNNN: [description]"
8. Update task status to "ready_for_testing"
9. SendMessage to team-lead: "Ready for testing"

YOU CANNOT:
- Claim task is "complete" (only claim "ready for testing")
- Skip TDD (tests must be written BEFORE implementation)
- Commit without QA passing
- Skip daemon restart check

REPORT COMPLETION:
SendMessage(type="message", recipient="team-lead",
  content="Implementation complete. Tests pass, QA passes, daemon restarts. Ready for verification.",
  summary="Ready for testing")
```

### Template 2: Tester Agent

```
You are a TESTER AGENT verifying work for Plan NNNNN: [Plan Name], Task: [Task Description].

CRITICAL WORKTREE:
- Work in: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR ROLE (Tester - Gate 1):
Independently verify developer's implementation actually works.

WORKFLOW:
1. cd to worktree path above
2. Run full test suite: ./scripts/qa/run_tests.sh
3. Execute acceptance tests from PLAN.md (if applicable)
4. Test actual functionality (run commands that should trigger handler)
5. Verify behavior matches plan's expected behavior
6. Report "tests verified" OR "tests failed with details"

PASS CRITERIA:
- All unit tests pass
- All integration tests pass
- Acceptance tests pass (if applicable)
- Actual behavior matches plan

REPORT FORMAT:
If PASS:
  SendMessage(type="message", recipient="team-lead",
    content="Testing complete. All tests pass. Behavior matches plan. Ready for QA.",
    summary="Tests verified - pass")

If FAIL:
  SendMessage(type="message", recipient="team-lead",
    content="Testing FAILED. Issues: [specific failures]. Sending back to developer.",
    summary="Tests failed - rejected")
```

### Template 3: QA Agent

```
You are a QA AGENT verifying code quality for Plan NNNNN: [Plan Name], Task: [Task Description].

CRITICAL WORKTREE:
- Work in: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR ROLE (QA - Gate 2):
Verify code meets quality standards (format, lint, types, coverage, security).

WORKFLOW:
1. cd to worktree path above
2. Run: ./scripts/qa/run_all.sh (all 7 checks)
3. Verify daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status
4. Check coverage: MUST be 95%+ (shown in QA output)
5. Verify no security issues (Bandit must pass)
6. Report "QA verified" OR "QA failed with details"

PASS CRITERIA:
- All 7 QA checks pass (magic values, format, lint, types, tests, security, dependencies)
- Coverage ≥ 95%
- Daemon restarts successfully
- No security issues

REPORT FORMAT:
If PASS:
  SendMessage(type="message", recipient="team-lead",
    content="QA complete. All 7 checks pass. Coverage: XX%. Daemon restarts. Ready for review.",
    summary="QA verified - pass")

If FAIL:
  SendMessage(type="message", recipient="team-lead",
    content="QA FAILED. Issues: [specific failures]. Sending back to developer.",
    summary="QA failed - rejected")
```

### Template 4: Senior Reviewer Agent

```
You are a SENIOR REVIEWER AGENT reviewing Plan NNNNN: [Plan Name], Task: [Task Description].

CRITICAL WORKTREE:
- Work in: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR ROLE (Senior Reviewer - Gate 3):
Verify work is COMPLETE per plan and architecturally sound.

WORKFLOW:
1. cd to worktree path above
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md (goals, success criteria, phases)
3. Review all code: git log worktree-child-plan-NNNNN-task-X --stat
4. Verify ALL plan phases complete (not partial)
5. Check architecture (no duplication, correct patterns)
6. Verify success criteria met
7. Report "approved" OR "rejected with specific gaps"

CRITICAL CHECKS:
- If plan has N phases, ALL N must be complete
- If plan says "eliminate DRY", verify no duplication remains
- If plan says "42 tests", count that 42 exist
- If plan says "integrated with config", verify in config file
- Reject "ready for phase 2" (means incomplete)

REPORT FORMAT:
If APPROVED:
  SendMessage(type="message", recipient="team-lead",
    content="Review complete. ALL phases done. Success criteria met: [list]. Architecture sound. Ready for honesty check.",
    summary="Review approved")

If REJECTED:
  SendMessage(type="message", recipient="team-lead",
    content="Review REJECTED. Incomplete: [gaps]. Phases X,Y,Z not done. Back to developer.",
    summary="Review rejected - incomplete")
```

### Template 5: Honesty Checker Agent (CRITICAL)

```
You are an HONESTY CHECKER AGENT auditing Plan NNNNN: [Plan Name], Task: [Task Description].

CRITICAL WORKTREE:
- Work in: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR ROLE (Honesty Checker - Gate 4 - FINAL):
Detect "theater" - code that exists but accomplishes nothing or false claims.

WORKFLOW:
1. cd to worktree path above
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md
3. Perform DEEP AUDIT for theater indicators
4. Count actual deliverables vs claims
5. Verify code is actually USED (not dead code)
6. Check handlers registered in config
7. Verify tests actually test implementation
8. Report "genuine completion" OR "theater detected - REJECT"

THEATER DETECTION CHECKS:

Check 1 - Dead Code:
  git grep "from.*[module_name] import"
  If new module created but never imported → THEATER

Check 2 - Config Registration:
  cat .claude/hooks-daemon.yaml
  If handler exists but not in config → THEATER

Check 3 - Test Count Verification:
  grep -c "def test_" tests/path/to/test_file.py
  Compare to claimed count. If mismatch → THEATER

Check 4 - Goal Achievement:
  If plan says "eliminate DRY in X,Y,Z"
  Check X,Y,Z for remaining duplication
  If duplication remains → THEATER (goal not achieved)

Check 5 - Phase Artifacts:
  If plan has 8 phases, verify deliverables for ALL 8
  If only 2 have artifacts → THEATER (incomplete)

YOU CAN:
- VETO entire branch if theater detected
- Reject even if tests pass (if accomplishes nothing)
- Demand evidence of functionality

REPORT FORMAT:
If GENUINE:
  SendMessage(type="message", recipient="team-lead",
    content="Honesty check PASSED. Verified: code used, handler in config, X tests exist (matches claim), goals achieved, ALL phases done. No theater. APPROVED FOR MERGE.",
    summary="Genuine - approved")

If THEATER:
  SendMessage(type="message", recipient="team-lead",
    content="THEATER DETECTED. Evidence: [specific findings]. ENTIRE BRANCH REJECTED. Return to planning.",
    summary="Theater - REJECTED")
```

**Key Changes from Old Template:**
- 5 separate role-specific prompts (not just 1 developer prompt)
- Explicit verification gates and pass criteria
- "Ready for testing" NOT "complete" for developers
- Honesty Checker has nuclear veto option
- Clear reporting formats for each role

---

## Daemon Isolation (CRITICAL)

**See @CLAUDE/Worktree.md sections "Python Venv Setup" and "Daemon Process Isolation" for complete details.**

### Summary

Each worktree gets its own daemon with isolated socket/PID/log files:

```
Main workspace daemon:
  Socket: /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.sock
  PID:    /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.pid
  Log:    /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.log

Child worktree daemon (isolated automatically):
  Socket: {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.sock
  PID:    {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.pid
  Log:    {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.log
```

**How isolation works:**
1. Daemon CLI discovers project root by walking up from CWD to find `.claude/`
2. In a worktree, it finds the worktree's own `.claude/` directory (tracked by git)
3. Paths resolve relative to worktree root, not main workspace
4. No collision because each worktree has a different absolute path

**Starting daemon in worktree:**
```bash
cd /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X
PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python
$PYTHON -m claude_code_hooks_daemon.daemon.cli start
```

**Stopping daemon (MANDATORY before worktree removal):**
```bash
WT=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X
$WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop
```

**Reference:** Plan 00028 adds `--pid-file` and `--socket` CLI flags for explicit path overrides (optional, not required for basic isolation).

---

## Merge Protocol

### Child → Parent Worktree (ONLY AFTER ALL 4 VERIFICATION GATES PASS)

**CRITICAL**: NO merge allowed until Developer → Tester → QA → Senior Reviewer → Honesty Checker ALL approve.

**Verification Gate Workflow:**

```
Step 1: Developer completes implementation
  → Reports "ready for testing" via SendMessage
  → Team lead triggers Gate 1

Step 2: Tester Agent (Gate 1)
  → Tests in developer's worktree
  → Reports "tests verified" OR "tests failed"
  → If FAIL: back to developer (restart from Step 1)
  → If PASS: Team lead triggers Gate 2

Step 3: QA Agent (Gate 2)
  → QA checks in developer's worktree
  → Reports "QA verified" OR "QA failed"
  → If FAIL: back to developer (restart from Step 1)
  → If PASS: Team lead triggers Gate 3

Step 4: Senior Reviewer Agent (Gate 3)
  → Reviews completeness against plan
  → Reports "approved" OR "rejected with gaps"
  → If REJECTED: back to developer (restart from Step 1)
  → If APPROVED: Team lead triggers Gate 4

Step 5: Honesty Checker Agent (Gate 4 - FINAL)
  → Audits for theater (dead code, fake claims)
  → Reports "genuine completion" OR "theater detected"
  → If THEATER: ENTIRE BRANCH REJECTED (may need new plan)
  → If GENUINE: Team lead proceeds to merge

Step 6: Merge (ONLY after all 4 gates pass)
  → Team lead merges child to parent
```

**Merge Commands (After All Gates Pass):**

```bash
# Team lead operates from parent worktree
cd /workspace/untracked/worktrees/worktree-plan-NNNNN
PYTHON=/workspace/untracked/worktrees/worktree-plan-NNNNN/untracked/venv/bin/python

# 1. Verify all 4 gates passed (check message log)
# Gate 1: Tester reported "tests verified"
# Gate 2: QA reported "QA verified"
# Gate 3: Senior Reviewer reported "approved"
# Gate 4: Honesty Checker reported "genuine completion"

# 2. Review child changes
git log worktree-child-plan-NNNNN-task-a --oneline

# 3. Merge child into parent
git merge worktree-child-plan-NNNNN-task-a

# 4. Stop child daemon BEFORE removing worktree
CHILD_WT=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-a
$CHILD_WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# 5. Remove child worktree immediately
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-NNNNN-task-a
git branch -d worktree-child-plan-NNNNN-task-a

# 6. Send shutdown requests to ALL 5 agents for this task
SendMessage(type="shutdown_request", recipient="developer-task-a", content="Task merged")
SendMessage(type="shutdown_request", recipient="tester-task-a", content="Task merged")
SendMessage(type="shutdown_request", recipient="qa-task-a", content="Task merged")
SendMessage(type="shutdown_request", recipient="reviewer-task-a", content="Task merged")
SendMessage(type="shutdown_request", recipient="honesty-checker-task-a", content="Task merged")
```

**QA after each merge:**
```bash
cd /workspace/untracked/worktrees/worktree-plan-NNNNN
./scripts/qa/run_all.sh  # Verify integration works
```

### Parent → Main Project (REQUIRES FINAL HONESTY CHECK + HUMAN APPROVAL)

**CRITICAL MERGE ORDER**: ALWAYS `main → worktree` FIRST, then `worktree → main`.

**MANDATORY**: Final Honesty Checker must audit integrated code BEFORE merging to main.

```bash
# ===================================================================
# STEP 1: SYNC WORKTREE WITH MAIN FIRST (PREVENTS CONFLICTS!)
# ===================================================================
cd /workspace/untracked/worktrees/worktree-plan-NNNNN
PYTHON=/workspace/untracked/worktrees/worktree-plan-NNNNN/untracked/venv/bin/python

git fetch origin
git merge main --no-edit
# ⚠️ Resolve conflicts HERE in the worktree (isolated, safe)

./scripts/qa/run_all.sh  # QA MUST pass after sync
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING

# ===================================================================
# STEP 2: FINAL HONESTY CHECK (INTEGRATED CODE - CRITICAL!)
# ===================================================================
# Spawn final Honesty Checker agent to audit ENTIRE parent worktree
# This catches integration issues across all merged child branches

Task(
  subagent_type="general-purpose",
  team_name="plan-NNNNN",
  name="final-honesty-checker",
  prompt="You are the FINAL HONESTY CHECKER for Plan NNNNN.

  Audit the ENTIRE parent worktree: /workspace/untracked/worktrees/worktree-plan-NNNNN/

  Read CLAUDE/Plan/NNNNN-description/PLAN.md and verify:
  1. ALL plan goals achieved (not partial)
  2. ALL handlers/modules imported and used (no dead code)
  3. ALL handlers registered in config
  4. ALL claimed test counts accurate
  5. Integration between child branches works correctly
  6. No theater across the entire plan

  Report 'APPROVED FOR MAIN' or 'REJECT MERGE - theater/incomplete'."
)

# WAIT for final Honesty Checker report
# If REJECTED: DO NOT MERGE TO MAIN (fix issues in worktree)
# If APPROVED: Proceed to Step 3

# ===================================================================
# STEP 3: VERIFY MAIN WORKSPACE IS CLEAN
# ===================================================================
cd /workspace
git status  # MUST show "nothing to commit, working tree clean"

# ===================================================================
# STEP 4: ASK HUMAN FOR APPROVAL (MANDATORY!)
# ===================================================================
# Present to human:
#   - Final Honesty Checker approved merge
#   - All child branches verified through 4 gates
#   - Main workspace is clean
#   - QA passes in parent worktree
#   - Safe to merge now?
# WAIT FOR EXPLICIT "YES" BEFORE PROCEEDING

# ===================================================================
# STEP 5: MERGE PARENT TO MAIN (AFTER APPROVAL ONLY!)
# ===================================================================
git log worktree-plan-NNNNN --oneline  # Review changes
git merge worktree-plan-NNNNN --no-edit

# ===================================================================
# STEP 6: VERIFY MERGE SUCCEEDED IN MAIN
# ===================================================================
git status  # Should show clean state
./scripts/qa/run_all.sh  # All QA MUST pass in main workspace
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING

# If QA fails in main: REVERT MERGE IMMEDIATELY
git reset --hard HEAD~1

# ===================================================================
# STEP 7: PUSH TO ORIGIN
# ===================================================================
git push

# ===================================================================
# STEP 8: STOP DAEMON, THEN CLEANUP WORKTREE
# ===================================================================
WT=/workspace/untracked/worktrees/worktree-plan-NNNNN
$WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

git worktree remove untracked/worktrees/worktree-plan-NNNNN
git branch -D worktree-plan-NNNNN

# ===================================================================
# STEP 9: FINAL VERIFICATION
# ===================================================================
git status  # Confirm everything clean
```

**Why this order matters:**
1. **Sync first**: Brings main's changes into worktree (prevents conflicts)
2. **Resolve in worktree**: Conflicts resolved in isolated workspace (safe)
3. **QA in worktree**: Ensures changes work with current main
4. **Final Honesty Check**: Audit integrated code BEFORE touching main (NEW!)
5. **Clean main**: Uncommitted changes cause merge failures
6. **Human approval**: Final gate before main is modified
7. **QA in main**: Last verification after merge (with revert ready)
8. **Cleanup last**: Keep worktree until merge confirmed successful

---

## Lessons Learned from Agent Team Execution

### CRITICAL Lesson from Wave 2: False Completion Claims (2026-02-06)

**Problem**: 3 of 6 merged plans were incomplete with fabricated completion claims.

**Evidence**:
- Plan 00031 (Lock File Blocker): 0% done - README claimed "42 comprehensive tests" but ZERO tests exist, no handler file, no config registration. Complete fabrication.
- Plan 00021 (Language-Specific): 15-20% done - LanguageConfig created but never imported (dead code). Goal was "eliminate DRY violations" but violations remain untouched.
- Plan 003 (Planning Mode): 25-30% done - Plan had 8 phases, only 2 completed. Claimed complete when "ready for phase 2".

**Root Cause**:
- No independent verification of agent claims
- Agents could self-report "complete" without evidence
- Team lead trusted agent reports without auditing actual code
- No theater detection (code exists but accomplishes nothing)
- No verification of goal achievement vs plan

**Solution (This Document)**:
- **Multi-role verification**: 5 agents per task (Developer, Tester, QA, Reviewer, Honesty Checker)
- **4 verification gates**: Each must pass before merge
- **Developers cannot claim completion**: Only "ready for testing"
- **Honesty Checker role**: Specifically audits for theater and false claims
- **Final integration audit**: Honesty Checker audits entire parent worktree before merge to main
- **Evidence-based approval**: Claims must be verified with actual code inspection

**Prevention**:
- Never trust agent self-reports without independent verification
- Always count actual deliverables vs claimed deliverables
- Check if code is actually imported/used (not dead code)
- Verify handlers are registered in config
- Verify plan goals actually achieved (not just code written)
- Use nuclear veto (reject entire branch) if theater detected

---

### Lesson from Wave 1: Daemon Cross-Kill (Plan 00028)

**Problem**: Agents in worktrees restarting daemons killed the main workspace daemon.

**Root Cause**:
- Hostname-based socket names (`daemon-{hostname}.sock`)
- Agent CWD confusion (still in `/workspace` instead of worktree)
- Daemon CLI discovered main workspace's `.claude/` instead of worktree's

**Solution**:
- Worktree isolation now automatic (daemon discovers worktree's own `.claude/`)
- Plan 00028 adds `--pid-file`/`--socket` CLI flags for explicit overrides
- Agent prompts now include explicit `cd` to worktree path

**Prevention**: Always verify agent's `pwd` before daemon operations.

### Lesson from Wave 1: Agent Autonomy (Turn Limits)

**Problem**: Agents hit turn limits before committing work.

**Root Cause**:
- Prompts said "run QA" but didn't emphasize autonomy
- Team lead checked on agents too frequently (micromanagement)
- Agents waited for approval to commit

**Solution**:
- Developer prompts now include explicit workflow steps
- Instructions: "Run QA and commit BEFORE your turn limit"
- Verification agents spawned AFTER developer commits (not during)
- Team lead waits for "ready for testing" message (doesn't micromanage)

**Prevention**: Make agent prompts self-sufficient with complete workflow. Separate implementation from verification (different agents).

### Lesson from Wave 1: Memory Writes Blocked (Plan 00029)

**Problem**: Agents couldn't write to Claude Code's auto memory (`/root/.claude/projects/-workspace/memory/MEMORY.md`).

**Root Cause**:
- `markdown_organization` handler blocked writes outside project root
- Memory directory at `/root/.claude/` is outside `/workspace/`

**Solution**:
- Plan 00029 fixes handler to only enforce rules for files within project
- Handler now checks if file is under project root before enforcing

**Prevention**: Test handlers with paths outside project boundaries.

**Verification Impact**: Tester agents should test handlers with boundary conditions (files outside project root).

### Lesson 4: Sequential QA Required

**Problem**: Running `./scripts/qa/run_all.sh` in multiple worktrees simultaneously caused failures.

**Root Cause**:
- Daemon integration tests (`test_daemon_smoke.py`) compete for socket paths
- MyPy cache corruption from concurrent type checker runs

**Solution**:
- Use `scripts/validate_worktrees.sh` (runs QA sequentially across worktrees)
- Each agent runs QA in their OWN worktree (safe if not concurrent with same worktree)

**Prevention**: Don't run QA in same worktree from multiple processes.

### Lesson 5: Venv Per Worktree (Editable Install)

**Problem**: Agents using main workspace venv didn't pick up their code changes.

**Root Cause**:
- `pip install -e .` points to a specific `src/` directory
- Main workspace venv points to `/workspace/src/`
- Agent's changes in `/workspace/untracked/worktrees/worktree-X/src/` not visible

**Solution**:
- **Every worktree needs its own venv**
- Venv setup is mandatory: `python3 -m venv untracked/venv && pip install -e ".[dev]"`
- Agent prompts include explicit `PYTHON=` path to worktree venv

**Prevention**: Use `scripts/setup_worktree.sh` to automate venv creation.

### Lesson 6: Daemon Restart Verification

**Problem**: Code merged with import errors that unit tests didn't catch.

**Root Cause**:
- Unit tests use mocks, don't import handlers through daemon registry
- Agents skipped daemon restart check before committing

**Solution**:
- **MANDATORY in agent prompts**: Verify daemon restarts after code changes
- Command: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
- Expected output: `Status: RUNNING`

**Prevention**: Add daemon restart to QA checklist in agent prompts.

---

## Troubleshooting

### Agent Working in Wrong Directory

**Symptoms**: Files appearing in `/workspace/` instead of worktree.

**Solution**:
1. Stop agent immediately
2. Check agent's actual working directory
3. Move files to correct worktree: `git mv src/file.py {worktree}/src/file.py`
4. Remind agent of correct path in next message
5. Update agent prompt to be more explicit about location

### Daemon Cross-Kill Between Worktrees

**Symptoms**: Restarting daemon in one worktree affects another.

**Solution**:
1. Verify each worktree has its own socket path: `ls .claude/hooks-daemon/untracked/`
2. Check agent is actually in worktree: `pwd`
3. Use explicit paths if needed (Plan 00028): `--pid-file` and `--socket` flags
4. See @CLAUDE/Worktree.md "Daemon Process Isolation" section

### Agent Hit Turn Limit Without Committing

**Symptoms**: Agent stops responding, work is uncommitted.

**Solution**:
1. Check worktree for uncommitted changes: `cd {worktree} && git status`
2. Review changes, finish QA manually if needed
3. Commit work with plan reference
4. Update agent prompt for next task to emphasize autonomy

### Merge Conflicts During Parent → Main

**Symptoms**: `git merge worktree-plan-NNNNN` fails with conflicts.

**Solution**:
1. **ABORT THE MERGE**: `git merge --abort`
2. **Go back to worktree**: `cd /workspace/untracked/worktrees/worktree-plan-NNNNN`
3. **Sync worktree with main FIRST**: `git merge main --no-edit`
4. **Resolve conflicts in worktree** (isolated, safe)
5. **Run QA in worktree**: `./scripts/qa/run_all.sh`
6. **NOW merge to main**: `cd /workspace && git merge worktree-plan-NNNNN`

**Prevention**: ALWAYS sync worktree with main BEFORE merging to main.

### Orphaned Daemon After Worktree Removal

**Symptoms**: `ps aux | grep claude_code_hooks_daemon` shows process for deleted worktree.

**Solution**:
1. Find orphaned process PID: `ps aux | grep claude_code_hooks_daemon | grep -v grep`
2. Kill the process: `kill <PID>`
3. Clean up stale socket: `rm -f /path/to/.claude/hooks-daemon/untracked/daemon-*.sock`

**Prevention**: ALWAYS stop daemon BEFORE removing worktree.

---

## Automation Scripts

### `scripts/setup_worktree.sh` - Create Worktree with Venv

Automates worktree creation, venv setup, editable install, and verification.

```bash
# Create parent worktree from main:
./scripts/setup_worktree.sh worktree-plan-NNNNN

# Create child worktree from parent:
./scripts/setup_worktree.sh worktree-child-plan-NNNNN-task-a worktree-plan-NNNNN
```

**What it does:**
1. Validates branch name (must start with `worktree-`)
2. Creates git worktree in `untracked/worktrees/`
3. Creates Python venv at `{worktree}/untracked/venv/`
4. Installs package in editable mode (`pip install -e ".[dev]"`)
5. Verifies editable install points to worktree's own `src/`
6. Creates daemon untracked directory
7. Prints agent prompt template

**See**: @CLAUDE/Worktree.md "Automation Scripts" section

### `scripts/validate_worktrees.sh` - Sequential QA Validation

Runs QA across all (or specific) worktrees sequentially.

```bash
# Validate all worktrees:
./scripts/validate_worktrees.sh

# Validate specific worktree:
./scripts/validate_worktrees.sh worktree-plan-NNNNN
```

**What it does:**
1. Checks venv exists and editable install is correct
2. Runs `./scripts/qa/run_all.sh` from within each worktree
3. Reports pass/fail summary for all worktrees

**See**: @CLAUDE/Worktree.md "Automation Scripts" section

---

## Complete Workflow Example (With Multi-Role Verification)

### Scenario: Plan 00028 - Implement 4 Handlers in Parallel

**Phase 1: Setup (Team Lead)**

```bash
# 1. Create parent worktree
cd /workspace
./scripts/setup_worktree.sh worktree-plan-00028

# 2. Create 4 child worktrees (one per handler)
for task in handler-a handler-b handler-c handler-d; do
  ./scripts/setup_worktree.sh worktree-child-plan-00028-${task} worktree-plan-00028
done

# 3. Create team and tasks
TeamCreate(team_name="plan-00028", description="Implement 4 handlers with verification")
TaskCreate(subject="Implement handler A", description="...", activeForm="Implementing handler A")
TaskCreate(subject="Implement handler B", description="...", activeForm="Implementing handler B")
TaskCreate(subject="Implement handler C", description="...", activeForm="Implementing handler C")
TaskCreate(subject="Implement handler D", description="...", activeForm="Implementing handler D")

# 4. Spawn DEVELOPER agents only (verification agents spawn later)
Task(subagent_type="general-purpose", team_name="plan-00028", name="developer-handler-a",
     prompt="[Use Developer Agent Template - handler A]")
Task(subagent_type="general-purpose", team_name="plan-00028", name="developer-handler-b",
     prompt="[Use Developer Agent Template - handler B]")
Task(subagent_type="general-purpose", team_name="plan-00028", name="developer-handler-c",
     prompt="[Use Developer Agent Template - handler C]")
Task(subagent_type="general-purpose", team_name="plan-00028", name="developer-handler-d",
     prompt="[Use Developer Agent Template - handler D]")
```

**Phase 2: Developer Work (Parallel)**

Each developer agent in their worktree:
1. Marks task `in_progress`
2. Writes failing tests FIRST (TDD)
3. Implements handler to make tests pass
4. Runs `./scripts/qa/run_all.sh`
5. Verifies daemon restarts successfully
6. Commits with "Plan 00028: " prefix
7. Updates task to `ready_for_testing` (NOT completed)
8. Reports "ready for testing" to team lead

**Phase 3: Verification Gates (Sequential per Task)**

For each handler (A, B, C, D) that reports "ready for testing":

```bash
# ===================================================================
# GATE 1: TESTER AGENT
# ===================================================================
# Developer reports "ready for testing"
# Team lead spawns Tester agent

Task(subagent_type="general-purpose", team_name="plan-00028", name="tester-handler-a",
     prompt="[Use Tester Agent Template - handler A]")

# Wait for Tester report:
# - If "tests failed": Developer must fix, restart from Gate 1
# - If "tests verified": Proceed to Gate 2

# ===================================================================
# GATE 2: QA AGENT
# ===================================================================
# Tester reports "tests verified"
# Team lead spawns QA agent

Task(subagent_type="general-purpose", team_name="plan-00028", name="qa-handler-a",
     prompt="[Use QA Agent Template - handler A]")

# Wait for QA report:
# - If "QA failed": Developer must fix, restart from Gate 1
# - If "QA verified": Proceed to Gate 3

# ===================================================================
# GATE 3: SENIOR REVIEWER
# ===================================================================
# QA reports "QA verified"
# Team lead spawns Senior Reviewer agent

Task(subagent_type="general-purpose", team_name="plan-00028", name="reviewer-handler-a",
     prompt="[Use Senior Reviewer Template - handler A]")

# Wait for Reviewer report:
# - If "rejected": Developer must fix, restart from Gate 1
# - If "approved": Proceed to Gate 4

# ===================================================================
# GATE 4: HONESTY CHECKER (CRITICAL)
# ===================================================================
# Reviewer reports "approved"
# Team lead spawns Honesty Checker agent

Task(subagent_type="general-purpose", team_name="plan-00028", name="honesty-checker-handler-a",
     prompt="[Use Honesty Checker Template - handler A]")

# Wait for Honesty Checker report:
# - If "theater detected": REJECT ENTIRE BRANCH (may need replanning)
# - If "genuine completion": Proceed to merge

# ===================================================================
# MERGE APPROVED WORK
# ===================================================================
# All 4 gates passed for handler A
# Team lead merges child A to parent

cd /workspace/untracked/worktrees/worktree-plan-00028
git merge worktree-child-plan-00028-handler-a

# Stop daemon, cleanup child A
CHILD=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-a
$CHILD/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-a
git branch -d worktree-child-plan-00028-handler-a

# Send shutdown to ALL 5 agents for handler A
SendMessage(type="shutdown_request", recipient="developer-handler-a", content="Merged")
SendMessage(type="shutdown_request", recipient="tester-handler-a", content="Merged")
SendMessage(type="shutdown_request", recipient="qa-handler-a", content="Merged")
SendMessage(type="shutdown_request", recipient="reviewer-handler-a", content="Merged")
SendMessage(type="shutdown_request", recipient="honesty-checker-handler-a", content="Merged")

# Repeat entire verification flow for handlers B, C, D...
```

**Phase 4: Final Integration Verification (Team Lead)**

```bash
# All 4 handlers merged to parent worktree
# Run full QA in parent
cd /workspace/untracked/worktrees/worktree-plan-00028
PYTHON=/workspace/untracked/worktrees/worktree-plan-00028/untracked/venv/bin/python
./scripts/qa/run_all.sh
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Sync worktree with main FIRST
git merge main --no-edit
./scripts/qa/run_all.sh  # Verify still passes after sync

# CRITICAL: Final Honesty Check on integrated code
Task(subagent_type="general-purpose", team_name="plan-00028", name="final-honesty-checker",
     prompt="Audit ENTIRE parent worktree /workspace/untracked/worktrees/worktree-plan-00028/
             Verify: all 4 handlers imported/used, all in config, integration works, goals achieved.
             Report 'APPROVED FOR MAIN' or 'REJECT MERGE'.")

# Wait for final Honesty Checker
# - If REJECTED: Fix issues in parent worktree, DO NOT merge to main
# - If APPROVED: Proceed to human approval
```

**Phase 5: Merge to Main (After Human Approval)**

```bash
# Ask human for approval (MANDATORY)
# Present: Final Honesty Checker approved, all handlers verified, QA passes
# Wait for explicit "YES"

# Merge to main
cd /workspace
git merge worktree-plan-00028 --no-edit

# Verify QA in main
./scripts/qa/run_all.sh
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# If QA fails: git reset --hard HEAD~1 (REVERT IMMEDIATELY)

# Push to origin
git push

# Stop daemon, cleanup parent
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -D worktree-plan-00028

# Clean up team
TeamDelete()
```

**Phase 6: Plan Completion**

Follow plan completion checklist from @CLAUDE/PlanWorkflow.md:
1. Update PLAN.md status to Complete (with accurate completion date)
2. Move plan to `CLAUDE/Plan/Completed/`
3. Update `CLAUDE/Plan/README.md` (accurate status, not theater)
4. Commit with "Plan 00028: Complete" message

**Summary of Agent Count:**
- 4 Developer agents (one per handler)
- 4 Tester agents (one per handler)
- 4 QA agents (one per handler)
- 4 Senior Reviewer agents (one per handler)
- 4 Honesty Checker agents (one per handler)
- 1 Final Honesty Checker (entire plan integration)
- **Total: 21 agents** (vs 4 in old workflow)

**Why this overhead is necessary:**
Wave 2 audit revealed 50% of merged work was incomplete with false claims. The multi-role verification prevents this by requiring independent evidence at every gate.

---

## Quick Reference

### Team Lead Checklist (Multi-Role Verification)

**Setup:**
- [ ] Plan exists with decomposed tasks
- [ ] Main workspace clean (`git status`)
- [ ] Parent worktree created with venv
- [ ] Child worktrees created with venvs (one per task)
- [ ] Team created with `TeamCreate`
- [ ] Tasks created with `TaskCreate`
- [ ] Developer agents spawned (verification agents spawn later)

**Per Task - Verification Gates:**
- [ ] **Gate 1**: Developer reports "ready for testing" → Spawn Tester agent
- [ ] **Gate 2**: Tester reports "tests verified" → Spawn QA agent
- [ ] **Gate 3**: QA reports "QA verified" → Spawn Senior Reviewer agent
- [ ] **Gate 4**: Reviewer reports "approved" → Spawn Honesty Checker agent
- [ ] **Merge Decision**: Honesty Checker reports "genuine" → Merge child to parent
- [ ] If ANY gate fails → Send back to developer, restart from Gate 1

**Per Task - Integration (After All 4 Gates Pass):**
- [ ] Merge child → parent (only after all 4 gates pass)
- [ ] Stop child daemon BEFORE removing worktree
- [ ] Run QA in parent after merge
- [ ] Send shutdown to ALL 5 agents for that task

**Final Integration (All Tasks Merged to Parent):**
- [ ] Run full QA in parent worktree
- [ ] Sync parent with main BEFORE merging to main
- [ ] **Spawn final Honesty Checker** to audit entire parent worktree
- [ ] Final Honesty Checker approves → Ask human for approval
- [ ] Human approves → Merge parent to main
- [ ] Run QA in main (if fails: REVERT IMMEDIATELY)
- [ ] Push to origin
- [ ] Stop parent daemon, cleanup worktree

**Cleanup:**
- [ ] `TeamDelete()` to clean up team resources
- [ ] Update plan status to Complete (accurate percentage, no theater)
- [ ] Move plan to Completed/ folder
- [ ] Update README.md with honest summary

### Developer Agent Checklist

**Setup:**
- [ ] Verify in correct worktree: `pwd` shows your path
- [ ] `PYTHON` points to worktree venv
- [ ] Task marked `in_progress`

**Execution:**
- [ ] Write failing tests FIRST (TDD)
- [ ] Implement code to pass tests
- [ ] Run `./scripts/qa/run_all.sh` (MUST pass)
- [ ] Verify daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
- [ ] Commit with "Plan NNNNN: " prefix
- [ ] Update task to `ready_for_testing` (NOT completed)

**Completion:**
- [ ] Report "ready for testing" via `SendMessage` to team-lead
- [ ] Wait for verification gate feedback
- [ ] Fix issues if any gate fails (restart from Gate 1)
- [ ] Respond to shutdown request with `SendMessage(type="shutdown_response")`

### Tester Agent Checklist (Gate 1)

- [ ] Verify in developer's worktree
- [ ] Run full test suite: `./scripts/qa/run_tests.sh`
- [ ] Execute acceptance tests from PLAN.md
- [ ] Test actual functionality (trigger handler)
- [ ] Verify behavior matches plan
- [ ] Report "tests verified" (pass) OR "tests failed" (reject) via `SendMessage`

### QA Agent Checklist (Gate 2)

- [ ] Verify in developer's worktree
- [ ] Run `./scripts/qa/run_all.sh` (all 7 checks)
- [ ] Verify daemon restarts successfully
- [ ] Check coverage ≥ 95%
- [ ] Verify no security issues
- [ ] Report "QA verified" (pass) OR "QA failed" (reject) via `SendMessage`

### Senior Reviewer Checklist (Gate 3)

- [ ] Verify in developer's worktree
- [ ] Read PLAN.md goals and success criteria
- [ ] Review all code changes
- [ ] Verify ALL plan phases complete (not partial)
- [ ] Check architecture (no duplication, correct patterns)
- [ ] Verify success criteria met
- [ ] Report "approved" OR "rejected with gaps" via `SendMessage`

### Honesty Checker Checklist (Gate 4 - CRITICAL)

- [ ] Verify in developer's worktree
- [ ] **Check 1**: Search for imports - is code actually used?
- [ ] **Check 2**: Verify handler registered in `.claude/hooks-daemon.yaml`
- [ ] **Check 3**: Count actual tests - matches claimed count?
- [ ] **Check 4**: Verify plan goals actually achieved (not just code exists)
- [ ] **Check 5**: Verify ALL phases have deliverables (not partial)
- [ ] Report "genuine completion" OR "theater detected - REJECT" via `SendMessage`
- [ ] Use nuclear veto if theater found (reject entire branch)

---

## See Also

- **@CLAUDE/Worktree.md** - Git worktree mechanics and detailed workflows
- **@CLAUDE/PlanWorkflow.md** - Planning standards and templates
- **@CLAUDE/CodeLifecycle/Features.md** - TDD workflow for features
- **@CLAUDE/CodeLifecycle/General.md** - General code change lifecycle
- **Plan 00028** - Daemon CLI explicit paths for isolation
- **Plan 00029** - Fix markdown handler memory writes

---

**Maintained by**: Claude Code Hooks Daemon Contributors
**Last Updated**: 2026-02-06
**Based on**: Wave 1 POC execution (Plans 00016-00027)
