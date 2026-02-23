# Plan 00032: Sub-Agent Orchestration for Context Preservation

**Status**: On Hold (2026-02-23) - Waiting for upstream delegate mode fix
**Created**: 2026-02-06
**Owner**: Main Claude (Orchestrator)
**Priority**: High (blocked by upstream)

## Overview

Implement comprehensive sub-agent orchestration to preserve main thread context. Main Claude should orchestrate work through specialized sub-agents rather than executing tasks directly, preventing context pollution and enabling effectively infinite conversations through strategic delegation.

**Key Constraint**: Agents CANNOT spawn nested agents (per release-agent.md). Only the main Claude thread can spawn agents. This means orchestration must be centralized in main thread.

## Goals

1. **Create specialized sub-agents** for all workflow gates and orchestration tasks
2. **Enforce sub-agent usage** via PreToolUse handlers (prevent direct tool execution)
3. **Preserve main thread context** by delegating all heavy work to sub-agents
4. **Enable agent teams** to use sub-agents for their own workflow steps
5. **Document orchestration patterns** for future work

## Non-Goals

- Nested agent spawning (impossible - only main thread can spawn)
- Auto-compaction triggering from hooks (researched - not possible)
- Changing existing agent team workflows (preserve what works)

## Context & Background

**Research findings**:
1. Manual compaction via `/compact` is the only trigger mechanism
2. PreCompact hook can observe but NOT trigger compaction
3. Agents cannot spawn nested agents (architectural constraint)
4. Main thread must orchestrate all agent spawning

**Current state**:
- 5 custom agents exist (.claude/agents/)
- Agent teams work but no sub-agent usage by teammates
- Main thread often executes QA, setup, and other tasks directly
- Context accumulates rapidly during complex work

**Why this matters**:
- Complex plans consume 30-50% of context window
- QA output pollutes context with logs
- Worktree/venv setup is verbose
- Agent teams could delegate internal work but don't

## Tasks

### Phase 1: Research & Design (Agent Team Capabilities)

- [ ] ⬜ **Verify agent team sub-agent spawning capability**
  - [ ] ⬜ Review TeamCreate/SendMessage/Task tool documentation
  - [ ] ⬜ Check if teammates can use Task tool to spawn their own sub-agents
  - [ ] ⬜ Test: Spawn teammate, have it spawn sub-agent, observe behavior
  - [ ] ⬜ Document findings in plan notes

- [ ] ⬜ **Design orchestration patterns**
  - [ ] ⬜ Main thread orchestration pattern (definite)
  - [ ] ⬜ Agent team member sub-agent pattern (if possible)
  - [ ] ⬜ Context preservation strategies
  - [ ] ⬜ Create pattern documentation

### Phase 2: Create Orchestration Sub-Agents

#### 2.1: Worktree Management Agent

- [ ] ⬜ **Create worktree-manager.md agent**
  - [ ] ⬜ Model: haiku (fast, cost-effective for setup work)
  - [ ] ⬜ Tools: Bash, Read, Write, Glob
  - [ ] ⬜ Purpose: Create/delete worktrees, setup venvs, install deps
  - [ ] ⬜ Returns: Summary with paths, no verbose output

#### 2.2: Setup/Installation Agent

- [ ] ⬜ **Create setup-agent.md**
  - [ ] ⬜ Model: haiku (simple tasks)
  - [ ] ⬜ Tools: Bash, Read, Write
  - [ ] ⬜ Purpose: Venv creation, pip install, daemon setup
  - [ ] ⬜ Returns: Success/failure summary only

#### 2.3: Git Operations Agent

- [ ] ⬜ **Create git-agent.md**
  - [ ] ⬜ Model: haiku (straightforward git commands)
  - [ ] ⬜ Tools: Bash, Read
  - [ ] ⬜ Purpose: Git status, diff, log, branch operations (NOT commits/pushes)
  - [ ] ⬜ Returns: Summarized git state, not raw output

#### 2.4: Research/Exploration Agent (Enhanced)

- [ ] ⬜ **Review existing Explore agent type**
  - [ ] ⬜ Check if we need custom exploration agent
  - [ ] ⬜ Document when to use built-in Explore vs custom

### Phase 3: Enhance Existing Agents for Team Usage

#### 3.1: QA Runner Enhancement

- [ ] ⬜ **Update qa-runner.md for team context**
  - [ ] ⬜ Add guidance for agent team members to use it
  - [ ] ⬜ Document: "If you're on a team, use qa-runner sub-agent, not direct QA"
  - [ ] ⬜ Add output format optimized for teammate consumption

#### 3.2: Python Developer Enhancement

- [ ] ⬜ **Update python-developer.md**
  - [ ] ⬜ Add note: Use qa-runner sub-agent for QA checks
  - [ ] ⬜ Document sub-agent delegation pattern
  - [ ] ⬜ Add examples of spawning qa-runner when needed

#### 3.3: QA Fixer Enhancement

- [ ] ⬜ **Update qa-fixer.md**
  - [ ] ⬜ Add note: Should spawn qa-runner to verify fixes
  - [ ] ⬜ Document fix-verify cycle using sub-agents

### Phase 4: Create Enforcement Handlers

**Purpose**: Prevent main thread from executing heavy operations directly

#### 4.1: QA Execution Blocker

- [ ] ⬜ **Create PreToolUse handler: qa_script_blocker**
  - [ ] ⬜ Event: PreToolUse (Bash)
  - [ ] ⬜ Pattern: `./scripts/qa/run_*.sh`
  - [ ] ⬜ Action: Advisory (terminal=false)
  - [ ] ⬜ Message: "💡 Use qa-runner sub-agent to preserve context: Task(subagent_type='qa-runner', ...)"
  - [ ] ⬜ Priority: 58 (advisory)

#### 4.2: Worktree Setup Advisor

- [ ] ⬜ **Create PreToolUse handler: worktree_setup_advisor**
  - [ ] ⬜ Event: PreToolUse (Bash)
  - [ ] ⬜ Pattern: `git worktree add|python3 -m venv|pip install`
  - [ ] ⬜ Action: Advisory
  - [ ] ⬜ Message: "💡 Use worktree-manager sub-agent to preserve context"
  - [ ] ⬜ Priority: 58 (advisory)

#### 4.3: Heavy Git Operations Advisor

- [ ] ⬜ **Create PreToolUse handler: git_operations_advisor**
  - [ ] ⬜ Event: PreToolUse (Bash)
  - [ ] ⬜ Pattern: `git log|git diff --stat|git show`
  - [ ] ⬜ Action: Advisory (only for verbose operations)
  - [ ] ⬜ Message: "💡 Use git-agent sub-agent for verbose git operations"
  - [ ] ⬜ Priority: 58 (advisory)

### Phase 5: Documentation & Integration

#### 5.1: Orchestration Guide

- [ ] ⬜ **Create CLAUDE/SubAgentOrchestration.md**
  - [ ] ⬜ When to use sub-agents vs direct execution
  - [ ] ⬜ Main thread orchestration patterns
  - [ ] ⬜ Agent team sub-agent patterns (if supported)
  - [ ] ⬜ Context preservation strategies
  - [ ] ⬜ Examples for common scenarios

#### 5.2: Update Existing Documentation

- [ ] ⬜ **Update CLAUDE.md**
  - [ ] ⬜ Add section on sub-agent orchestration
  - [ ] ⬜ Reference SubAgentOrchestration.md
  - [ ] ⬜ Update "Using your tools" section

- [ ] ⬜ **Update CLAUDE/AgentTeam.md**
  - [ ] ⬜ Add sub-agent delegation guidance
  - [ ] ⬜ Document how team members should use sub-agents
  - [ ] ⬜ Add examples to each role (developer uses qa-runner, etc.)

- [ ] ⬜ **Update CLAUDE/PlanWorkflow.md**
  - [ ] ⬜ Add guidance on sub-agent orchestration during plans
  - [ ] ⬜ Update task templates with sub-agent patterns

#### 5.3: Update Agent Agents

- [ ] ⬜ **Update .claude/agents/README.md** (if exists, else create)
  - [ ] ⬜ List all agents with purposes
  - [ ] ⬜ Orchestration vs execution agents
  - [ ] ⬜ When to use which agent

### Phase 6: Testing & Validation

#### 6.1: Main Thread Orchestration Test

- [ ] ⬜ **Test main thread sub-agent spawning**
  - [ ] ⬜ Spawn worktree-manager for worktree creation
  - [ ] ⬜ Spawn qa-runner for QA execution
  - [ ] ⬜ Spawn git-agent for git operations
  - [ ] ⬜ Verify context preservation (token usage)
  - [ ] ⬜ Document token savings

#### 6.2: Agent Team Sub-Agent Test (If Supported)

- [ ] ⬜ **Test teammate sub-agent spawning**
  - [ ] ⬜ Create test team with TeamCreate
  - [ ] ⬜ Spawn teammate (python-developer)
  - [ ] ⬜ Have teammate spawn qa-runner sub-agent
  - [ ] ⬜ Observe if it works or errors
  - [ ] ⬜ Document findings

#### 6.3: Handler Testing

- [ ] ⬜ **Test enforcement handlers**
  - [ ] ⬜ Trigger qa_script_blocker (try to run QA directly)
  - [ ] ⬜ Trigger worktree_setup_advisor
  - [ ] ⬜ Trigger git_operations_advisor
  - [ ] ⬜ Verify advisory messages appear
  - [ ] ⬜ Verify terminal=false allows continuation

#### 6.4: Integration Test

- [ ] ⬜ **Real-world workflow test**
  - [ ] ⬜ Start new plan (small test plan)
  - [ ] ⬜ Use sub-agents for ALL heavy operations
  - [ ] ⬜ Compare token usage to traditional approach
  - [ ] ⬜ Document workflow and findings

### Phase 7: QA & Deployment

- [ ] ⬜ **Run full QA suite**
  - [ ] ⬜ Use qa-runner sub-agent: `Task(subagent_type='qa-runner', ...)`
  - [ ] ⬜ Fix any issues via qa-fixer
  - [ ] ⬜ Verify all checks pass

- [ ] ⬜ **Daemon restart verification**
  - [ ] ⬜ Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] ⬜ Verify: Status RUNNING
  - [ ] ⬜ Check logs for import errors

- [ ] ⬜ **Update plan status to Complete**
  - [ ] ⬜ Move plan to Completed/
  - [ ] ⬜ Update CLAUDE/Plan/README.md

## Technical Decisions

### Decision 1: Advisory vs Blocking Handlers

**Context**: Should handlers BLOCK direct tool execution or ADVISE?

**Options Considered**:
1. **Blocking (terminal=true)** - Force sub-agent usage, deny direct execution
2. **Advisory (terminal=false)** - Suggest sub-agent, allow override

**Decision**: Advisory (Option 2)

**Rationale**:
- Main Claude may need direct execution for debugging
- Allows gradual adoption
- Less disruptive to existing workflows
- Context awareness comes through practice, not force

**Date**: 2026-02-06

### Decision 2: Agent Model Selection

**Context**: Which model for each agent type?

**Decision**:
- **Worktree/Setup/Git agents**: haiku (fast, cheap, simple tasks)
- **QA agents**: haiku (execution) + sonnet (fixing)
- **Code reviewer**: opus (nuanced analysis)
- **Python developer**: sonnet (balanced capability)

**Rationale**: Match model cost/capability to task complexity

**Date**: 2026-02-06

### Decision 3: Agent Team Sub-Agent Support (TBD)

**Context**: Can agent team members spawn their own sub-agents?

**Investigation Required**:
- Test in Phase 1
- Document findings
- Update plan based on results

**Status**: Decision deferred until Phase 1 testing

## Agent Inventory (After This Plan)

### Orchestration Agents (Main Thread Uses These)
- **worktree-manager** (haiku) - Worktree/venv setup
- **setup-agent** (haiku) - Installation tasks
- **git-agent** (haiku) - Verbose git operations

### Workflow Agents (Existing)
- **qa-runner** (haiku) - QA execution
- **qa-fixer** (sonnet) - QA issue resolution
- **python-developer** (sonnet) - Development work
- **code-reviewer** (opus) - Expert review
- **release-agent** (sonnet) - Release preparation

### Built-in Agents (Claude Code)
- **Explore** - Codebase exploration
- **Plan** - Implementation planning
- **general-purpose** - General tasks

## Enforcement Handlers Inventory

### Advisory Handlers (New)
- **qa_script_blocker** (priority 58) - Advise using qa-runner sub-agent
- **worktree_setup_advisor** (priority 58) - Advise using worktree-manager
- **git_operations_advisor** (priority 58) - Advise using git-agent for verbose ops

## Success Criteria

- [ ] All orchestration agents created and tested
- [ ] Enforcement handlers prevent accidental context pollution
- [ ] Agent team sub-agent capability documented (works or doesn't)
- [ ] Documentation comprehensive and actionable
- [ ] Real-world test shows 30%+ context reduction
- [ ] All QA checks pass
- [ ] Daemon restarts successfully

## Dependencies

- None (standalone enhancement)

## Blocks

- None

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Agent teams can't spawn sub-agents | High | Medium | Document limitation, main thread orchestrates for teams |
| Advisory handlers ignored | Medium | High | Monitor usage, adjust messaging, consider metrics |
| Sub-agent overhead > savings | Medium | Low | Benchmark in Phase 6, adjust strategy if needed |
| Complex orchestration confusing | Medium | Medium | Comprehensive docs, clear examples |

## Notes & Updates

### 2026-02-06 - Plan Created

**Research Summary**:
- Compaction cannot be triggered from hooks (PreCompact is observe-only)
- Manual `/compact` is only trigger mechanism
- Agents cannot spawn nested agents (architectural constraint)
- Main thread must orchestrate all agent spawning
- Existing agents: qa-runner, python-developer, qa-fixer, code-reviewer, release-agent
- Agent teams work well but no evidence of sub-agent usage by teammates

**Open Questions**:
1. Can agent team members spawn sub-agents? (Test in Phase 1)
2. What token savings can we achieve? (Measure in Phase 6)
3. Should enforcement be advisory or blocking? (Decided: advisory)

**Next Steps**:
- ⏸️ PLAN ON HOLD - Waiting for upstream delegate mode fix
- Monitor GitHub issues: #23447, #25037, #14859, #7881
- When delegate mode is fixed, reassess scope (may need minimal daemon work)
- See RESEARCH-2026-02-23.md for full findings

### 2026-02-23 - Research Complete, Plan Put On Hold

**Research conducted by**: Main Claude (Opus 4.6) with Explore + general-purpose sub-agents

**Critical Findings**:

1. **PreToolUse/PostToolUse hooks have NO agent identification** - `session_id` is shared across main thread and all subagents. Our `OrchestratorOnlyHandler` (Plan 00019) cannot distinguish orchestrator from teammate. If enabled, it blocks everyone.

2. **Delegate mode is the upstream solution but is broken** - Claude Code has built-in delegate mode (Shift+Tab) that restricts the lead to coordination-only tools. However, it currently cascades to teammates, stripping them of file system tools too. Tracked in GitHub issues #23447, #24073, #24307, #25037.

3. **Plan mode is a partial workaround** - Task tool IS allowed in plan mode, but Bash is completely blocked (can't even run `git status`). Unknown if it also cascades.

4. **Agent hierarchy in hooks is requested but not implemented** - GitHub Issue #14859 requests `agent_id`, `parent_agent_id` on ALL hook events. If implemented, our handler approach would become viable.

**Decision**: Hold this plan. Delegate mode is exactly what we need and is a first-class platform feature. Building workarounds in the hooks daemon would be fragile, incomplete, and superseded once upstream fixes land.

**What to monitor**:
- [#23447](https://github.com/anthropics/claude-code/issues/23447) - Primary delegate mode cascade bug
- [#25037](https://github.com/anthropics/claude-code/issues/25037) - Latest duplicate with active discussion
- [#14859](https://github.com/anthropics/claude-code/issues/14859) - Agent hierarchy in hook events
- [#7881](https://github.com/anthropics/claude-code/issues/7881) - Subagent identification in hooks

**Full research document**: [RESEARCH-2026-02-23.md](RESEARCH-2026-02-23.md)
