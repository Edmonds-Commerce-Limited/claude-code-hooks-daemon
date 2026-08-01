# Worktree Workflow

Git worktree workflow for isolated, safe refactoring and development.

```bash
# ✅ CORRECT ORDER:
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge main --no-edit              # 1. Sync worktree with main FIRST
./scripts/qa/run_all.sh              # 2. Verify QA still passes
cd /workspace
git merge worktree-plan-00028        # 3. ONLY THEN merge to main

# ❌ WRONG - Will cause conflicts and lost work:
cd /workspace
git merge worktree-plan-00028        # DON'T DO THIS WITHOUT STEP 1!
```

## Overview

Git worktrees allow multiple working directories from a single repository, enabling parallel development without branch-switching disruption. This is **essential** for running parallel agents on different tasks.

### Hierarchical Structure

Worktrees support **parent-child relationships** for complex plans:

- **Parent (Plan) Worktrees**: Top-level worktree for a plan (e.g., Plan 00028)
- **Child (Task) Worktrees**: Individual tasks within the plan

**Merge Rules:**

- ✅ **ALLOWED**: Child → Parent worktree (automatic, no approval needed)
- ❌ **NOT ALLOWED**: Parent → Main project (requires human approval)

## Critical Rules

### 1. Worktree Location

**ALL worktree folders MUST be in:**

```
./untracked/worktrees/<branch-name>/
```

✅ **Correct**: `./untracked/worktrees/worktree-plan-00028/`
❌ **Wrong**: `../plan-00028/`, `/tmp/worktree/`, etc.

**Why**:

- Keeps workspace organised
- Prevents git confusion
- Easy cleanup (just delete `untracked/worktrees/`)
- Excluded from main repo operations

### 2. Branch Naming

**Parent (Plan) Worktrees:**

- Prefix: `worktree-`
- Format: `worktree-<plan-name>`
- ✅ Examples: `worktree-plan-00028`, `worktree-handler-refactor`

**Child (Task) Worktrees:**

- Prefix: `worktree-child-`
- Format: `worktree-child-<parent-name>-<task-name>`
- ✅ Examples: `worktree-child-plan-00028-handler-1`, `worktree-child-plan-00028-config-fix`

❌ **Wrong**: `plan-00028`, `feature/headers`, `temp-work`, `child-handler-1`

**Why**:

- Clear identification of worktree hierarchy
- Easy filtering in `git branch` output
- Shows parent-child relationships
- Prevents accidental merges to main
- Signals temporary nature

### 3. Python Venv Setup (CRITICAL)

**Each worktree MUST have its own Python virtual environment.** The main
workspace venv has the package installed in editable mode pointing to
`/workspace/src/`. A worktree needs its own venv pointing to its own `src/`.

**Do not hand-roll it.** `setup_worktree.sh` creates the worktree AND its venv
in one step, using the fingerprint-keyed layout the resolver expects:

```bash
# Run from the PROJECT ROOT — creates the worktree and its venv together:
./scripts/setup_worktree.sh worktree-plan-00028
```

**Why not `python3 -m venv untracked/venv`**: that builds the retired
pre-v3.7.0 layout. Venvs have been fingerprint-keyed since v3.7.0
(`untracked/venv-{slug}-py{MM}-{fingerprint}/`), and `resolve_venv.sh` will not
accept a hand-made `untracked/venv/` — the wrapper exits 5 telling you to run
the installer.

**Why each worktree needs its own**:

- Editable installs (`pip install -e .`) point to a specific `src/` directory
- The main workspace venv imports from `/workspace/src/`, not the worktree's `src/`
- Using the wrong venv means your code changes won't be picked up

**You never name the interpreter.** Each worktree has its own
`./bin/hooks-daemon`, which anchors to its own location and resolves that
worktree's venv itself.

### 4. Daemon Process Isolation (CRITICAL)

**Each worktree gets its own daemon process with isolated socket/PID/log files.**

#### How It Works

The daemon CLI discovers the project root by walking up the directory tree to find `.claude/`. In a worktree, it finds the worktree's own `.claude/` directory (tracked by git), so the daemon naturally resolves paths relative to the worktree root:

```
Main workspace daemon:
  Socket: /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.sock
  PID:    /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.pid
  Log:    /workspace/.claude/hooks-daemon/untracked/daemon-{hostname}.log

Worktree daemon (isolated automatically):
  Socket: {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.sock
  PID:    {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.pid
  Log:    {worktree}/.claude/hooks-daemon/untracked/daemon-{hostname}.log
```

No collision occurs because each worktree has a different absolute path for `.claude/hooks-daemon/untracked/`.

#### Starting a Daemon in a Worktree

```bash
cd /workspace/untracked/worktrees/worktree-plan-00028

# Daemon automatically uses worktree's .claude/ for socket/PID
./bin/hooks-daemon start
./bin/hooks-daemon status
# Expected: Status: RUNNING (with worktree-local socket)
```

#### Explicit Path Overrides (Optional)

For additional control, use CLI flags or env vars to override automatic resolution.

**Path Resolution Precedence**: CLI flags > Environment variables > Auto-discovery

##### CLI Flags (Plan 00028)

The most explicit way to control daemon paths is with CLI flags:

```bash
cd /workspace/untracked/worktrees/worktree-plan-00028

# Start daemon with explicit paths
./bin/hooks-daemon \
  --pid-file .claude/hooks-daemon/untracked/daemon-wt.pid \
  --socket .claude/hooks-daemon/untracked/daemon-wt.sock \
  start

# All commands support these flags
./bin/hooks-daemon \
  --pid-file .claude/hooks-daemon/untracked/daemon-wt.pid \
  --socket .claude/hooks-daemon/untracked/daemon-wt.sock \
  status

./bin/hooks-daemon \
  --pid-file .claude/hooks-daemon/untracked/daemon-wt.pid \
  --socket .claude/hooks-daemon/untracked/daemon-wt.sock \
  stop
```

**Supported CLI Flags**:

- `--pid-file PATH`: Explicit PID file path (overrides env vars and auto-discovery)
- `--socket PATH`: Explicit socket path (overrides env vars and auto-discovery)

**When to use CLI flags**:

- Testing specific path configurations
- Debugging daemon isolation issues
- Temporary path overrides without modifying environment
- Scripted daemon management with custom paths

##### Environment Variables

Alternatively, use env vars to override automatic resolution:

```bash
# Force specific paths (usually not needed - automatic isolation works)
export CLAUDE_HOOKS_SOCKET_PATH={worktree}/.claude/hooks-daemon/untracked/daemon-wt.sock
export CLAUDE_HOOKS_PID_PATH={worktree}/.claude/hooks-daemon/untracked/daemon-wt.pid
export CLAUDE_HOOKS_LOG_PATH={worktree}/.claude/hooks-daemon/untracked/daemon-wt.log
```

**Note**: CLI flags take precedence over environment variables if both are specified.

#### Stopping a Worktree Daemon (MANDATORY Before Cleanup)

**You MUST stop the worktree's daemon before removing the worktree.** Failing to do this leaves orphaned processes with stale PID files and dangling sockets.

```bash
# ALWAYS stop daemon BEFORE removing worktree
cd /workspace/untracked/worktrees/worktree-plan-00028

# Method 1: Auto-discovery (works if cwd is worktree)
./bin/hooks-daemon stop

# Method 2: Explicit paths with CLI flags (works from any directory)
./bin/hooks-daemon \
  --pid-file /workspace/untracked/worktrees/worktree-plan-00028/.claude/hooks-daemon/untracked/daemon-*.pid \
  --socket /workspace/untracked/worktrees/worktree-plan-00028/.claude/hooks-daemon/untracked/daemon-*.sock \
  stop

# NOW safe to remove worktree
cd /workspace
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -d worktree-plan-00028
```

#### Orphaned Daemon Recovery

If a worktree was removed without stopping its daemon:

```bash
# Find orphaned daemon processes
ps aux | grep claude_code_hooks_daemon | grep -v grep

# Kill by PID (check it's the right process first)
kill <PID>

# Clean up stale socket if it exists
rm -f /path/to/.claude/hooks-daemon/untracked/daemon-*.sock
```

### 5. Agent Containment

**Agents working in worktrees MUST stay in their worktree**

When launching sub-agents for worktree tasks:

- Set working directory explicitly
- Verify agent is in correct worktree
- Never `cd` back to main workspace
- All file operations relative to worktree root
- Use the worktree's own `./bin/hooks-daemon`, not the main workspace's

**Example agent prompt:**

```
You are working in a git worktree at /workspace/untracked/worktrees/worktree-plan-00028/
DO NOT work in /workspace - only work in YOUR worktree directory.
All file paths should be relative to /workspace/untracked/worktrees/worktree-plan-00028/
Run the daemon CLI as ./bin/hooks-daemon from that worktree — it resolves that
worktree's own venv, so you never name an interpreter.
```

### 6. Merge Protocol

**Two types of merges with different rules:**

#### Child → Parent Worktree (ALLOWED)

✅ **Can merge automatically** - no human approval needed

```bash
# From parent worktree
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge worktree-child-plan-00028-handler-1
```

**Why allowed:**

- Isolated to plan worktree
- Doesn't affect main project
- Part of plan execution workflow
- Easy to rollback if needed

#### Parent → Main Project (REQUIRES APPROVAL)

❌ **MUST ask human approval first**

Before merging parent to main:

1. ✋ **STOP** - Ask human for approval
2. Verify no other agents working in main workspace
3. Verify no conflicts with main branch
4. Get explicit "yes" from human
5. Only then proceed with merge

**Why requires approval:**

- Multiple agents may be working simultaneously
- Main workspace might have uncommitted changes
- Conflicts need human resolution
- Risk of losing work

### 7. Cleanup Protocol

**On merge completion, daemon MUST be stopped, then worktree branches and folders cleaned up:**

```bash
# After child merges to parent:
# 1. Stop child's daemon
WT=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-1
$WT/bin/hooks-daemon stop 2>/dev/null || true

# 2. Remove worktree and branch
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-1
git branch -d worktree-child-plan-00028-handler-1

# After parent merges to main:
# 1. Stop parent's daemon
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop 2>/dev/null || true

# 2. Remove worktree and branch
cd /workspace
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -d worktree-plan-00028
```

**Why mandatory:**

- **Daemon stop prevents orphaned processes** with stale PID files and dangling sockets
- Prevents worktree clutter
- Reduces confusion about active work
- Frees disk space
- Keeps git branch list clean

## Standard Worktree Workflow

### Creating a Parent (Plan) Worktree

```bash
# 1. Ensure untracked/worktrees directory exists
mkdir -p untracked/worktrees

# 2. Create parent worktree from main branch (also builds its venv)
cd /workspace
./scripts/setup_worktree.sh worktree-plan-00028

# 3. Verify creation
cd /workspace
git worktree list
```

### Creating a Child (Task) Worktree

```bash
# 1. Create child from parent worktree branch (also builds its venv)
cd /workspace
./scripts/setup_worktree.sh worktree-child-plan-00028-handler-1 worktree-plan-00028

# 2. Verify it's based on parent
cd /workspace
git worktree list
```

**Note**: Child worktree is branched FROM the parent worktree branch, not from main.

### Working in a Worktree

```bash
# Navigate to worktree
cd /workspace/untracked/worktrees/worktree-plan-00028

# Work normally - commits, edits, tests
git status
# ... do your work ...

# Run QA within worktree
./scripts/qa/run_all.sh

# Verify daemon loads with your changes
./bin/hooks-daemon restart
./bin/hooks-daemon status

git add <specific-files>
git commit -m "Plan 00028: Implement handler"

# Return to main workspace
cd /workspace
```

### Merging Child → Parent Worktree

```bash
# From parent worktree directory
cd /workspace/untracked/worktrees/worktree-plan-00028

# 1. Review child changes
git log worktree-child-plan-00028-handler-1

# 2. Merge child into parent (no approval needed)
git merge worktree-child-plan-00028-handler-1

# 3. Stop child's daemon process
CHILD_WT=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-1
$CHILD_WT/bin/hooks-daemon stop 2>/dev/null || true

# 4. Immediately cleanup child
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-1
git branch -d worktree-child-plan-00028-handler-1
```

### Merging Parent → Main Project

**CRITICAL**: This is a multi-step process that requires careful verification at each stage.

⚠️ **MERGE ORDER IS CRITICAL** ⚠️
**ALWAYS merge main → worktree FIRST, then worktree → main**
**NEVER merge worktree → main directly!**

```bash
# ===================================================================
# STEP 1: ALWAYS MERGE MAIN INTO WORKTREE FIRST!
# ===================================================================
# This is THE MOST IMPORTANT STEP - sync worktree with main BEFORE merging back
# Prevents conflicts and ensures worktree has all latest changes from main
cd /workspace/untracked/worktrees/worktree-plan-00028
git fetch origin
git merge main --no-edit
# ⚠️ If there are conflicts, resolve them HERE in the worktree
# ⚠️ Test thoroughly after merge - the worktree must pass all QA
./scripts/qa/run_all.sh
./bin/hooks-daemon restart
./bin/hooks-daemon status
# Expected: Status: RUNNING

# STEP 2: Verify main workspace is clean
cd /workspace
git status  # MUST show "nothing to commit, working tree clean"

# ✋ STOP - If main workspace has uncommitted changes:
#   - Commit them first OR
#   - Stash them: git stash
#   - DO NOT proceed until main is clean

# STEP 3: ✋ STOP - Ask human for final approval!
# Confirm with human:
#   - Is main branch clean? (no uncommitted changes)
#   - Are all other agents/processes stopped?
#   - Is it safe to merge now?

# STEP 4: Review parent worktree changes
git log worktree-plan-00028 --oneline

# STEP 5: Merge parent to main (only after ALL approvals above!)
git merge worktree-plan-00028 --no-edit

# STEP 6: Verify merge succeeded
git status  # Should show clean state
./scripts/qa/run_all.sh  # Verify all QA still passes
./bin/hooks-daemon restart
./bin/hooks-daemon status
# Expected: Status: RUNNING

# STEP 7: Push to origin
git push

# STEP 8: Stop worktree daemon BEFORE removing worktree
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop 2>/dev/null || true

# STEP 9: ONLY NOW cleanup parent worktree
# (Not before merge push - we need it in case merge fails)
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -D worktree-plan-00028

# STEP 10: Final verification
git status  # Confirm everything clean
```

**Why this order matters:**

1. **ALWAYS sync worktree first** (`main → worktree`):
   - Prevents conflicts by updating worktree with main's latest changes
   - Lets you resolve conflicts IN THE WORKTREE (isolated, safe)
   - Ensures your changes work with the current state of main
   - **If you skip this, the merge WILL conflict and you WILL lose work**
2. **Clean main workspace**: Uncommitted changes in main cause merge failures
3. **Human verification**: Ensures no other work is in progress
4. **Keep worktree until success**: Don't delete until merge is confirmed working
5. **Cleanup last**: Only remove worktree after everything pushed successfully

**Remember**: The worktree is your isolated workspace. ALWAYS bring main's changes INTO your workspace BEFORE you merge your workspace back to main!

### Cleaning Up

Cleanup is **mandatory and immediate** after merging. **Always stop the daemon first.**

```bash
# After merging child to parent:
# 1. Stop daemon
CHILD_WT=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-1
$CHILD_WT/bin/hooks-daemon stop 2>/dev/null || true
# 2. Remove worktree and branch
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-1
git branch -d worktree-child-plan-00028-handler-1

# After merging parent to main:
# 1. Stop daemon
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop 2>/dev/null || true
# 2. Remove worktree and branch
cd /workspace
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -d worktree-plan-00028
```

**Never leave merged worktrees around** - cleanup prevents confusion, orphaned daemons, and keeps workspace tidy.

## Parallel Agent Strategy

### Hierarchical Approach: Plan 00028 (4 handlers in parallel)

**Step 1: Create Parent (Plan) Worktree**

```bash
# Main orchestrator creates the parent worktree (and its venv) for the plan
cd /workspace
./scripts/setup_worktree.sh worktree-plan-00028
```

**Step 2: Wave 1 - Create Handlers (4 child agents in parallel)**

```bash
# Create 4 child worktrees from parent — each with its own venv
cd /workspace
for wt in handler-a handler-b handler-c handler-d; do
  ./scripts/setup_worktree.sh "worktree-child-plan-00028-${wt}" worktree-plan-00028
done

# Launch 4 agents, each in their child worktree
Agent 1 → handler_a.py in worktree-child-plan-00028-handler-a
Agent 2 → handler_b.py in worktree-child-plan-00028-handler-b
Agent 3 → handler_c.py in worktree-child-plan-00028-handler-c
Agent 4 → handler_d.py in worktree-child-plan-00028-handler-d
```

**Step 3: Merge Children into Parent (sequential, in parent worktree)**

```bash
# From parent worktree, merge all children
cd /workspace/untracked/worktrees/worktree-plan-00028

# Merge child, stop its daemon, then cleanup
git merge worktree-child-plan-00028-handler-a
WT=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-a
$WT/bin/hooks-daemon stop 2>/dev/null || true
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-a
git branch -d worktree-child-plan-00028-handler-a

cd /workspace/untracked/worktrees/worktree-plan-00028
git merge worktree-child-plan-00028-handler-b
WT=/workspace/untracked/worktrees/worktree-child-plan-00028-handler-b
$WT/bin/hooks-daemon stop 2>/dev/null || true
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-handler-b
git branch -d worktree-child-plan-00028-handler-b

# ... repeat for other children
```

**Step 4: Run Full QA in Parent Worktree**

```bash
# From parent worktree - verify everything works together
cd /workspace/untracked/worktrees/worktree-plan-00028

./scripts/qa/run_all.sh
./bin/hooks-daemon restart
./bin/hooks-daemon status
# Expected: Status: RUNNING
```

**Step 5: Merge Parent into Main (REQUIRES APPROVAL)**

```bash
# ✋ STOP - Ask human for approval!
# STEP 1: Sync worktree with main first
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge main --no-edit
./scripts/qa/run_all.sh

# STEP 2: Merge to main (after human approval)
cd /workspace
git merge worktree-plan-00028
git push

# STEP 3: Stop daemon, then cleanup parent
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop 2>/dev/null || true
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -d worktree-plan-00028
```

### Benefits of Hierarchical Approach

1. **All plan work isolated**: Parent worktree contains entire plan
2. **Clean main workspace**: Main repo unaffected until final approval
3. **Easy rollback**: Can abandon entire plan without affecting main
4. **Parallel within plan**: Multiple agents work on tasks simultaneously
5. **Sequential integration**: Tasks merge to parent, then parent merges to main
6. **Clear hierarchy**: Easy to see which tasks belong to which plan

## Agent Team Integration

Worktrees are designed to work with Claude Code's **agent team mode** (`TeamCreate` / `SendMessage` / `Task` with `team_name`). The team lead orchestrates work from the main workspace while teammates operate in isolated worktrees.

**For complete agent team workflow, see @CLAUDE/AgentTeam.md** - includes team lead/agent responsibilities, lessons learned from Wave 1 POC, and copy-paste agent prompts.

### Architecture

```
Main Workspace (/workspace/) ← Team Lead (orchestrator)
    │
    ├── TeamCreate("plan-00028")
    │
    ├── worktree-plan-00028/ ← Integration worktree (merges happen here)
    │
    ├── worktree-child-plan-00028-handler-a/ ← Teammate "handler-a-dev"
    ├── worktree-child-plan-00028-handler-b/ ← Teammate "handler-b-dev"
    └── worktree-child-plan-00028-handler-c/ ← Teammate "handler-c-dev"
```

### Team Lead Workflow

The team lead operates from the **main workspace** and coordinates all worktree creation, merging, and cleanup.

**Phase 1: Setup**

1. Create the team:

   ```
   TeamCreate(team_name="plan-00028", description="Implement 3 new handlers")
   ```

2. Create tasks via `TaskCreate` for each piece of work

3. Create parent worktree + child worktrees (with venv setup for each)

4. Spawn teammates via `Task` tool, one per child worktree:

   ```
   Task(
     subagent_type="general-purpose",
     team_name="plan-00028",
     name="handler-a-dev",
     prompt="You are working in a git worktree at
       /workspace/untracked/worktrees/worktree-child-plan-00028-handler-a/
       DO NOT work in /workspace.
       Run the daemon CLI as ./bin/hooks-daemon from that worktree.
       Your task: Implement handler A. See TaskList for details.
       Run ./scripts/qa/run_all.sh before committing.
       Verify daemon loads: ./bin/hooks-daemon restart"
   )
   ```

**Phase 2: Monitor and Merge**

1. Teammates work autonomously, sending messages when done
2. As each teammate completes, merge their child into parent:
   - Stop child daemon
   - Merge child → parent worktree
   - Remove child worktree and branch
3. Send shutdown requests to completed teammates

**Phase 3: Integration and Cleanup**

1. Run full QA in parent worktree
2. Sync parent with main (`git merge main --no-edit`)
3. Ask human for merge approval
4. Merge parent → main
5. Stop parent daemon
6. Remove parent worktree
7. Shut down remaining teammates
8. `TeamDelete()` to clean up team resources

### Teammate Responsibilities

Each teammate MUST:

- **Stay in their worktree** - never `cd /workspace`
- **Use their own `./bin/hooks-daemon`** - it anchors to its own location, so
  the worktree's copy automatically uses the worktree-local venv
- **Run QA before committing** - `./scripts/qa/run_all.sh`
- **Verify daemon loads** - `./bin/hooks-daemon restart`
- **Communicate via `SendMessage`** - report completion, ask questions
- **Mark tasks complete** via `TaskUpdate` when done
- **Respond to shutdown requests** - approve via `SendMessage` with `type: "shutdown_response"`

### Shutdown Sequence (CRITICAL)

The shutdown order matters to avoid orphaned processes:

```
1. SendMessage(type="shutdown_request") to each teammate
   ↓ (wait for shutdown_response from each)
2. Stop each child worktree daemon
   $CHILD_WT/bin/hooks-daemon stop
   ↓
3. Merge children → parent (if not already done)
   ↓
4. Remove child worktrees and branches
   ↓
5. Run QA in parent, sync with main, merge (with approval)
   ↓
6. Stop parent worktree daemon
   ↓
7. Remove parent worktree and branch
   ↓
8. TeamDelete() to clean up team files
```

**If a teammate is unresponsive:**

```bash
# Find its daemon PID
cat {worktree}/.claude/hooks-daemon/untracked/daemon-*.pid

# Kill the daemon
kill <PID>

# Force-remove the worktree
cd /workspace
git worktree remove --force untracked/worktrees/worktree-child-plan-00028-stuck
git branch -D worktree-child-plan-00028-stuck
```

### Task Coordination

Teams share a task list. Map tasks to worktrees:

| Task                | Worktree                              | Teammate        |
| ------------------- | ------------------------------------- | --------------- |
| Implement handler A | `worktree-child-plan-00028-handler-a` | `handler-a-dev` |
| Implement handler B | `worktree-child-plan-00028-handler-b` | `handler-b-dev` |
| Integration testing | `worktree-plan-00028` (parent)        | Team lead       |
| Merge to main       | Main workspace                        | Team lead       |

### Avoiding Conflicts Between Teammates

- **Each teammate gets a separate worktree** - no shared files
- **Teammates should NOT modify the same files** - plan tasks to avoid overlap
- **If overlap is unavoidable**, merge children sequentially into parent and resolve conflicts there
- **Config files** (`.claude/hooks-daemon.yaml`): Only the team lead should modify shared config; teammates should not change it in their worktrees

## Automation Scripts

Two scripts automate the most error-prone worktree operations:

### `scripts/setup_worktree.sh` - Create Worktree with Venv

Automates: worktree creation, venv setup, editable install, verification.

```bash
# Create parent worktree from main:
./scripts/setup_worktree.sh worktree-plan-00028

# Create child worktree from parent:
./scripts/setup_worktree.sh worktree-child-plan-00028-handler-a worktree-plan-00028
```

**What it does:**

1. Validates branch name (must start with `worktree-`)
2. Creates git worktree in `untracked/worktrees/`
3. Creates Python venv at `untracked/venv/`
4. Installs package in editable mode (`pip install -e ".[dev]"`)
5. Verifies editable install points to worktree's own `src/`
6. Creates daemon untracked directory
7. Prints agent prompt template

### `scripts/validate_worktrees.sh` - QA Validation

Runs QA sequentially across all (or specific) worktrees.

```bash
# Validate all worktrees:
./scripts/validate_worktrees.sh

# Validate specific worktree:
./scripts/validate_worktrees.sh worktree-plan-00028
```

**What it does:**

1. Checks venv exists and editable install is correct
2. Runs `./scripts/qa/run_all.sh` from within each worktree
3. Reports pass/fail summary for all worktrees

## Concurrent QA Limitation (CRITICAL)

**QA runs in worktrees MUST be sequential, NOT parallel.**

Running `./scripts/qa/run_all.sh` in multiple worktrees simultaneously causes:

1. **Daemon socket collisions**: Integration tests (`test_daemon_smoke.py`) start/stop daemons that compete for socket paths, causing `FileNotFoundError` and `AssertionError: Daemon still running after stop`
2. **MyPy cache corruption**: Concurrent mypy processes writing to `.mypy_cache` causes type checker failures (`Library stubs not installed for "jsonschema"`)

**Correct approach**: Use `scripts/validate_worktrees.sh` which runs QA sequentially.

**When agents work in parallel**: Each agent runs QA in their OWN worktree. This is safe because:

- Each worktree has its own venv, daemon socket, and test isolation
- The daemon smoke tests use `/tmp/test-daemon-{unique-id}.sock` for test isolation
- Conflicts only occur when the same worktree's QA runs concurrently with another's

**Bottom line**: One QA run per worktree at a time. Multiple agents in DIFFERENT worktrees can run QA concurrently as long as the daemon smoke tests don't collide (which they shouldn't since they use unique temp paths).

## Common Pitfalls

### ❌ Working in Wrong Directory

```bash
# Agent creates handler in main workspace instead of worktree
cd /workspace  # WRONG
touch src/claude_code_hooks_daemon/handlers/pre_tool_use/new_handler.py  # WRONG LOCATION
```

✅ **Solution**: Always verify `pwd` before file operations

### ❌ Running the MAIN workspace's wrapper while working in a worktree

```bash
cd /workspace/untracked/worktrees/worktree-plan-00028
/workspace/bin/hooks-daemon restart  # WRONG — imports main src, not worktree src
```

The wrapper anchors to its OWN location, so an absolute path to `/workspace/bin/`
always resolves the MAIN venv no matter where you are.

✅ **Solution**: use the worktree's own wrapper — relative, from inside it:

```bash
cd /workspace/untracked/worktrees/worktree-plan-00028
./bin/hooks-daemon restart
```

### ❌ Creating a Worktree with Bare `git worktree add`

```bash
# No venv is created, so nothing can import the package
git worktree add untracked/worktrees/worktree-plan-00028 -b worktree-plan-00028
cd untracked/worktrees/worktree-plan-00028
pytest tests/  # ModuleNotFoundError!
```

✅ **Solution**: always create worktrees with `./scripts/setup_worktree.sh`,
which adds the worktree and builds its venv together.

### ❌ Branch Name Confusion

```bash
# Creating branch without worktree- prefix
git worktree add untracked/worktrees/plan-00028 -b plan-00028  # WRONG
```

✅ **Solution**: Always use `worktree-` prefix

### ❌ Merging Without Approval

```bash
# Agent automatically merges after completing task
git merge worktree-plan-00028  # WRONG - no human approval
```

✅ **Solution**: Always ask human before merging parent to main

### ❌ Skipping Daemon Restart Verification

```bash
# Merging without verifying daemon loads
cd /workspace
git merge worktree-plan-00028  # Merged code with import errors!
```

✅ **Solution**: Always verify daemon starts in worktree before merging:

```bash
./bin/hooks-daemon restart
./bin/hooks-daemon status
# Expected: Status: RUNNING
```

### ❌ Removing Worktree Without Stopping Daemon

```bash
# Removing worktree while daemon is still running
cd /workspace
git worktree remove untracked/worktrees/worktree-plan-00028  # Orphaned daemon process!
```

✅ **Solution**: Always stop daemon first:

```bash
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop
# THEN remove worktree
```

### ❌ Forgetting Cleanup

```bash
# Leaving old worktrees around
$ git worktree list
/workspace                              abc1234 [main]
/workspace/untracked/worktrees/old-1    def5678 [worktree-old-1]
/workspace/untracked/worktrees/old-2    ghi9012 [worktree-old-2]
```

✅ **Solution**: Clean up immediately after merging (stop daemon first)

## Benefits

1. **Parallel Work**: Multiple agents working simultaneously
2. **Isolation**: Changes don't interfere with each other
3. **Safety**: Main workspace remains stable
4. **Speed**: No branch switching overhead
5. **Clarity**: Clear separation of tasks

## When to Use Worktrees

✅ **Use worktrees for:**

- Multi-task plans with parallel phases
- Handler creation that can be done independently
- Refactoring multiple modules simultaneously
- Any work requiring 2+ parallel agents

❌ **Don't use worktrees for:**

- Single-file edits
- Quick fixes
- Sequential work where context matters
- Exploratory work (use main workspace)

## Directory Structure

```
/workspace/
├── .git/                                           # Main git directory
├── .claude/
│   ├── hooks-daemon.yaml                           # Config (tracked)
│   └── hooks-daemon/
│       └── untracked/
│           ├── daemon-{hostname}.sock              # Main workspace daemon socket
│           ├── daemon-{hostname}.pid               # Main workspace daemon PID
│           └── daemon-{hostname}.log               # Main workspace daemon log
├── untracked/                                      # Not tracked by git
│   ├── venv/                                       # Main workspace venv
│   └── worktrees/                                  # All worktrees here
│       ├── worktree-plan-00028/                    # Parent (Plan) worktree
│       │   ├── .claude/
│       │   │   └── hooks-daemon/
│       │   │       └── untracked/
│       │   │           ├── daemon-{hostname}.sock  # Worktree's own daemon socket
│       │   │           ├── daemon-{hostname}.pid   # Worktree's own daemon PID
│       │   │           └── daemon-{hostname}.log   # Worktree's own daemon log
│       │   ├── src/claude_code_hooks_daemon/
│       │   ├── tests/
│       │   ├── scripts/qa/
│       │   ├── untracked/venv/                     # Worktree's own venv
│       │   └── ... (full copy of repo)
│       ├── worktree-child-plan-00028-handler-a/    # Child (Task) worktree
│       │   ├── .claude/hooks-daemon/untracked/     # Child's own daemon files
│       │   ├── untracked/venv/                     # Child's own venv
│       │   └── ... (full copy, branched from parent)
│       └── worktree-child-plan-00028-handler-b/    # Child (Task) worktree
│           ├── .claude/hooks-daemon/untracked/     # Child's own daemon files
│           ├── untracked/venv/                     # Child's own venv
│           └── ... (full copy, branched from parent)
├── src/claude_code_hooks_daemon/                   # Main workspace source
├── tests/
├── scripts/qa/
└── ...
```

**Hierarchy:**

- Main project (`/workspace/`) ← Parent worktrees merge here (with approval)
- Parent worktrees (`worktree-plan-00028`) ← Child worktrees merge here (automatic)
- Child worktrees (`worktree-child-*`) ← Individual tasks worked on here

## Verification Checklist

### Before Creating Parent Worktree:

- [ ] Directory will be `untracked/worktrees/worktree-<plan-name>`
- [ ] Branch name starts with `worktree-` (not `worktree-child-`)
- [ ] Branching from main

### Before Creating Child Worktree:

- [ ] Directory will be `untracked/worktrees/worktree-child-<parent>-<task>`
- [ ] Branch name starts with `worktree-child-`
- [ ] Branch name includes parent plan name
- [ ] Branching from parent worktree branch (not main!)
- [ ] Agent knows to stay in their child worktree

### After Creating Any Worktree:

- [ ] Created via `./scripts/setup_worktree.sh <branch> [base]` (builds the
  fingerprint-keyed venv and installs the package editable in one step)
- [ ] `./bin/hooks-daemon` present in the worktree (it resolves that worktree's
  own venv automatically — no interpreter path to set)
- [ ] QA scripts work: `./scripts/qa/run_all.sh`

### Before Merging Child → Parent:

- [ ] Working in parent worktree directory
- [ ] Reviewed child changes
- [ ] No conflicts expected
- [ ] Child teammate has been shut down (if agent team mode)
- [ ] Ready to stop child daemon and cleanup immediately after merge

### Before Merging Parent → Main:

- [ ] ✋ **STEP 1**: ⚠️ **MERGED MAIN INTO WORKTREE FIRST** ⚠️ (`cd worktree && git merge main`)
- [ ] ✋ **STEP 2**: Resolved any conflicts in parent worktree (NOT in main!)
- [ ] ✋ **STEP 3**: Full QA passes in worktree (`./scripts/qa/run_all.sh`)
- [ ] ✋ **STEP 4**: Daemon restarts successfully in worktree (`./bin/hooks-daemon restart && status`)
- [ ] ✋ **STEP 5**: Verified main workspace is clean (`git status` shows clean)
- [ ] ✋ **STEP 6**: Committed or stashed any uncommitted changes in main workspace
- [ ] ✋ **STEP 7**: Asked human for final approval
- [ ] ✋ **STEP 8**: Got explicit "yes" from human
- [ ] ✋ **STEP 9**: Confirmed no other agents/processes working in main workspace
- [ ] ✋ **STEP 10**: Reviewed changes one last time (`git log worktree-plan-NNNNN --oneline`)

**REMINDER**: The merge order is ALWAYS: `main → worktree` FIRST, then `worktree → main`

### After Merging Child → Parent:

- [ ] Stopped child worktree daemon (`$CHILD_WT/.../daemon.cli stop`)
- [ ] Removed child worktree folder immediately
- [ ] Deleted child branch immediately
- [ ] Verified parent worktree still works

### After Merging Parent → Main:

- [ ] ✋ **STEP 11**: Verified merge succeeded (`git status` shows clean)
- [ ] ✋ **STEP 12**: Full QA passes (`./scripts/qa/run_all.sh`)
- [ ] ✋ **STEP 13**: Daemon restarts successfully (`./bin/hooks-daemon restart && status`)
- [ ] ✋ **STEP 14**: Pushed to origin successfully (`git push`)
- [ ] ✋ **STEP 15**: Stopped parent worktree daemon (`$WT/.../daemon.cli stop`)
- [ ] ✋ **STEP 16**: ONLY NOW remove parent worktree folder
- [ ] ✋ **STEP 17**: ONLY NOW delete parent branch
- [ ] ✋ **STEP 18**: Final verification (`git status` clean)
- [ ] ✋ **STEP 19**: Updated plan status to completed (see @CLAUDE/PlanWorkflow.md)
- [ ] ✋ **STEP 20**: If agent team mode, `TeamDelete()` to clean up team resources

**CRITICAL**: Never remove worktree/branch before merge is pushed successfully!

## Troubleshooting

### "Fatal: invalid reference: worktree-plan-00028"

**Cause**: Branch doesn't exist yet
**Solution**: Use `-b` flag when creating worktree

### "Lock file exists"

**Cause**: Previous worktree operation was interrupted
**Solution**: `git worktree prune` to clean up

### "Already exists"

**Cause**: Worktree folder wasn't properly removed
**Solution**: Manual cleanup:

```bash
rm -rf untracked/worktrees/worktree-plan-00028
git worktree prune
```

### "ModuleNotFoundError: No module named 'claude_code_hooks_daemon'"

**Cause**: The worktree has no venv, or has a hand-made `untracked/venv/` (the
retired pre-v3.7.0 layout, which `resolve_venv.sh` refuses).

**Solution**: recreate the worktree through the SSoT script, which builds a
fingerprint-keyed venv:

```bash
cd /workspace
git worktree remove untracked/worktrees/worktree-plan-00028
./scripts/setup_worktree.sh worktree-plan-00028
```

Then run the daemon CLI as `./bin/hooks-daemon` from inside the worktree — it
resolves that worktree's venv itself, so there is no interpreter to name.

### Orphaned Daemon After Worktree Removal

**Cause**: Worktree removed without stopping its daemon first
**Symptoms**: `ps aux | grep claude_code_hooks_daemon` shows process for deleted worktree
**Solution**:

```bash
# Find the PID from the stale PID file (if worktree still partially exists)
# Or find it from process list
ps aux | grep claude_code_hooks_daemon | grep -v grep

# Kill the orphaned process
kill <PID>

# Clean up any stale socket files
rm -f /path/to/.claude/hooks-daemon/untracked/daemon-*.sock
```

### Agent Working in Wrong Place

**Symptoms**: Files appearing in main workspace instead of worktree
**Solution**:

1. Stop agent immediately
2. Verify agent's working directory
3. Move files to correct worktree
4. Remind agent of worktree location

### Child Worktree Created from Main Instead of Parent

**Symptoms**: Child worktree doesn't have parent's changes
**Solution**:

1. Remove incorrect child worktree
2. Recreate child from parent branch:
   ```bash
   git worktree remove untracked/worktrees/worktree-child-plan-00028-task
   git branch -D worktree-child-plan-00028-task
   git worktree add untracked/worktrees/worktree-child-plan-00028-task \
     -b worktree-child-plan-00028-task worktree-plan-00028
   ```

### Trying to Merge Parent to Main Without Approval

**Symptoms**: Agent attempts `git merge worktree-plan-00028` from main workspace
**Solution**:

1. Stop immediately
2. Undo merge if it happened: `git merge --abort`
3. Ask human for approval
4. Only proceed after explicit "yes"

## Quick Reference

### Worktree Hierarchy

```
Main Project (/workspace/)
    ↑
    │ (merge with human approval)
    │
Parent Worktree (worktree-plan-00028)
    ↑
    │ (merge automatically)
    │
Child Worktrees (worktree-child-plan-00028-*)
```

### Key Rules Summary

| Action                 | Approval Required | Cleanup               |
| ---------------------- | ----------------- | --------------------- |
| Create parent worktree | No                | After merge to main   |
| Create child worktree  | No                | After merge to parent |
| Merge child → parent   | **NO**            | Immediate             |
| Merge parent → main    | **YES**           | Immediate             |

### Naming Cheat Sheet

```bash
# Parent (Plan) Worktree
worktree-plan-00028
worktree-handler-refactor

# Child (Task) Worktree - must include parent name!
worktree-child-plan-00028-handler-a
worktree-child-plan-00028-config-fix
worktree-child-handler-refactor-module-1
```

### Common Commands

```bash
# Create parent from main (worktree + venv in one step)
./scripts/setup_worktree.sh worktree-plan-00028

# Create child from parent
cd /workspace
git worktree add untracked/worktrees/worktree-child-plan-00028-task \
  -b worktree-child-plan-00028-task worktree-plan-00028

# Merge child to parent (in parent directory)
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge worktree-child-plan-00028-task

# Stop child daemon, then cleanup immediately
WT=/workspace/untracked/worktrees/worktree-child-plan-00028-task
$WT/bin/hooks-daemon stop 2>/dev/null || true
cd /workspace
git worktree remove untracked/worktrees/worktree-child-plan-00028-task
git branch -d worktree-child-plan-00028-task

# Merge parent to main (ASK HUMAN FIRST!)
# Step 1: Sync worktree with main
cd /workspace/untracked/worktrees/worktree-plan-00028
git merge main --no-edit
./scripts/qa/run_all.sh

# Step 2: Merge to main (after approval)
cd /workspace
git merge worktree-plan-00028

# Step 3: Stop daemon, then cleanup parent
WT=/workspace/untracked/worktrees/worktree-plan-00028
$WT/bin/hooks-daemon stop 2>/dev/null || true
git worktree remove untracked/worktrees/worktree-plan-00028
git branch -d worktree-plan-00028
```

## References

- Git worktree docs: `git help worktree`
- Main project docs: `/workspace/CLAUDE.md`
- Self-install mode: `CLAUDE/SELF_INSTALL.md`
- Plan workflow: `CLAUDE/PlanWorkflow.md`
- QA suite: `scripts/qa/run_all.sh`
- Code lifecycle: `CLAUDE/CodeLifecycle/General.md`
- **Agent team workflow**: `CLAUDE/AgentTeam.md` (team coordination, lessons learned, prompts)
- **Worktree setup**: `scripts/setup_worktree.sh` (automated creation + venv)
- **Worktree QA validation**: `scripts/validate_worktrees.sh` (sequential QA)

---

**Remember**:

- Worktrees are for **parallel execution** on complex plans
- **Parent worktrees** isolate entire plans from main project
- **Child worktrees** allow parallel work within a plan
- **Every worktree needs its own Python venv**
- **Every worktree gets its own daemon** (socket/PID/log isolated automatically)
- **Always stop daemon before removing worktree** (prevents orphaned processes)
- **Always verify daemon restarts** before merging
- **Always cleanup** immediately after merging
- **Always ask human** before merging parent to main
- **Agent teams**: Use `TeamCreate` → `Task` with `team_name` → `SendMessage` for coordination
