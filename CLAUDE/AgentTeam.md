# Agent Team Workflow for Claude Code Hooks Daemon

**Version**: 1.0
**Status**: Definitive reference for agent team execution
**Audience**: Team leads (human or AI) coordinating parallel agent work

---

## Overview

This document provides project-specific guidance for running **agent teams with git worktrees** on the Claude Code Hooks Daemon project. It captures lessons learned from the Wave 1 POC (Plans 00016-00027, executed 2026-02-06) and provides definitive workflows for future multi-agent work.

**When to use agent teams:**
- Plans with 3+ independent tasks (handlers, modules, tests)
- Tasks that can execute in parallel without file conflicts
- Work requiring 4+ hours that can be decomposed

**When NOT to use agent teams:**
- Single-file edits or quick fixes
- Sequential work where context matters (refactoring interconnected modules)
- Exploratory work without clear task boundaries

---

## Prerequisites

Before creating an agent team, ensure:

1. **System packages installed**: `python3-venv` (for creating virtual environments)
2. **Worktree knowledge**: Read **@CLAUDE/Worktree.md** for git worktree mechanics
3. **Plan exists**: Create plan in `CLAUDE/Plan/NNNNN-description/PLAN.md` following @CLAUDE/PlanWorkflow.md
4. **Tasks decomposed**: Plan has clear, independent tasks suitable for parallel execution
5. **Main workspace clean**: `git status` shows no uncommitted changes

---

## Architecture

```
Main Workspace (/workspace/)
    ↓ Team Lead operates here (orchestration only)
    │
    ├── Parent Worktree (worktree-plan-NNNNN)
    │   ↓ Integration worktree (merges happen here)
    │   │
    │   ├── Child Worktree 1 (worktree-child-plan-NNNNN-task-a) ← Agent 1
    │   ├── Child Worktree 2 (worktree-child-plan-NNNNN-task-b) ← Agent 2
    │   ├── Child Worktree 3 (worktree-child-plan-NNNNN-task-c) ← Agent 3
    │   └── Child Worktree 4 (worktree-child-plan-NNNNN-task-d) ← Agent 4
```

**Key Principle**: Team lead creates worktrees, spawns agents, coordinates merges. Agents stay isolated in their child worktrees.

---

## Team Lead Responsibilities

The team lead (operating from `/workspace/`) is responsible for:

### 1. Setup Phase

**Do:**
- Create parent worktree from main branch
- Create child worktrees from parent branch (one per agent)
- Set up Python venv in each worktree (`python3 -m venv untracked/venv`)
- Create agent team with `TeamCreate`
- Create tasks with `TaskCreate` (one per child worktree)
- Spawn agents with `Task` tool, passing self-sufficient prompts

**Don't:**
- Work in child worktrees (that's for agents)
- Micromanage agents (check status every few minutes)
- Skip venv setup (agents will fail immediately)

### 2. Monitoring Phase

**Do:**
- Wait for agents to report completion via `SendMessage`
- Review agent code when they report done
- Answer questions if agents are blocked

**Don't:**
- Interrupt agents mid-work to check progress
- Manually check task status obsessively (trust the agents)
- Merge before agents report completion

### 3. Integration Phase

**Do:**
- Merge child → parent sequentially as agents complete
- Stop each child's daemon BEFORE removing its worktree
- Run full QA in parent worktree after all merges
- Sync parent with main (`git merge main --no-edit`) BEFORE merging to main
- Ask human for approval before merging parent → main

**Don't:**
- Merge multiple children in parallel (conflicts likely)
- Skip QA between merges
- Merge parent to main without syncing first
- Remove worktrees without stopping daemons

### 4. Cleanup Phase

**Do:**
- Stop parent daemon after merge to main succeeds
- Remove parent worktree and branch immediately
- Send shutdown requests to all agents
- Use `TeamDelete` to clean up team resources
- Update plan status to Complete (see @CLAUDE/PlanWorkflow.md)

**Don't:**
- Leave merged worktrees around
- Skip daemon shutdown (creates orphaned processes)
- Forget to update plan documentation

---

## Agent Responsibilities

Each agent (operating from `/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/`) MUST:

### 1. Stay in Your Worktree (CRITICAL)

**Do:**
- Verify `pwd` shows your worktree path before ANY file operation
- Use absolute paths relative to your worktree root
- Set `PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python`

**Don't:**
- `cd /workspace` (that's the team lead's workspace)
- Work in the parent worktree or other child worktrees
- Use the main workspace's venv (`/workspace/untracked/venv/`)

### 2. Complete Work Autonomously

**Do:**
- Read your task from `TaskList`
- Mark task `in_progress` when starting
- Write tests first (TDD - see @CLAUDE/CodeLifecycle/Features.md)
- Run `./scripts/qa/run_all.sh` (MUST pass before committing)
- Verify daemon loads: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
- Commit with plan reference: `Plan NNNNN: Task description`
- Mark task `completed` when done
- Report completion via `SendMessage` to team lead

**Don't:**
- Stop work before running QA (agents hitting turn limits learned this lesson)
- Commit without verifying daemon restarts
- Ask team lead for permission to commit (you're autonomous)
- Leave task status stale

### 3. Communicate via SendMessage

**Do:**
- Send message when blocked or have questions
- Report completion when task is done and committed
- Respond to shutdown requests with `type: "shutdown_response"`

**Don't:**
- Just type responses in text (not visible to team lead!)
- Go silent for long periods without status updates

### 4. Handle Shutdown Gracefully

**Do:**
- When you receive `type: "shutdown_request"`, verify your work is committed
- Respond with `SendMessage(type="shutdown_response", request_id="...", approve=true)`
- If not done, reject with explanation: `approve=false, content="Still working on tests"`

**Don't:**
- Just say "I'll shut down" in text (use the tool!)
- Approve shutdown if you have uncommitted work

---

## Agent Prompt Template (Copy-Paste Ready)

Use this template when spawning agents with the `Task` tool:

```
You are working on Plan NNNNN: [Plan Name].

CRITICAL WORKTREE ISOLATION:
- Your worktree: /workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/
- DO NOT work in /workspace - ONLY work in YOUR worktree
- PYTHON=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-X/untracked/venv/bin/python

YOUR TASK:
Read CLAUDE/Plan/NNNNN-description/PLAN.md and execute Task X:
1. [Specific task description]
2. Follow TDD: write failing tests first (see @CLAUDE/CodeLifecycle/Features.md)
3. Run QA: ./scripts/qa/run_all.sh (MUST pass)
4. Verify daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status
5. Commit with "Plan NNNNN: " prefix
6. Mark TaskList task #N as completed when done

Check TaskList for task #N, mark in_progress, then completed when done.
Report completion via SendMessage to team-lead.

AUTONOMY:
- You are FULLY AUTONOMOUS - complete your task without asking for permission
- Run QA and commit BEFORE your turn limit
- If blocked, send a message explaining the blocker
```

**Key elements:**
- Explicit worktree path (prevents working in wrong directory)
- Explicit Python path (prevents using wrong venv)
- Complete instructions (prevents hitting turn limits before committing)
- Task reference (clear ownership)
- QA + daemon restart (mandatory verification)
- SendMessage reminder (agents must use the tool)

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

### Child → Parent Worktree (ALLOWED - No Approval)

Agents complete tasks, team lead merges their work into the parent worktree.

```bash
# Team lead operates from parent worktree
cd /workspace/untracked/worktrees/worktree-plan-NNNNN
PYTHON=/workspace/untracked/worktrees/worktree-plan-NNNNN/untracked/venv/bin/python

# 1. Review child changes
git log worktree-child-plan-NNNNN-task-a --oneline

# 2. Merge child into parent
git merge worktree-child-plan-NNNNN-task-a

# 3. Stop child daemon BEFORE removing worktree
CHILD_WT=/workspace/untracked/worktrees/worktree-child-plan-NNNNN-task-a
$CHILD_WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# 4. Remove child worktree immediately
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-NNNNN-task-a
git branch -d worktree-child-plan-NNNNN-task-a

# 5. Send shutdown request to agent
SendMessage(type="shutdown_request", recipient="agent-task-a", content="Task merged, shutting down")
```

**QA after each merge:**
```bash
cd /workspace/untracked/worktrees/worktree-plan-NNNNN
./scripts/qa/run_all.sh  # Verify integration works
```

### Parent → Main Project (REQUIRES APPROVAL)

**CRITICAL MERGE ORDER**: ALWAYS `main → worktree` FIRST, then `worktree → main`.

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
# STEP 2: VERIFY MAIN WORKSPACE IS CLEAN
# ===================================================================
cd /workspace
git status  # MUST show "nothing to commit, working tree clean"

# ===================================================================
# STEP 3: ASK HUMAN FOR APPROVAL (MANDATORY!)
# ===================================================================
# Confirm with human:
#   - Is main branch clean?
#   - Are all agents stopped?
#   - Is it safe to merge now?
# WAIT FOR EXPLICIT "YES" BEFORE PROCEEDING

# ===================================================================
# STEP 4: MERGE PARENT TO MAIN (AFTER APPROVAL ONLY!)
# ===================================================================
git log worktree-plan-NNNNN --oneline  # Review changes
git merge worktree-plan-NNNNN --no-edit

# ===================================================================
# STEP 5: VERIFY MERGE SUCCEEDED
# ===================================================================
git status  # Should show clean state
./scripts/qa/run_all.sh  # All QA MUST pass in main workspace
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING

# ===================================================================
# STEP 6: PUSH TO ORIGIN
# ===================================================================
git push

# ===================================================================
# STEP 7: STOP DAEMON, THEN CLEANUP WORKTREE
# ===================================================================
WT=/workspace/untracked/worktrees/worktree-plan-NNNNN
$WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

git worktree remove untracked/worktrees/worktree-plan-NNNNN
git branch -D worktree-plan-NNNNN

# ===================================================================
# STEP 8: FINAL VERIFICATION
# ===================================================================
git status  # Confirm everything clean
```

**Why this order matters:**
1. **Sync first**: Brings main's changes into worktree (prevents conflicts)
2. **Resolve in worktree**: Conflicts resolved in isolated workspace (safe)
3. **QA in worktree**: Ensures changes work with current main
4. **Clean main**: Uncommitted changes cause merge failures
5. **Human approval**: Multiple agents may be active, need coordination
6. **Cleanup last**: Keep worktree until merge confirmed successful

---

## Lessons Learned from Wave 1 POC

### Lesson 1: Daemon Cross-Kill (Plan 00028)

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

### Lesson 2: Agent Autonomy (Turn Limits)

**Problem**: Agents hit turn limits before committing work.

**Root Cause**:
- Prompts said "run QA" but didn't emphasize autonomy
- Team lead checked on agents too frequently (micromanagement)
- Agents waited for approval to commit

**Solution**:
- Prompts now include "FULLY AUTONOMOUS" explicitly
- Instructions: "Run QA and commit BEFORE your turn limit"
- Team lead doesn't check status until agent reports completion

**Prevention**: Make agent prompts self-sufficient with complete workflow.

### Lesson 3: Memory Writes Blocked (Plan 00029)

**Problem**: Agents couldn't write to Claude Code's auto memory (`/root/.claude/projects/-workspace/memory/MEMORY.md`).

**Root Cause**:
- `markdown_organization` handler blocked writes outside project root
- Memory directory at `/root/.claude/` is outside `/workspace/`

**Solution**:
- Plan 00029 fixes handler to only enforce rules for files within project
- Handler now checks if file is under project root before enforcing

**Prevention**: Test handlers with paths outside project boundaries.

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

## Complete Workflow Example

### Scenario: Plan 00028 - Implement 4 Handlers in Parallel

**Phase 1: Setup (Team Lead)**

```bash
# 1. Create parent worktree
cd /workspace
./scripts/setup_worktree.sh worktree-plan-00028

# 2. Create 4 child worktrees
for task in handler-a handler-b handler-c handler-d; do
  ./scripts/setup_worktree.sh worktree-child-plan-00028-${task} worktree-plan-00028
done

# 3. Create team and tasks
TeamCreate(team_name="plan-00028", description="Implement 4 handlers")
TaskCreate(subject="Implement handler A", description="...", activeForm="Implementing handler A")
TaskCreate(subject="Implement handler B", description="...", activeForm="Implementing handler B")
TaskCreate(subject="Implement handler C", description="...", activeForm="Implementing handler C")
TaskCreate(subject="Implement handler D", description="...", activeForm="Implementing handler D")

# 4. Spawn 4 agents (use prompt template above)
Task(subagent_type="general-purpose", team_name="plan-00028", name="agent-handler-a", prompt="...")
Task(subagent_type="general-purpose", team_name="plan-00028", name="agent-handler-b", prompt="...")
Task(subagent_type="general-purpose", team_name="plan-00028", name="agent-handler-c", prompt="...")
Task(subagent_type="general-purpose", team_name="plan-00028", name="agent-handler-d", prompt="...")
```

**Phase 2: Agents Work (Parallel)**

Each agent in their worktree:
1. Marks task `in_progress`
2. Writes failing tests (TDD)
3. Implements handler
4. Runs `./scripts/qa/run_all.sh`
5. Verifies daemon: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
6. Commits with "Plan 00028: " prefix
7. Marks task `completed`
8. Sends completion message to team lead

**Phase 3: Integration (Team Lead)**

As each agent reports completion:

```bash
# Merge child A to parent
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge worktree-child-plan-00028-handler-a

# Stop daemon, cleanup child A
CHILD=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-a
$CHILD/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-a
git branch -d worktree-child-plan-00028-handler-a

# Send shutdown to agent A
SendMessage(type="shutdown_request", recipient="agent-handler-a", content="Task merged")

# Repeat for agents B, C, D...
```

**Phase 4: Final QA and Merge to Main (Team Lead)**

```bash
# Run full QA in parent worktree
cd /workspace/untracked/worktrees/worktree-plan-00028
PYTHON=/workspace/untracked/worktrees/worktree-plan-00028/untracked/venv/bin/python
./scripts/qa/run_all.sh
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Sync worktree with main FIRST
git merge main --no-edit
./scripts/qa/run_all.sh  # Verify still passes

# Ask human for approval
# ... wait for "yes" ...

# Merge to main
cd /workspace
git merge worktree-plan-00028 --no-edit
git push

# Stop daemon, cleanup parent
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -D worktree-plan-00028

# Clean up team
TeamDelete()
```

**Phase 5: Plan Completion**

Follow plan completion checklist from @CLAUDE/PlanWorkflow.md:
1. Update PLAN.md status to Complete
2. Move plan to `CLAUDE/Plan/Completed/`
3. Update `CLAUDE/Plan/README.md`
4. Commit with "Plan 00028: Complete" message

---

## Quick Reference

### Team Lead Checklist

**Setup:**
- [ ] Plan exists with decomposed tasks
- [ ] Main workspace clean (`git status`)
- [ ] Parent worktree created with venv
- [ ] Child worktrees created with venvs (one per agent)
- [ ] Team created with `TeamCreate`
- [ ] Tasks created with `TaskCreate`
- [ ] Agents spawned with self-sufficient prompts

**Monitoring:**
- [ ] Wait for agents to report completion (don't micromanage)
- [ ] Answer questions if agents blocked

**Integration:**
- [ ] Merge children → parent sequentially as they complete
- [ ] Stop each child's daemon BEFORE removing worktree
- [ ] Run QA in parent after each merge
- [ ] Sync parent with main BEFORE merging to main
- [ ] Ask human for approval
- [ ] Merge parent → main (after approval)
- [ ] Push to origin
- [ ] Stop parent daemon, cleanup worktree

**Cleanup:**
- [ ] Send shutdown requests to all agents
- [ ] `TeamDelete()` to clean up team resources
- [ ] Update plan status to Complete
- [ ] Move plan to Completed/ folder

### Agent Checklist

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
- [ ] Mark task `completed`

**Completion:**
- [ ] Report via `SendMessage` to team lead
- [ ] Respond to shutdown request with `SendMessage(type="shutdown_response")`

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
