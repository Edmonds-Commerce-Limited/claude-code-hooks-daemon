# Claude Code Planning Workflow

**Version 2.0** | Effective: January 2026

This document defines the standard planning workflow for all work on the Claude Code Hooks Daemon project. All developers and AI agents must follow this workflow to ensure efficient, trackable, and high-quality work.

---

## Core Principles

1. **Plan Before Execute** - Never start implementation without a documented plan
2. **Break Down Complexity** - Decompose large work into manageable tasks
3. **Track Everything** - Every task has a status and owner
4. **Document Decisions** - Capture rationale for major decisions
5. **Iterate Rapidly** - Plans are living documents, update as you learn
6. **Test First (TDD)** - Write failing tests before implementation
7. **Debug First** - Introspect hook events before writing handlers
8. **Orchestrate Intelligently** - Use sub-agents and teams for parallel execution when possible

---

## Execution Strategies

Plans should specify the recommended execution approach based on complexity and model capabilities.

### Strategy Selection Matrix

| Plan Complexity                                        | Recommended Model | Execution Strategy      | Rationale                                                |
| ------------------------------------------------------ | ----------------- | ----------------------- | -------------------------------------------------------- |
| **Simple** (single handler, straightforward logic)     | Sonnet 4.5        | Sub-Agent Orchestration | Sonnet delegates independent tasks to specialized agents |
| **Medium** (multiple handlers, some dependencies)      | Sonnet 4.5        | Sub-Agent Orchestration | Sonnet coordinates sequential phases with parallel tasks |
| **Complex** (architectural changes, many dependencies) | Opus 4.6          | Sub-Agent Teams         | Opus manages team of agents with task coordination       |
| **Critical** (releases, major refactors)               | Opus 4.6          | Sub-Agent Teams         | Opus provides strategic oversight and decision-making    |

**Haiku 4.5 CANNOT orchestrate plans.** Only Opus and Sonnet are valid executors.

### Execution Strategy Definitions

**1. Single-Threaded**

- Main agent (Sonnet or Opus) executes all work directly
- No delegation to sub-agents
- Use for: Quick fixes, documentation updates, simple changes

**2. Sub-Agent Orchestration** (Sonnet preferred)

- Main agent (Sonnet) spawns specialized sub-agents for independent tasks
- Main agent coordinates but doesn't micromanage
- Sub-agents work in parallel when possible
- Use for: Multi-phase work, parallel test execution, independent modules
- Example: Main Sonnet spawns Explore agent for codebase research, then spawns python-developer for implementation

**3. Sub-Agent Teams** (Opus preferred)

- Main agent (Opus) creates team with task list
- Team members claim tasks autonomously
- Main agent provides strategic guidance and reviews
- Use for: Large-scale refactors, coordinated multi-file changes, releases
- Example: Opus creates team with researcher, developer, tester agents; each claims tasks from shared task list

### Model-Specific Guidance

**When executing as Sonnet 4.5:**

- Default to Sub-Agent Orchestration for multi-phase plans
- Spawn agents for independent tasks (Explore for research, python-developer for TDD implementation)
- Use multiple parallel agents when tasks are independent
- Keep main thread for coordination and decision-making

**When executing as Opus 4.6:**

- Default to Sub-Agent Teams for complex plans
- Create team structure with clear roles
- Use shared task list for coordination
- Provide strategic oversight and architectural decisions
- Review sub-agent output for quality and consistency

**Haiku 4.5:**

- CANNOT orchestrate plans
- Use only for: utility scripts, basic file operations, team support roles

### Choosing Recommended Executor

Plans specify **Recommended Executor** in the header:

```markdown
**Recommended Executor**: Opus | Sonnet
```

**Guidelines**:

- **Opus**: Architectural changes, releases, critical refactors, complex coordination
- **Sonnet**: Feature work, handler implementations, bug fixes, standard complexity

**Minimum**: Sonnet 4.5. Haiku cannot orchestrate plans.

---

## Plan Structure

### Directory Layout

```
CLAUDE/
└── Plan/
    ├── 00001-handler-implementation/
    │   ├── PLAN.md                      # Main plan document
    │   ├── {supporting-docs*}.md        # Supporting analysis docs
    │   └── assets/                      # Diagrams, logs, etc.
    ├── 00002-config-refactoring/
    │   ├── PLAN.md
    │   └── config-analysis.md
    ├── 00003-qa-improvements/
    │   ├── PLAN.md
    │   └── coverage-report.md
    ├── 00307-subagent-file-based-report-handoff/
    │   ├── PLAN.md
    │   ├── JOURNAL/
    │   └── subagent-reports/            # Dispatched subagents' file-handoff reports
    │       └── {yymmdd}-{agent-name}-{model}.md
    └── README.md                        # Index of all plans
```

### Subagent report handoff (`subagent-reports/`)

Plan 00307: a subagent dispatched to work on THIS plan writes any long-form
report — findings, exploration notes, review output — to a file under this
plan folder's `subagent-reports/` subdirectory, never inline as its final
message. The standard filename is `{yymmdd}-{agent-name}-{model}.md` (e.g.
`260901-explore-hook-surfaces-fable.md`). The subagent's final message stays
a short completion summary plus the file path.

Rationale: a subagent's return travels over a bounded-size wire channel. Task
1.1's reproduction (`CLAUDE/Plan/00307-subagent-file-based-report-handoff/`)
found the harness silently eliding the MIDDLE of an oversized inline report
while both start/end sentinels survived intact — a coordinator can receive
what looks like a complete report while content is missing. The
`dispatch_declaration` handler (PreToolUse on the `Task` tool) injects this
contract at dispatch time when a prompt does not already declare it; the
`subagent_report_size_blocker` handler (SubagentStop) blocks an oversized
final message until it is re-routed through a file. Work that is NOT plan
work should instead declare an explicit destination (falling back to
`untracked/agent-reports/` when none is given).

`subagent-reports/` is a recognised plan-folder member for plan QA purposes —
its presence never triggers a stray-file or unexpected-content finding.

### Plan Numbering

- Plans are numbered sequentially with 5-digit zero-padding: `00001-`, `00002-`, `00003-`, etc. (`NNNNN` in templates)
- Use kebab-case for plan folder names
- Plan numbers never change even if plan is cancelled

---

## Plan Document Structure

Every `PLAN.md` must follow this structure:

```markdown
# Plan NNNNN: [Plan Title]

**Status**: In Progress | Complete | Blocked | Cancelled
**Created**: YYYY-MM-DD
**Owner**: [Name/Agent]
**Priority**: High | Medium | Low
**Recommended Executor**: Opus | Sonnet | Haiku
**Execution Strategy**: Sub-Agent Orchestration | Sub-Agent Teams | Single-Threaded

## Overview

[2-3 paragraphs describing what this plan aims to achieve and why]

## Goals

- Clear, measurable goal 1
- Clear, measurable goal 2
- Clear, measurable goal 3

## Non-Goals

- Explicitly what this plan will NOT do
- Helps scope creep management

## Context & Background

[Summary relevant background, previous decisions, or context needed]
Refer to detailed info in supporting docs as required

## Tasks

### Phase 1: [Phase Name]

- [ ] **Task 1.1**: Description of task
  - [ ] Subtask 1.1.1: More specific work
  - [ ] Subtask 1.1.2: More specific work
- [ ] **Task 1.2**: Description of task

### Phase 2: [Phase Name]

- [ ] **Task 2.1**: Description of task
- [ ] **Task 2.2**: Description of task

## Dependencies

- Depends on: Plan 00001 (Complete)
- Blocks: Plan 00003 (Not Started)
- Related: Plan 00002

## Technical Decisions

### Decision 1: [Title]
**Context**: Why this decision is needed
**Options Considered**:
1. Option A - pros/cons
2. Option B - pros/cons

**Decision**: We chose Option A because [rationale]
**Date**: YYYY-MM-DD

## Success Criteria

- [ ] Criterion 1 that must be met
- [ ] Criterion 2 that must be met
- [ ] All QA checks passing

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Risk description | High/Med/Low | High/Med/Low | How we'll handle it |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes (git is the SSoT for "when").
     The blow-by-blow activity log lives in JOURNAL/ — see CLAUDE/PlanJournalling.md. -->

- Milestone reached at <commit-hash>
```

---

## Task Status System

### Status Icons

Use these Unicode icons for task status:

| Status           | Icon | Markdown | Meaning                           |
| ---------------- | ---- | -------- | --------------------------------- |
| **Not Started**  | ⬜   | `⬜`     | Task not yet begun                |
| **In Progress**  | 🔄   | `🔄`     | Currently being worked on         |
| **Completed**    | ✅   | `✅`     | Task finished and verified        |
| **Blocked**      | 🚫   | `🚫`     | Cannot proceed (dependency/issue) |
| **Cancelled**    | ❌   | `❌`     | Task no longer needed             |
| **On Hold**      | ⏸️   | `⏸️`     | Paused temporarily                |
| **Needs Review** | 👁️   | `👁️`     | Work done, awaiting review        |

### Task Formatting

```markdown
- [ ] ⬜ **Task Title**: Clear description of what needs to be done
  - [ ] ⬜ Subtask 1: Specific action
  - [ ] 🔄 Subtask 2: Another action (currently working)
  - [ ] ✅ Subtask 3: Already completed
```

### Rules for Status Updates

1. **One Task In Progress** - Limit to 1-2 tasks marked 🔄 at a time
2. **Update Immediately** - Change status as soon as state changes
3. **Document Blocks** - If marking 🚫, add note explaining why
4. **Verify Completion** - Only mark ✅ after testing/verification and QA passing

---

## QA Integration (Python Project)

**CRITICAL: Before completing ANY task, all QA checks must pass.**

### Required QA Verification

Run the complete QA suite before marking any task complete:

```bash
# Run ALL QA checks (REQUIRED before commits)
./scripts/qa/llm_qa.py all
```

### What Gets Checked

`scripts/qa/run_all.sh` is the single source of truth for which checks exist —
do not trust any written enumeration of them (this section previously carried a
five-row table that had drifted, including a security requirement weaker than
the real zero-findings-at-all-severities policy). Full QA policy:
[CLAUDE/QA.md](QA.md).

### QA Task Format

Always include QA verification as a subtask:

```markdown
- [ ] ⬜ **Implement feature X**
  - [ ] ⬜ Write implementation
  - [ ] ⬜ Run QA: `./scripts/qa/llm_qa.py all`
  - [ ] ⬜ Fix any issues
  - [ ] ⬜ Verify all checks pass
```

### Individual QA Commands

```bash
# Individual checks (auto-fix enabled by default)
./scripts/qa/run_lint.sh          # Ruff linter
./scripts/qa/run_format_check.sh  # Black formatter
./scripts/qa/run_type_check.sh    # MyPy type checker
./scripts/qa/run_tests.sh         # Pytest with coverage

# Manual auto-fix
./scripts/qa/run_autofix.sh       # Runs Black + Ruff --fix
```

---

## Plan QA (automated enforcement)

The daemon enforces plan-tree hygiene automatically. Most plan rot is
cross-file (PLAN.md status ↔ folder location ↔ README row ↔ git state), so
enforcement runs in three stages that share one check catalogue.

**Stage 1 — edit-time lint** (`plan_qa_edit`, PreToolUse): every Write/Edit of
a `PLAN.md` is linted against single-file rules on the content the file *would*
have. New material with a missing/invalid `**Status**:` line, a header that
contradicts an all-ticked body, or ad-hoc task markers is **blocked** with the
exact fix (mode `edit_mode`, default `block`). The plan-index `README.md` is
linted too, against one rule — `index-row-length`: keep every line under 500
characters, because a row is a pointer (link, status, one clause), not a
summary copied from the linked plan.

**Stage 2 — commit gate** (`plan_qa_commit_gate`, PreToolUse on `git commit`):
checks the **staged** tree against cross-file invariants -- index-at-birth (a
new plan folder stages its README row in the same commit), terminal-state
atomicity (a status flip to a terminal state ships the `git mv` into the
archive dir plus the README row and statistics recount in ONE commit), number
collisions, and row/folder bijection. Ships **warn-first** (mode
`commit_gate_mode`, default `warn`); read the advisory findings and amend the
commit before it lands.

**Stage 3 — session sweep** (`plan_qa_sweep`, SessionStart): reports whole-tree
drift once per new session as advisory context; never blocks (mode
`sweep_mode`, default `advise`).

### Allowed status tokens

`Not Started`, `In Progress`, `Complete`, `Blocked`, `Cancelled`,
`Superseded`, `Dormant`. Any **terminal** status (Complete, Cancelled,
Superseded) requires the plan folder to move into the archive directory
(`Completed/`, or `Cancelled/` where configured) in the **same commit** that
sets the status -- alongside the README index row update and statistics
recount.

### CLI

```bash
./bin/hooks-daemon plan-qa --sweep          # whole tree; exit 1 on findings (CI-able)
./bin/hooks-daemon plan-qa --check-staged   # staged-tree commit-gate checks
./bin/hooks-daemon plan-qa --lint <PLAN.md> # single-file edit-stage checks
```

Add `--json` to any of these for machine-readable output.

### Policy & grandfathering

All policy lives in `.claude/hooks-daemon.yaml` under `plan_workflow.qa` (one
block shared by all three surfaces and the CLI -- see
`docs/guides/HANDLER_REFERENCE.md`). Legacy plans predating these rules are
held to advise-only via `legacy_plan_allowlist` (plan numbers), and historic
duplicate numbers are tolerated via `collision_allowlist`.

### Truth is enforced on LIVE plans, never on the historical record

Plan QA keeps **active** plans grounded in current truth. It does **not** try to
keep the archive matching today's tree, and no one should.

- **A live plan must state present truth.** It is read in full at the start of
  every session that touches it, so a task citing a path, command or option
  that has since moved actively misleads the next reader. If a live plan's
  current task text has gone stale, **fix it** — that is squarely in scope.
- **An archived plan is a RECORD of what was true when it was written.**
  Completed, Cancelled and Superseded plans are not maintained against the
  present. Editing one so it matches today's tree does not make it more
  accurate; it **falsifies the record** of what the work actually faced.
- **The same applies to a dated historical block inside a live plan** — an
  "assumed defaults (from the audit)" list, an incident write-up, a findings
  table stamped with a date. That block is a record of a moment, not a claim
  about now, and it stays as written.

**Consequence for `path-existence`.** The check cannot tell a live reference
from historical prose, so it will flag backticked `src/...` paths in both. On
an archived plan, or inside a dated block, that finding is **expected noise —
leave the prose alone**. And never un-backtick a path to silence it: that
games the check without changing anything a reader sees. Only a stale path in
a live plan's current text is a real finding.

---

## TDD Integration

This project enforces Test-Driven Development. All implementation work must follow the Red-Green-Refactor cycle.

### TDD Workflow

1. **Red**: Write a failing test that defines the expected behaviour
2. **Green**: Write the minimum code to make the test pass
3. **Refactor**: Clean up the code while keeping tests green
4. **Verify**: Run full QA suite

### TDD Task Format

```markdown
- [ ] ⬜ **Implement handler for X**
  - [ ] ⬜ Write failing test for matches() behavior
  - [ ] ⬜ Implement matches() to pass test
  - [ ] ⬜ Write failing test for handle() behavior
  - [ ] ⬜ Implement handle() to pass test
  - [ ] ⬜ Refactor for clarity
  - [ ] ⬜ Verify 95%+ coverage maintained
  - [ ] ⬜ Run full QA suite
```

### Coverage Requirement

- Minimum 95% test coverage is required
- New code must have corresponding tests
- Coverage reports in `untracked/qa/coverage.json`

### Running Tests

```bash
# Run all tests with coverage
./scripts/qa/run_tests.sh

# Run specific test file
pytest tests/handlers/pre_tool_use/test_my_handler.py -v

# Run with coverage report
pytest --cov=src --cov-report=html
```

---

## Planning Workflow Steps

### Step 1: Identify Work

When new work is identified:

1. Check if it fits in an existing plan
2. If not, determine if a new plan is needed
3. For small tasks (< 1 hour), use TodoWrite instead

**New Plan Threshold**: If work will take > 2 hours or involves multiple phases

### Step 2: Create Plan

1. Create new folder: `CLAUDE/Plan/NNNNN-descriptive-name/`
2. Copy plan template to `PLAN.md`
3. Fill in overview, goals, and initial task breakdown
4. Update `CLAUDE/Plan/README.md` with plan entry

### Step 3: Break Down Tasks

1. Decompose work into phases (if needed)
2. Break each phase into concrete tasks
3. Break tasks into subtasks if task > 30 minutes
4. Ensure tasks are actionable and testable
5. **Include TDD subtasks for implementation work**
6. **Include QA verification subtasks**

**Good Task**: "Create PreToolUse handler to block destructive sed commands with 95% coverage"
**Bad Task**: "Work on handlers"

### Step 4: Review & Approve

1. Review plan completeness
2. Verify tasks are well-defined
3. Check for missing dependencies
4. Get stakeholder approval (if needed)

### Step 5: Execute

1. Mark plan status as 🔄 In Progress
2. Work through tasks sequentially
3. **Follow TDD cycle for implementation**
4. Update task status in real-time
5. Document any blockers or changes
6. **Run QA before each commit**
7. Commit work with reference to plan: `Plan 00001: Implement destructive git handler`

### Failsafe Recovery Cron (while executing)

For long, multi-hour plan executions, set up a **non-durable hourly failsafe
recovery cron** at the start of execution (the `recovery_cron_advisor` handler
prompts this on plan creation/progress when enabled). It is a safety net that
resumes work stalled by **external** factors — Claude API overload, rate limits,
5-hour usage limits, network failures — by firing only while the REPL is idle.

**This is NOT a heartbeat.** You must **never** pace yourself to the cron or wait
for it between units of work — that is an own goal that turns a recovery net into
an artificial throttle. Work proceeds at full speed until an external factor
actually stops you; the cron only matters once something has already gone wrong.

- Create it non-durable (`CronCreate` `durable:false`, `recurring:true`, an
  off-:00 minute) and record the cron ID in the plan's JOURNAL (the activity
  log; the `Delivery & Milestones` stub is for milestones + commit hashes).
- If you are blocked **only** on human input, the cron is a no-op — keep waiting.
- On plan completion, **do not reflexively delete the cron** — deleting it while
  the session is still live leaves you with no recovery coverage if a rate limit
  or usage limit hits next. Keep it whenever further work may happen this session
  (it is non-durable and dies automatically on session exit, and is a no-op when
  nothing is resumable). Run `CronDelete` only once you are certain the session is
  finished with no further work.

### Step 6: Complete

1. **Verify all QA checks pass**
2. Verify all success criteria met
3. Mark all tasks as ✅
4. Mark plan status as Complete
5. Record the delivery commit hash(es) in the plan's "Delivery & Milestones"
   section (NOT a completion date — git is the source of truth for "when")
6. Document any lessons learned
7. **Follow the Plan Completion Checklist below**

### Plan Completion Checklist

When a plan is complete, follow these steps to properly close it out. Skipping steps leads to stale plan indexes and orphaned folders.

1. **Update PLAN.md status**: Change `**Status**:` to `Complete`. Do NOT add a completion date — git history is authoritative for "when". Cite the delivery commit hash(es) in the "Delivery & Milestones" section instead.
2. **Mark all tasks**: Change `- [ ]` to `- [x]` for all completed tasks in the plan
3. **Move to Completed folder**: Relocate the plan directory into the archive
   ```bash
   git mv CLAUDE/Plan/NNNNN-description CLAUDE/Plan/Completed/NNNNN-description
   ```
4. **Update README.md**: Edit `CLAUDE/Plan/README.md` with all of the following changes:
   - Remove the plan entry from the "Active Plans" section
   - Add the plan to the "Completed Plans" section with a brief summary
   - Update plan statistics (Total, Active count, Completed count, Success Rate)
5. **Unblock dependent plans**: Check if any other plans had `Blocked by: Plan NNNNN` referencing this plan and remove that blocker so dependent work can proceed
6. **Commit**: Include all plan-related file changes (PLAN.md, README.md, directory move) in a single commit using the message format:
   ```
   Plan NNNNN: Complete - Brief description
   ```

**Why a single commit?** Atomic plan closure ensures the plan index, archive, and status are always consistent. Splitting across commits risks partial updates if work is interrupted.

---

## Using TodoWrite vs Plans

### Use TodoWrite For:

- Very small tasks and LOW RISK tasks
- Single-session work
- No major architectural decisions
- Temporary tracking during active work

### Use Plans For:

- Medium sized+ work
- Any risk
- Work with multiple phases
- Architectural or design decisions
- Work that may need to be resumed later
- Work that others need to understand

### Converting TodoWrite to Plan

If TodoWrite list grows beyond 5 items or becomes multi-session:

1. Create proper plan
2. Migrate tasks to plan
3. Clear TodoWrite
4. Reference plan in work

---

## Plan Templates

### Handler Implementation Plan Template

Use this template when creating new handlers for hook events.

````markdown
# Plan NNNNN: [Handler Name] Handler

**Status**: Not Started
**Type**: Handler Implementation
**Event Type**: PreToolUse | PostToolUse | SessionStart | etc.
**Priority Range**: [pick a band from the Priority Guide: CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide]

## Overview

[What handler, why needed, what behavior it enforces]

## Goals

- Intercept [specific event/pattern]
- Enforce [specific behavior]
- Maintain 95%+ test coverage

## Non-Goals

- [What this handler does NOT do]

## Debug Analysis

**Before implementation**, capture event flow:
```bash
./scripts/debug_hooks.sh start "Testing [scenario]"
# ... perform actions in Claude Code ...
./scripts/debug_hooks.sh stop
````

**Event Analysis**:

- Event Type: [PreToolUse, etc.]
- Tool Name: [Write, Bash, etc.]
- Key hook_input fields: [list relevant fields]
- Trigger Pattern: [what triggers this handler]

## Tasks

### Phase 1: Debug & Design

- [ ] ⬜ Run debug script for target scenario
- [ ] ⬜ Analyze captured events and data
- [ ] ⬜ Document event type and patterns
- [ ] ⬜ Design handler matching logic
- [ ] ⬜ Determine priority and terminal behavior

### Phase 2: TDD Implementation

- [ ] ⬜ Create test file: `tests/handlers/{event_type}/test_{handler_name}.py`
- [ ] ⬜ Write failing test for matches() - positive case
- [ ] ⬜ Write failing test for matches() - negative cases
- [ ] ⬜ Implement matches() to pass tests
- [ ] ⬜ Write failing test for handle() - expected result
- [ ] ⬜ Write failing test for handle() - edge cases
- [ ] ⬜ Implement handle() to pass tests
- [ ] ⬜ Refactor and clean up

### Phase 3: Integration

- [ ] ⬜ Register handler in config
- [ ] ⬜ Update handler count in CLAUDE.md
- [ ] ⬜ Run full QA suite: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ Test with live Claude Code session
- [ ] ⬜ Update documentation

## Handler Specification

```python
class [HandlerName]Handler([Event]HandlerBase):
    def __init__(self) -> None:
        super().__init__(
            name="[handler-name]",
            priority=[XX],
            terminal=[True/False]
        )

    def matches(self, hook_input: dict) -> bool:
        # Pattern matching logic
        pass

    def handle(self, hook_input: dict) -> [Event]Result:
        # Handler behaviour
        pass
```

The base and result type are chosen by the event: `PreToolUseHandlerBase`/`GatingResult`, `PostToolUseHandlerBase`/`BlockingResult`, or `<Event>HandlerBase`/`AdvisoryResult` for everything else.

## Success Criteria

- [ ] Handler correctly intercepts target events
- [ ] All tests passing
- [ ] 95%+ coverage maintained
- [ ] Live testing successful in Claude Code
- [ ] Documentation updated
- [ ] All QA checks pass

````

### Feature Implementation Plan Template

```markdown
# Plan NNNNN: [Feature Name]

**Status**: Not Started
**Type**: Feature Implementation

## Overview

[What feature, why needed]

## Tasks

### Phase 1: Design
- [ ] ⬜ Analyze requirements
- [ ] ⬜ Design solution architecture
- [ ] ⬜ Document technical decisions

### Phase 2: TDD Implementation
- [ ] ⬜ Write failing tests for core functionality
- [ ] ⬜ Implement core functionality
- [ ] ⬜ Write tests for edge cases
- [ ] ⬜ Implement edge case handling
- [ ] ⬜ Refactor for clarity

### Phase 3: Integration & QA
- [ ] ⬜ Integrate with existing code
- [ ] ⬜ Run full QA: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ Fix any QA issues
- [ ] ⬜ Update documentation

## Success Criteria

- [ ] Feature works as specified
- [ ] All tests passing with 95%+ coverage
- [ ] All QA checks pass
- [ ] Documentation updated
````

### Bug Fix Plan Template

```markdown
# Plan NNNNN: Fix [Bug Description]

**Status**: Not Started
**Type**: Bug Fix
**Severity**: Critical | High | Medium | Low

## Bug Description

[What's broken, how to reproduce]

## Tasks

- [ ] ⬜ Reproduce bug locally
- [ ] ⬜ **Write failing test that demonstrates the bug**
- [ ] ⬜ Identify root cause
- [ ] ⬜ Implement fix (make test pass)
- [ ] ⬜ Add additional regression tests
- [ ] ⬜ Run full QA: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ Verify fix works in live testing

## Success Criteria

- [ ] Bug no longer reproducible
- [ ] Failing test now passes
- [ ] No regression in other tests
- [ ] All QA checks pass
```

### Refactoring Plan Template

Use this template when improving existing code without changing behaviour.

```markdown
# Plan NNNNN: Refactor [Component/Area]

**Status**: Not Started
**Type**: Refactoring

## Overview

[What needs refactoring, why it improves the codebase]

## Goals

- Improve [readability/maintainability/performance]
- Maintain existing behavior
- Maintain or improve test coverage

## Non-Goals

- No new features
- No behavior changes

## Tasks

### Phase 1: Preparation
- [ ] ⬜ Identify all affected code
- [ ] ⬜ Ensure adequate test coverage exists
- [ ] ⬜ Document current behavior

### Phase 2: Refactoring
- [ ] ⬜ Apply refactoring incrementally
- [ ] ⬜ Run tests after each change
- [ ] ⬜ Verify no behavior changes

### Phase 3: Verification
- [ ] ⬜ Run full QA: `./scripts/qa/llm_qa.py all`
- [ ] ⬜ Compare before/after behavior
- [ ] ⬜ Update documentation if needed

## Success Criteria

- [ ] All existing tests pass
- [ ] Coverage maintained at 95%+
- [ ] No behavior changes
- [ ] All QA checks pass
- [ ] Code is cleaner/more maintainable
```

---

## Best Practices

### Task Writing

✅ **Good Tasks**:

- "Create PreToolUse handler to block force push to main/master"
- "Add terminal flag to npm audit handler with priority 45"
- "Fix MyPy type error in FrontController.dispatch method"
- "Increase test coverage for daemon/server.py to 95%"

❌ **Bad Tasks**:

- "Fix the daemon"
- "Make it work better"
- "Work on handlers"

### Task Granularity

- **Task**: 15-60 minutes of focused work
- **Subtask**: 5-15 minutes of specific action
- **Phase**: Group of related tasks (hours/days)

### Status Update Discipline

1. **Before starting work**: Review plan, mark task 🔄
2. **During work**: Update status if blocked
3. **After completing**: Mark ✅, run QA, commit with reference
4. **Regularly**: Review the plan and edit it IN PLACE so it states current
   truth. Append the narrative of what happened to the plan's `JOURNAL/`
   day-file — never to `PLAN.md`. See [CLAUDE/PlanJournalling.md](PlanJournalling.md).

### Handling Changes

When requirements change mid-plan:

1. **Document Change**: Edit `PLAN.md` in place to state the new truth
   (revise Goals/Tasks, record the reasoning under Technical Decisions), and
   append a dated entry to the plan's `JOURNAL/` recording what changed and
   why. Do NOT append a change-log section to `PLAN.md`.
2. **Update Tasks**: Revise task list as needed
3. **Assess Impact**: Update estimates, dependencies
4. **Communicate**: Ensure stakeholders aware

---

## Plan Reviews

### Daily Review (If actively working on plan)

- Are tasks up to date?
- Any blockers need attention?
- Is plan still on track?
- Are QA checks still passing?

### Weekly Review (For active plans)

- Progress vs timeline?
- Any scope changes needed?
- Dependencies still valid?
- Test coverage maintained?

### Completion Review

- All success criteria met?
- All QA checks pass?
- Lessons learned documented?
- Follow-up work identified?

---

## Plan Metrics

Track these for each plan:

- **Planned vs Actual Effort**: Improve estimation
- **Blocker Count**: Identify process issues
- **Scope Changes**: Track requirements stability
- **Completion Rate**: % of tasks completed
- **QA Pass Rate**: How often QA passes on first run

---

## Integration with Git

### Commit Messages

Reference plans in commits:

```
Plan 00001: Implement destructive git handler

- Add DestructiveGitHandler to block force push and reset --hard
- Include tests for all blocked patterns
- Register handler with priority 10

Refs: CLAUDE/Plan/00001-handler-implementation
```

### Branch Naming

For larger plans, use feature branches:

```
plan/00001-destructive-git-handler
plan/00002-config-refactoring
plan/00003-tdd-enforcement
```

### Pre-Commit Verification

Before committing, always verify:

```bash
# Run full QA suite
./scripts/qa/llm_qa.py all

# Check git status
git status

# Stage specific files (avoid staging secrets)
git add src/handlers/pre_tool_use/my_handler.py
git add tests/handlers/pre_tool_use/test_my_handler.py

# Commit with plan reference
git commit -m "Plan 00001: Implement destructive git handler"
```

---

## Plan Index

Maintain `CLAUDE/Plan/README.md`:

```markdown
# Plans Index

## Active Plans
- [00001: Destructive Git Handler](00001-handler-implementation/PLAN.md) - In Progress

## Completed Plans
- None yet

## Blocked Plans
- None

## Cancelled Plans
- None
```

---

## AI Agent Guidelines

When Claude Code (or other AI agents) work on this project:

01. **Always check for existing plans** before starting work
02. **Create plan if none exists** for work > 2 hours
03. **Choose execution strategy** based on current model and plan complexity:
    - **Sonnet**: Default to Sub-Agent Orchestration
    - **Opus**: Default to Sub-Agent Teams
    - **Haiku**: Default to Single-Threaded
04. **Debug hook events first** - Before writing handlers:
    - Use `scripts/debug_hooks.sh` to capture event flow
    - Analyse logs to understand what events fire
    - See CLAUDE/DEBUGGING_HOOKS.md for complete guide
05. **Follow TDD workflow** - Write failing tests before implementation
06. **Update task status in real-time** as you work
07. **Run QA before commits** - `./scripts/qa/llm_qa.py all` must pass
08. **Document blockers immediately** if you get stuck
09. **Ask user for approval** before marking plan complete
10. **Reference plans in all commits** for traceability

### Agent Workflow Example

```
User: "Implement a handler to block destructive sed commands"

Agent:
1. Checks CLAUDE/Plan/ for existing plan
2. If none, creates Plan 00001 (via `CLAUDE/Plan/mkplan.bash`)
3. Runs debug script to capture sed usage events
4. Analyzes events to determine handler design
5. Breaks down into TDD tasks
6. Shows plan to user for approval
7. Begins execution:
   - Write failing test
   - Implement handler
   - Run QA suite
8. Commits with "Plan 00001: Implement sed blocker handler"
9. Ticks the task in PLAN.md and appends the narrative to the plan's JOURNAL/
10. Marks complete when all QA passes
```

### Handler Development Workflow

**CRITICAL**: Always debug first, develop second:

1. Identify scenario ("enforce TDD", "block destructive git", etc.)
2. **Use `scripts/debug_hooks.sh` to capture event flow**
3. Analyse logs to determine which event type and what data is available
4. Write tests first (TDD)
5. Implement handler
6. Run QA suite
7. Debug again to verify handler intercepts correctly
8. Test in live Claude Code session

---

## Summary

**Remember**:

- Plan before you code
- Debug hook events before writing handlers
- Write tests first (TDD)
- Run QA before commits
- Update status religiously
- Keep tasks concrete and testable
- Document decisions and changes
- Plans are living documents

**Questions?** See examples in `CLAUDE/Plan/` or ask in conversation.

---

**Maintained by**: Claude Code Hooks Daemon Contributors
**Last Updated**: January 2026
