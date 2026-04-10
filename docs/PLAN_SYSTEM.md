# Plan System

A structured planning methodology for organizing development work through numbered folders and standardized documentation. Originally developed for the Claude Code Hooks Daemon but applicable to any software project.

**Version**: 2.0
**Status**: Production-ready
**License**: MIT

---

## Important Distinction

**Plans vs Workflows** - These are two completely separate concepts:

- **Plans** (this document): Numbered folders (`00001-`, `00002-`, etc.) for tracking development work. Each plan has a `PLAN.md` with tasks, goals, and status.
- **Workflows** (see [WORKFLOWS.md](WORKFLOWS.md)): Repeatable processes (like `page-orchestration`, `qa-skill`, `release`) that survive conversation compaction through state files.

This document covers **Plans only**. For workflow documentation, see [WORKFLOWS.md](WORKFLOWS.md).

---

## Table of Contents

1. [Overview & Philosophy](#overview--philosophy)
2. [Core Concepts](#core-concepts)
3. [Directory Structure](#directory-structure)
4. [Plan Document Template](#plan-document-template)
5. [Setting Up Plan System](#setting-up-plan-system)
6. [Customization Guide](#customization-guide)
7. [Best Practices](#best-practices)
8. [Integration with Other Tools](#integration-with-other-tools)
9. [Examples](#examples)

---

## Overview & Philosophy

### What is the Plan System?

The Plan System is a structured approach to organizing development work through:

- **Numbered folders** (sequential, zero-padded) containing all plan-related documentation
- **Standardized PLAN.md** format with tasks, goals, decisions, and progress tracking
- **Lifecycle management** (Not Started → In Progress → Complete/Blocked/Cancelled)
- **Documentation co-location** (all supporting docs stay with the plan)
- **Archive preservation** (completed plans move to Completed/ for historical reference)

### Why Use Structured Planning?

**For Human Developers:**

- Clearer thinking through explicit task breakdown
- Visible progress tracking
- Better handoffs between team members
- Historical knowledge preservation

**For AI Assistants:**

- Context preservation across sessions
- Explicit task prioritization
- Reduced hallucination (written goals vs assumed goals)
- Better collaboration between multiple AI agents

**For Projects:**

- Architectural decision log
- Work estimation improvement over time
- Audit trail for changes
- Onboarding documentation

### Benefits Over Ad-Hoc Development

| Ad-Hoc Approach                     | Plan Workflow Approach                 |
| ----------------------------------- | -------------------------------------- |
| Tasks scattered across tools/memory | Single source of truth in CLAUDE/Plan/ |
| Lost context after interruptions    | State preserved in PLAN.md             |
| Unclear completion criteria         | Explicit success criteria              |
| No decision rationale               | Technical decisions documented         |
| Hard to resume work                 | README.md index shows all active plans |

### When to Use Plans vs Simple Tasks

**Use Plan Workflow For:**

- Work taking > 2 hours
- Multi-phase implementation
- Architectural decisions needed
- Work that may be interrupted/resumed
- Coordination between multiple people/agents
- Anything with significant risk

**Use Simple Task Lists For:**

- Quick fixes (< 1 hour)
- Single-session work
- No architectural decisions
- Low risk changes
- Temporary tracking during active work

**Converting Simple Tasks to Plans:**
If your task list grows beyond 5 items or spans multiple sessions, create a proper plan and migrate the tasks.

---

## Core Concepts

### 1. Numbered Folders

Plans use **5-digit zero-padded sequential numbering**:

```
00001-first-feature/
00002-bug-fix/
00003-refactoring/
...
00099-another-feature/
00100-milestone-work/
```

**Why this format?**

- **Sortable**: Filesystem sorts correctly (00001 before 00002)
- **Trackable**: Easy to reference in commits ("Plan 00042: ...")
- **Scalable**: Supports 00001-99999 plans
- **Stable**: Numbers never change even if plan is cancelled

### 2. Plan Lifecycle

Every plan progresses through states:

```
Not Started → In Progress → Complete
                         ↘ Blocked
                         ↘ Cancelled
```

**Status tracking** in PLAN.md header:

```markdown
**Status**: In Progress
```

**Completion** triggers move to archive:

```bash
git mv CLAUDE/Plan/00042-feature CLAUDE/Plan/Completed/00042-feature
```

### 3. Documentation Co-location

All plan-related documents stay together:

```
00042-complex-feature/
├── PLAN.md                  # Main plan document
├── architecture-analysis.md # Supporting analysis
├── design-decisions.md      # Design exploration
├── performance-study.md     # Research findings
└── assets/
    ├── diagram.png          # Visual aids
    └── benchmark-logs.txt   # Data files
```

**Benefits:**

- No scattered documentation
- Everything moves together to Completed/
- Easy to find all context for a plan
- Historical plans remain complete

### 4. Atomic Units of Work

**One plan = one cohesive piece of work**

- Single clear goal
- Measurable success criteria
- Related tasks grouped together
- Independent completion (no cross-plan dependencies if possible)

**If a plan grows too large**, split it:

```
00050-large-feature/           → Split into:
                                 00050-feature-phase-1/
                                 00051-feature-phase-2/
                                 00052-feature-phase-3/
```

### 5. Task Status System

Plans use **emoji status indicators** for visual clarity:

| Status       | Icon | Markdown | Usage              |
| ------------ | ---- | -------- | ------------------ |
| Not Started  | ⬜   | `⬜`     | Task hasn't begun  |
| In Progress  | 🔄   | `🔄`     | Currently working  |
| Completed    | ✅   | `✅`     | Done and verified  |
| Blocked      | 🚫   | `🚫`     | Cannot proceed     |
| Cancelled    | ❌   | `❌`     | No longer needed   |
| On Hold      | ⏸️   | `⏸️`     | Paused temporarily |
| Needs Review | 👁️   | `👁️`     | Awaiting review    |

**Example:**

```markdown
### Phase 1: Implementation
- [ ] ⬜ **Setup environment**
  - [ ] 🔄 Install dependencies
  - [ ] ✅ Configure tooling
  - [ ] 🚫 Setup CI (blocked: credentials needed)
```

---

## Directory Structure

### Standard Layout

```
project-root/
└── CLAUDE/
    └── Plan/
        ├── README.md                    # Index of all plans
        ├── CLAUDE.md                    # Lifecycle instructions
        ├── 00001-first-feature/
        │   ├── PLAN.md                 # Main plan document
        │   ├── supporting-doc.md       # Optional supporting docs
        │   └── assets/                 # Optional assets folder
        ├── 00002-another-feature/
        │   └── PLAN.md
        ├── Completed/
        │   └── 00001-first-feature/    # Moved when complete
        │       └── PLAN.md
        ├── Cancelled/                   # Optional: cancelled plans
        └── Archive/                     # Optional: old/deprecated plans
```

### Key Files

**README.md** - Master index of all plans:

```markdown
# Plans Index

## Active Plans
- [00042: Feature X](00042-feature-x/PLAN.md) - In Progress
- [00043: Bug Fix Y](00043-bug-fix-y/PLAN.md) - Not Started

## Completed Plans
- [00041: Refactoring Z](Completed/00041-refactoring-z/PLAN.md) - Complete (2026-02-15)

## Plan Statistics
- **Total Plans Created**: 43
- **Active**: 2
- **Completed**: 40
- **Cancelled**: 1
```

**CLAUDE.md** - Lifecycle instructions for AI assistants:

```markdown
# Plan Lifecycle

See @CLAUDE/PlanWorkflow.md for full workflow.

## Quick Reference
- Create: CLAUDE/Plan/NNNNN-description/
- Execute: Update status as you go
- Complete: Move to Completed/, update README.md
```

---

## Plan Document Template

Every `PLAN.md` follows this structure:

```markdown
# Plan NNNNN: [Plan Title]

**Status**: In Progress | Complete | Blocked | Cancelled
**Created**: YYYY-MM-DD
**Owner**: [Name/Agent]
**Priority**: High | Medium | Low
**Estimated Effort**: [X hours/days]

## Overview

[2-3 paragraphs describing what this plan aims to achieve and why]

## Goals

- Clear, measurable goal 1
- Clear, measurable goal 2
- Clear, measurable goal 3

## Non-Goals

- Explicitly what this plan will NOT do
- Helps prevent scope creep

## Context & Background

[Relevant background, previous decisions, or context needed]
[Reference supporting docs for detailed information]

## Tasks

### Phase 1: [Phase Name]

- [ ] ⬜ **Task 1.1**: Description
  - [ ] ⬜ Subtask 1.1.1: Specific work
  - [ ] ⬜ Subtask 1.1.2: Specific work
- [ ] ⬜ **Task 1.2**: Description

### Phase 2: [Phase Name]

- [ ] ⬜ **Task 2.1**: Description
- [ ] ⬜ **Task 2.2**: Description

## Dependencies

- Depends on: Plan 00040 (Complete)
- Blocks: Plan 00044 (Not Started)
- Related: Plan 00041

## Technical Decisions

### Decision 1: [Title]

**Context**: Why this decision is needed

**Options Considered**:
1. Option A - pros: X, cons: Y
2. Option B - pros: X, cons: Y

**Decision**: We chose Option A because [rationale]

**Date**: YYYY-MM-DD

## Success Criteria

- [ ] Criterion 1 that must be met
- [ ] Criterion 2 that must be met
- [ ] All tests passing
- [ ] Documentation updated

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Risk description | High/Med/Low | High/Med/Low | How to handle |

## Timeline

- Phase 1: 2026-02-01 to 2026-02-05
- Phase 2: 2026-02-06 to 2026-02-10
- Target Completion: 2026-02-10

## Notes & Updates

### 2026-02-03
- Update or note about progress/changes

### 2026-02-05
- Another update or decision
```

### Template Sections Explained

**Header Block**: Quick reference metadata

- **Status**: Current state (In Progress, Complete, etc.)
- **Created**: Start date
- **Owner**: Person/agent responsible
- **Priority**: Urgency level
- **Estimated Effort**: Time estimate (improves over time)

**Overview**: What and why (2-3 paragraphs maximum)

**Goals**: Explicit success targets (measurable)

**Non-Goals**: Explicit scope boundaries (prevent feature creep)

**Context & Background**: Why this work is needed (link to issues, previous discussions)

**Tasks**: Concrete work items with status tracking

- Break into phases if multi-stage
- Use emoji status indicators
- Include subtasks for granularity

**Dependencies**: Cross-plan relationships

- **Depends on**: Must complete before this starts
- **Blocks**: This blocks other plans
- **Related**: Associated but not blocking

**Technical Decisions**: Architectural choices with rationale

- Document options considered
- Explain why chosen path was selected
- Date decisions for historical context

**Success Criteria**: Definition of done (checkboxes)

**Risks & Mitigations**: What could go wrong and how to handle it

**Timeline**: Target dates (estimates, not commitments)

**Notes & Updates**: Running log of progress and changes

---

## Optional Handler Support

The Claude Code Hooks Daemon includes optional handlers that support the Plan System:

### 1. MarkdownOrganizationHandler (Optional)

**Event**: PostToolUse (Write/Edit)
**Priority**: 40
**Type**: Blocking

**Purpose**: Enforces markdown file organization rules, including CLAUDE/Plan/ structure.

**What it does**:

- Allows markdown files in approved locations (CLAUDE/Plan/, docs/, etc.)
- Blocks markdown files outside approved locations
- Allows edits to PLAN.md and supporting docs within plan folders
- Allows Completed/, Cancelled/, Archive/ subdirectories

**Configuration**:

```yaml
handlers:
  post_tool_use:
    markdown_organization:
      enabled: true
      priority: 40
      track_plans_in_project: "CLAUDE/Plan"
```

### 2. PlanCompletionAdvisorHandler (Optional)

**Event**: PreToolUse (Write/Edit)
**Priority**: 36
**Type**: Non-blocking (advisory)

**Purpose**: Reminds agent to properly close out completed plans.

**What it does**:

- Detects edits to PLAN.md that change status to "Complete"
- Provides advisory about completion steps:
  - Move folder to Completed/
  - Update README.md (remove from Active, add to Completed)
  - Update plan statistics

**Example advisory**:

```
Plan 00042-feature appears to be marked as complete. Remember to:
1. Move to Completed/: git mv CLAUDE/Plan/00042-feature CLAUDE/Plan/Completed/
2. Update CLAUDE/Plan/README.md (move from Active to Completed section, update link path)
3. Update plan statistics in README.md (increment Completed count, update total)
```

### 3. GitContextInjectorHandler (Optional)

**Event**: UserPromptSubmit
**Priority**: 50
**Type**: Non-blocking (advisory)

**Purpose**: Suggests referencing plan numbers in git commits.

**Commit message format**:

```
Plan 00042: Implement feature X

- Add handler for Y
- Include tests for Z

Refs: CLAUDE/Plan/00042-feature/PLAN.md
```

**Note**: These handlers are optional. The Plan System works without the hooks daemon - it's simply a documentation convention using numbered folders and PLAN.md files.

---

## Setting Up Plan System

### Prerequisites

1. **Git repository** (plan folders tracked in version control)
2. **Markdown editor** (any text editor works)
3. **Claude Code Hooks Daemon** (optional - for automated enforcement)

### Step 1: Initialize Directory Structure

```bash
# Create plan directory structure
mkdir -p CLAUDE/Plan/{Completed,Cancelled,Archive}

# Create index file
cat > CLAUDE/Plan/README.md << 'EOF'
# Plans Index

## Active Plans

- None yet

## Completed Plans

- None yet

## Plan Statistics

- **Total Plans Created**: 0
- **Active**: 0
- **Completed**: 0
EOF

# Create lifecycle instructions
cat > CLAUDE/Plan/CLAUDE.md << 'EOF'
# Plan Lifecycle

See @CLAUDE/PlanWorkflow.md for full planning workflow.

## Quick Reference

- **Create**: CLAUDE/Plan/NNNNN-description/
- **Execute**: Update task status as you work
- **Complete**: Move to Completed/, update README.md
EOF
```

### Step 2: Copy Plan Template

Save the [Plan Document Template](#plan-document-template) as `CLAUDE/Plan/TEMPLATE.md` for easy reference.

### Step 3: Create Your First Plan

```bash
# Create plan folder
mkdir -p CLAUDE/Plan/00001-my-first-feature

# Copy template
cp CLAUDE/Plan/TEMPLATE.md CLAUDE/Plan/00001-my-first-feature/PLAN.md

# Edit plan (fill in overview, goals, tasks)
# Then update README.md to add plan to Active Plans section
```

### Step 4: Configure Handlers (Optional)

If using the Claude Code Hooks Daemon, edit `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  post_tool_use:
    markdown_organization:
      enabled: true
      priority: 40
      track_plans_in_project: "CLAUDE/Plan"

  pre_tool_use:
    plan_completion_advisor:
      enabled: true
      priority: 36
```

See [Installation Guide](../CLAUDE/LLM-INSTALL.md) for daemon installation.

### Step 5: Git Integration

Add to `.git/info/exclude` (or `.gitignore` if shared):

```
# Plan drafts and work-in-progress notes
CLAUDE/Plan/*/DRAFT-*.md
CLAUDE/Plan/*/NOTES-*.md
```

---

## Customization Guide

### Project-Specific Adaptations

The Plan Workflow concept is flexible - adapt it to your project's needs:

#### Different Folder Structure

**Instead of `CLAUDE/Plan/`**, use what fits your project:

```
# Technical project
docs/plans/

# Product project
product/plans/

# Research project
research/experiments/
```

**Update handler config** if using daemon:

```yaml
handlers:
  post_tool_use:
    markdown_organization:
      track_plans_in_project: "docs/plans"
```

#### Custom Numbering Scheme

**3-digit numbering** for smaller projects:

```
001-feature/
002-bugfix/
...
999-milestone/
```

**Date-based numbering** for research projects:

```
2026-02-17-experiment-a/
2026-02-18-experiment-b/
```

**Key principle**: Whatever scheme you choose, be consistent.

#### Modified Templates

Add project-specific sections:

**For API projects**:

```markdown
## API Changes

- Endpoints added: [list]
- Endpoints modified: [list]
- Breaking changes: [list]
- Migration guide: [link]
```

**For UI projects**:

```markdown
## Design Review

- Figma link: [url]
- Design review date: YYYY-MM-DD
- Approved by: [name]
- Design notes: [description]
```

**For data projects**:

```markdown
## Data Impact

- Tables affected: [list]
- Migration required: Yes/No
- Data validation: [approach]
- Rollback plan: [steps]
```

#### Task Tracking Integration

**Jira integration**:

```markdown
## Tasks

### Phase 1: Implementation
- [ ] ⬜ **Task 1**: [Description] (JIRA-123)
- [ ] ⬜ **Task 2**: [Description] (JIRA-124)
```

**GitHub Issues integration**:

```markdown
**GitHub Issue**: #42

## Tasks
- [ ] ⬜ **Fix bug X** (refs #42)
```

#### Additional Supporting Doc Types

Add project-specific supporting docs:

```
00042-feature/
├── PLAN.md
├── API-SPEC.md          # API documentation
├── DATABASE-SCHEMA.md   # Schema changes
├── PERFORMANCE.md       # Performance analysis
├── SECURITY.md          # Security considerations
└── ROLLBACK-PLAN.md     # Rollback procedures
```

### Language-Specific Adaptations

**Python projects** - Add QA requirements:

```markdown
## Success Criteria
- [ ] All tests passing (pytest)
- [ ] 95%+ test coverage
- [ ] Type checking passes (mypy strict)
- [ ] Linting passes (ruff)
- [ ] Formatting correct (black)
```

**JavaScript projects** - Add build checks:

```markdown
## Success Criteria
- [ ] All tests passing (jest)
- [ ] ESLint passes with zero warnings
- [ ] TypeScript compilation successful
- [ ] Build passes (npm run build)
- [ ] Bundle size within limits
```

**Go projects** - Add Go-specific checks:

```markdown
## Success Criteria
- [ ] All tests passing (go test)
- [ ] go vet passes
- [ ] golangci-lint passes
- [ ] go mod tidy clean
```

---

## Best Practices

### 1. Plan Creation

**Good plan titles**:

```
✅ 00042-add-user-authentication
✅ 00043-fix-memory-leak-in-parser
✅ 00044-refactor-database-layer
```

**Bad plan titles**:

```
❌ 00042-stuff
❌ 00043-fix-things
❌ 00044-update
```

**When to create a plan**:

- Work will take > 2 hours
- Multiple related tasks
- Requires architectural decisions
- May be interrupted/resumed
- Needs documentation for others

**When NOT to create a plan**:

- Quick fixes (< 1 hour)
- Simple typo corrections
- Single-file changes with no design decisions
- Temporary experimental work

### 2. Task Writing

**Good tasks** (specific, actionable, testable):

```markdown
✅ **Create user authentication handler**
  - [ ] Write failing test for login validation
  - [ ] Implement password hashing (bcrypt)
  - [ ] Add JWT token generation
  - [ ] Test with real user database
  - [ ] Update API documentation

✅ **Fix memory leak in parser** (max 30 minutes)
  - [ ] Profile parser with heap analysis
  - [ ] Identify leak source
  - [ ] Implement fix
  - [ ] Verify with profiler
```

**Bad tasks** (vague, non-actionable):

```markdown
❌ **Fix the system**
❌ **Make it better**
❌ **Work on authentication**
```

**Task granularity**:

- **Task**: 15-60 minutes of focused work
- **Subtask**: 5-15 minutes of specific action
- **Phase**: Group of related tasks (hours/days)

### 3. Status Update Discipline

**Update frequently**:

```markdown
# Morning: Start work
- [ ] 🔄 **Task 1**: Currently implementing

# Afternoon: Hit blocker
- [ ] 🚫 **Task 1**: Blocked - waiting for API key

# Next day: Blocker resolved
- [ ] ✅ **Task 1**: Complete - tested and working
```

**Rules**:

1. **Limit work in progress**: Max 1-2 tasks marked 🔄 at a time
2. **Update immediately**: Change status as soon as state changes
3. **Document blocks**: If 🚫, add note explaining why
4. **Verify completion**: Only ✅ after testing/verification

### 4. Handling Changes

**When requirements change mid-plan**:

```markdown
## Notes & Updates

### 2026-02-10 - Scope Change
Original goal was X, but stakeholder requested Y instead.

**Impact**:
- Added 2 new tasks to Phase 2
- Removed Task 3.1 (no longer needed)
- Timeline extended by 2 days

**Decision**: Proceed with revised scope (approved by stakeholder)
```

**When to split a plan**:

- Original estimate was way off (2x+ longer)
- Natural breakpoint discovered
- Part can ship independently
- Different priorities emerge

**How to split**:

```bash
# Original: 00042-large-feature (too big)

# Split into:
git mv CLAUDE/Plan/00042-large-feature CLAUDE/Plan/00042-feature-phase-1

# Create new plans:
mkdir CLAUDE/Plan/00043-feature-phase-2
mkdir CLAUDE/Plan/00044-feature-phase-3

# Update dependencies in each PLAN.md
```

### 5. Completion Checklist

**Before marking plan complete**:

- [ ] All tasks marked ✅
- [ ] All success criteria met
- [ ] Tests passing
- [ ] Documentation updated
- [ ] Code review complete (if applicable)
- [ ] Deployed to staging/production
- [ ] Post-mortem notes added (what went well, what didn't)

**Completion workflow**:

```bash
# 1. Update PLAN.md status
# Change: **Status**: In Progress
# To:     **Status**: Complete (2026-02-17)

# 2. Move to Completed
git mv CLAUDE/Plan/00042-feature CLAUDE/Plan/Completed/00042-feature

# 3. Update README.md
# - Remove from Active Plans
# - Add to Completed Plans with summary
# - Update statistics (increment Completed count)

# 4. Commit
git add CLAUDE/Plan/
git commit -m "Plan 00042: Complete - Feature X implementation

All tasks complete, tests passing, deployed to production.
See Completed/00042-feature/PLAN.md for full details."
```

### 6. Plan Reviews

**Daily review** (if actively working on plan):

- Are tasks up to date?
- Any blockers need attention?
- Is plan still on track?
- Any scope changes needed?

**Weekly review** (for active plans):

- Progress vs timeline?
- Dependencies still valid?
- Risks materialized?
- Lessons learned so far?

**Completion review**:

- All success criteria met?
- Lessons learned documented?
- Follow-up work identified?
- Knowledge transferred?

---

## Integration with Other Tools

### Git Integration

**Commit message format**:

```
Plan 00042: Add user authentication

- Implement bcrypt password hashing
- Add JWT token generation and validation
- Include integration tests for auth flow

Refs: CLAUDE/Plan/00042-user-auth/PLAN.md
```

**Branch naming** (for larger plans):

```bash
# Create feature branch from plan
git checkout -b plan/00042-user-auth

# Work on plan
# ...

# Merge when complete
git checkout main
git merge --no-ff plan/00042-user-auth
git branch -d plan/00042-user-auth
```

**Tags for milestones**:

```bash
# Tag major plan completions
git tag -a milestone-v1.0-complete -m "Plans 00001-00025 complete - v1.0 feature set"
```

### Issue Tracker Integration

**Link plans to issues**:

```markdown
# Plan 00042: Fix Memory Leak

**GitHub Issue**: #123
**JIRA Issue**: PROJ-456

## Tasks
- [ ] ⬜ **Profile application** (GitHub #123)
- [ ] ⬜ **Implement fix** (JIRA PROJ-456)
```

**Close issues when plan completes**:

```bash
# In plan completion commit message
git commit -m "Plan 00042: Complete - Memory leak fixed

Fixes #123
Resolves PROJ-456"
```

### CI/CD Integration

**Validation hooks**:

```yaml
# .github/workflows/validate-plans.yml
name: Validate Plans

on: [pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Check plan structure
        run: |
          # Validate PLAN.md files exist
          # Check for required sections
          # Validate numbering sequence
          ./scripts/validate-plans.sh
```

**Auto-generate documentation**:

```yaml
# Generate PLAN-INDEX.md from all plans
- name: Generate plan index
  run: |
    python scripts/generate-plan-index.py > docs/PLAN-INDEX.md
    git add docs/PLAN-INDEX.md
```

### Documentation Generation

**Extract technical decisions**:

```python
# scripts/extract-decisions.py
# Reads all PLAN.md files
# Extracts "Technical Decisions" sections
# Generates ARCHITECTURE-DECISIONS.md
```

**Generate metrics**:

```python
# scripts/plan-metrics.py
# Calculates:
# - Average plan duration
# - Completion rate
# - Most common blockers
# - Estimation accuracy
```

---

## Examples

### Example 1: Simple Feature Plan

```markdown
# Plan 00042: Add Dark Mode Toggle

**Status**: Complete (2026-02-17)
**Created**: 2026-02-15
**Owner**: AI Assistant
**Priority**: Medium
**Estimated Effort**: 4 hours
**Actual Effort**: 3.5 hours

## Overview

Add a dark mode toggle to the application UI. Users have requested a dark theme option to reduce eye strain during nighttime usage.

## Goals

- Add toggle switch to settings page
- Persist user preference in localStorage
- Support system-level dark mode preference detection
- Apply dark theme to all existing components

## Non-Goals

- Custom color scheme selection (use standard dark theme)
- Dark mode for marketing pages (product UI only)
- Automatic time-based switching

## Tasks

### Phase 1: Design
- [x] ✅ **Review existing color palette**
- [x] ✅ **Define dark mode CSS variables**
- [x] ✅ **Create toggle component mockup**

### Phase 2: Implementation
- [x] ✅ **Create DarkModeToggle component**
  - [x] ✅ Write component tests
  - [x] ✅ Implement toggle UI
  - [x] ✅ Add accessibility labels
- [x] ✅ **Add theme context provider**
  - [x] ✅ Implement useTheme hook
  - [x] ✅ Add localStorage persistence
  - [x] ✅ Detect system preference
- [x] ✅ **Update CSS variables for dark mode**
- [x] ✅ **Test all components in dark mode**

### Phase 3: Polish
- [x] ✅ **Add smooth theme transition**
- [x] ✅ **Update documentation**
- [x] ✅ **Deploy to staging**

## Success Criteria

- [x] Toggle switch renders correctly
- [x] Theme persists across page reloads
- [x] System preference detected on first load
- [x] All components render correctly in dark mode
- [x] Accessibility audit passes
- [x] Documentation updated

## Technical Decisions

### Decision 1: CSS Variables vs CSS-in-JS

**Context**: Need to apply dark theme across all components

**Options Considered**:
1. CSS Variables - Define colors once, swap with data attribute
2. CSS-in-JS - Use theme prop in styled-components

**Decision**: CSS Variables because:
- Simpler implementation
- No runtime overhead
- Easier to maintain
- Standard web platform feature

**Date**: 2026-02-15

## Notes & Updates

### 2026-02-15
- Started implementation
- Chose CSS variables approach

### 2026-02-16
- Completed core implementation
- All tests passing

### 2026-02-17
- Deployed to staging
- QA approved
- Deployed to production
- Plan complete!
```

### Example 2: Complex Refactoring Plan

```markdown
# Plan 00043: Refactor Database Layer to Repository Pattern

**Status**: In Progress
**Created**: 2026-02-10
**Owner**: Development Team
**Priority**: High
**Estimated Effort**: 3 weeks

## Overview

The current database layer has direct SQL queries scattered across business logic. This makes testing difficult and creates tight coupling. Refactor to use Repository Pattern with clean separation of concerns.

## Goals

- Centralize all database queries in repository classes
- Enable easy mocking for unit tests
- Support multiple database backends (PostgreSQL, SQLite for tests)
- Improve query performance with proper indexing

## Non-Goals

- ORM migration (stick with raw SQL for performance)
- GraphQL API layer (separate project)
- Database schema changes (schema stays the same)

## Context & Background

Current pain points:
- Business logic mixed with SQL queries
- Difficult to unit test without database
- Query duplication across controllers
- No query performance monitoring

See `database-analysis.md` for detailed audit of current state.

## Tasks

### Phase 1: Design (Week 1)
- [x] ✅ **Audit existing database queries**
  - [x] ✅ Find all direct SQL usage (49 locations found)
  - [x] ✅ Group by entity type (User, Order, Product, etc.)
  - [x] ✅ Document current query patterns
- [x] ✅ **Design repository interface**
  - [x] ✅ Define base Repository<T> interface
  - [x] ✅ Design UserRepository interface
  - [x] ✅ Design OrderRepository interface
  - [x] ✅ Get team review and approval
- [x] ✅ **Create migration plan**
  - [x] ✅ Determine migration order (least coupled first)
  - [x] ✅ Plan feature flag strategy
  - [x] ✅ Define rollback procedures

### Phase 2: Foundation (Week 1-2)
- [x] ✅ **Implement base repository infrastructure**
  - [x] ✅ Create Repository<T> base class
  - [x] ✅ Add connection pool management
  - [x] ✅ Implement query logging
  - [x] ✅ Add performance monitoring
- [ ] 🔄 **Implement UserRepository**
  - [x] ✅ Write repository interface
  - [x] ✅ Implement PostgreSQL version
  - [ ] 🔄 Implement SQLite version (for tests)
  - [ ] ⬜ Write comprehensive tests
  - [ ] ⬜ Migrate user-related queries

### Phase 3: Entity Repositories (Week 2-3)
- [ ] ⬜ **Implement OrderRepository**
- [ ] ⬜ **Implement ProductRepository**
- [ ] ⬜ **Implement CategoryRepository**
- [ ] ⬜ **Implement PaymentRepository**

### Phase 4: Migration (Week 3)
- [ ] ⬜ **Migrate business logic layer**
  - [ ] ⬜ Update UserController to use UserRepository
  - [ ] ⬜ Update OrderController to use OrderRepository
  - [ ] ⬜ Update remaining controllers
- [ ] ⬜ **Remove old database layer**
  - [ ] ⬜ Delete legacy query helpers
  - [ ] ⬜ Update documentation
  - [ ] ⬜ Remove feature flags

### Phase 5: Optimization (Week 3)
- [ ] ⬜ **Add query optimization**
  - [ ] ⬜ Review slow query log
  - [ ] ⬜ Add missing indexes
  - [ ] ⬜ Optimize N+1 queries
- [ ] ⬜ **Load testing**
  - [ ] ⬜ Benchmark before/after performance
  - [ ] ⬜ Verify no regressions

## Dependencies

- Blocks: Plan 00044 (GraphQL API - needs clean data layer)
- Related: Plan 00040 (Testing improvements - benefits from mockable repos)

## Technical Decisions

### Decision 1: Repository Pattern vs Active Record

**Context**: Need better separation of concerns and testability

**Options Considered**:
1. Repository Pattern - Separate data access layer with interfaces
2. Active Record - Entities know how to persist themselves
3. Data Mapper ORM - Use full ORM like SQLAlchemy

**Decision**: Repository Pattern because:
- Clean separation enables easy testing
- Supports multiple DB backends cleanly
- Keeps business logic decoupled from persistence
- No ORM overhead (we need raw SQL performance)

**Date**: 2026-02-10

### Decision 2: Generic Repository<T> vs Specific Repositories

**Context**: Should we have a base generic repository or only specific ones?

**Options Considered**:
1. Generic Repository<T> with common CRUD operations
2. Only specific repositories (UserRepository, etc.) with custom methods

**Decision**: Hybrid approach:
- Generic Repository<T> base class with common operations (findById, save, delete)
- Specific repositories extend base and add entity-specific queries
- Balance between DRY and type safety

**Date**: 2026-02-11

## Success Criteria

- [ ] All SQL queries moved to repository classes
- [ ] Zero direct database access in business logic
- [ ] 95%+ test coverage for repositories
- [ ] Unit tests can run without database (using mocks)
- [ ] Performance benchmarks show no regression
- [ ] Documentation updated with new architecture
- [ ] Team trained on repository pattern

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Performance regression | High | Medium | Benchmark each repository, rollback if slower |
| Breaking existing features | High | Low | Feature flags, gradual rollout, extensive testing |
| Team adoption issues | Medium | Medium | Training sessions, pair programming, code reviews |
| Timeline overrun | Medium | High | Start with smallest repositories, learn as we go |

## Timeline

- Week 1 (Feb 10-14): Design + Foundation
- Week 2 (Feb 17-21): UserRepository migration + additional repos
- Week 3 (Feb 24-28): Remaining migrations + optimization
- Target Completion: 2026-02-28

## Notes & Updates

### 2026-02-10
- Created plan after team discussion
- Everyone aligned on Repository Pattern approach
- Sarah volunteered to lead migration

### 2026-02-11
- Design review complete
- Repository interfaces approved
- Started implementing base infrastructure

### 2026-02-14
- Base Repository<T> complete
- UserRepository PostgreSQL implementation done
- Currently working on SQLite test version

### 2026-02-17
- Hit blocker: SQLite syntax differences from PostgreSQL
- Decision: Create adapter layer for DB-specific SQL
- Created adapters for both PostgreSQL and SQLite
- Back on track now
```

### Example 3: Bug Fix Plan

```markdown
# Plan 00045: Fix Memory Leak in Event Processing

**Status**: Complete (2026-02-16)
**Created**: 2026-02-15
**Owner**: Performance Team
**Priority**: Critical
**Estimated Effort**: 1 day
**Actual Effort**: 6 hours

**GitHub Issue**: #287

## Overview

Production monitoring shows memory usage growing unbounded in event processing service. Memory grows by ~50MB/hour, eventually causing OOM crashes after 24-48 hours of uptime.

## Goals

- Identify source of memory leak
- Implement fix
- Verify leak is resolved with profiling
- Deploy fix to production

## Non-Goals

- General performance optimization (separate effort)
- Event processing refactoring (not needed)

## Context & Background

**Symptom**: Memory usage grows continuously, never levels off
**Impact**: Service crashes every 24-48 hours, requires restart
**First observed**: 2026-02-10 (after v2.5.0 deployment)
**Potential cause**: Recent changes to event listener registration

See `memory-profile-analysis.md` for detailed profiling data.

## Tasks

### Phase 1: Investigation
- [x] ✅ **Reproduce locally**
  - [x] ✅ Set up monitoring
  - [x] ✅ Run service with profiling enabled
  - [x] ✅ Confirm memory growth
- [x] ✅ **Profile with heap analysis**
  - [x] ✅ Take heap dumps at intervals
  - [x] ✅ Compare snapshots
  - [x] ✅ Identify growing objects
- [x] ✅ **Identify leak source**
  - [x] ✅ Found: EventListener instances not being garbage collected
  - [x] ✅ Root cause: Missing removeListener calls

### Phase 2: Fix
- [x] ✅ **Write failing test**
  - [x] ✅ Test that listeners are removed after use
  - [x] ✅ Test that memory doesn't grow unbounded
- [x] ✅ **Implement fix**
  - [x] ✅ Add removeListener calls in cleanup paths
  - [x] ✅ Add WeakMap for listener tracking
  - [x] ✅ Add automated cleanup timer
- [x] ✅ **Verify fix with profiling**
  - [x] ✅ Run service for 4 hours
  - [x] ✅ Confirm memory stays flat
  - [x] ✅ No OOM crashes

### Phase 3: Deploy
- [x] ✅ **Deploy to staging**
  - [x] ✅ Monitor for 2 hours
  - [x] ✅ Verify no issues
- [x] ✅ **Deploy to production**
  - [x] ✅ Gradual rollout (10% → 50% → 100%)
  - [x] ✅ Monitor memory metrics
  - [x] ✅ Confirm leak resolved

## Success Criteria

- [x] Memory leak identified with profiling
- [x] Root cause documented
- [x] Fix implemented with tests
- [x] Memory usage stable over 4+ hours
- [x] Deployed to production
- [x] No OOM crashes observed
- [x] GitHub issue #287 closed

## Technical Decisions

### Decision 1: WeakMap vs Manual Tracking

**Context**: How to track listeners for cleanup

**Options Considered**:
1. WeakMap - Automatic garbage collection
2. Manual tracking with cleanup timer
3. Immediate removeListener calls only

**Decision**: WeakMap + cleanup timer because:
- WeakMap prevents memory leaks even if cleanup fails
- Cleanup timer provides defense-in-depth
- Immediate calls might be missed in error paths

**Date**: 2026-02-15

## Notes & Updates

### 2026-02-15 10:00
- Started investigation
- Memory leak confirmed locally

### 2026-02-15 14:00
- Heap profiling complete
- Found EventListener instances growing
- Root cause: Missing removeListener in error handlers

### 2026-02-15 16:00
- Fix implemented
- Tests passing
- Profiling shows flat memory usage

### 2026-02-16 09:00
- Deployed to staging
- Monitoring looks good

### 2026-02-16 14:00
- Production rollout complete
- Memory usage stable
- GitHub issue #287 closed
- Plan complete!
```

---

## Frequently Asked Questions

### General Questions

**Q: Do I need the hooks daemon to use Plan Workflow?**
A: No. The plan workflow concept (numbered folders, PLAN.md structure) works with any editor and git. The hooks daemon adds automation (enforcement, context preservation) but isn't required.

**Q: Can I use plan workflow with other AI assistants (ChatGPT, etc.)?**
A: Yes. The plan structure is tool-agnostic. Only the handlers are specific to Claude Code with the hooks daemon.

**Q: How do I migrate existing work to plan workflow?**
A: Create plans for active work, backfill for important historical work. Start fresh rather than migrating everything.

**Q: What if my team prefers Jira/Linear/etc?**
A: Plans complement issue trackers. Use trackers for team coordination, plans for detailed implementation tracking. Link them together.

### Technical Questions

**Q: How do I handle cross-plan dependencies?**
A: Document in Dependencies section. If tightly coupled, consider merging plans.

**Q: Can I have multiple active plans simultaneously?**
A: Yes, but limit to 2-3 per person to maintain focus.

**Q: Should I create a plan for documentation updates?**
A: Only if substantial (> 2 hours). Simple doc fixes don't need plans.

**Q: How do I handle plans that span sprints/milestones?**
A: Break into multiple plans (one per sprint) or use phases within a single plan.

### Workflow Questions

**Q: What if I need to pause a plan?**
A: Mark status as "⏸️ On Hold", add note explaining why, update when resuming.

**Q: How do I handle abandoned/outdated plans?**
A: Mark as "Cancelled" with reason, move to Completed/ (cancelled plans still preserved).

**Q: Should I update completed plans with new information?**
A: No. Completed plans are historical record. Create new plan if work resumes.

**Q: How detailed should task breakdowns be?**
A: Detailed enough that someone else (or future you) can understand and continue the work.

---

## Conclusion

Plan Workflow provides structured planning through:

- **Numbered folders** for organization and traceability
- **Standardized PLAN.md** for consistency
- **Task status tracking** for visibility
- **Archive preservation** for knowledge retention
- **Handler support** (optional) for automation

**Key Benefits**:

- Clearer thinking through explicit planning
- Context preservation across interruptions
- Better collaboration between people and AI
- Historical knowledge base for the project

**Getting Started**:

1. Create CLAUDE/Plan/ directory structure
2. Copy plan template
3. Create your first plan
4. Install hooks daemon (optional) for automation
5. Iterate and adapt to your workflow

**Next Steps**:

- Read [Handler Development Guide](../CLAUDE/HANDLER_DEVELOPMENT.md) for custom handlers
- See [Architecture Documentation](../CLAUDE/ARCHITECTURE.md) for system design
- Review example plans in [CLAUDE/Plan/Completed/](../CLAUDE/Plan/Completed/)

---

**Version**: 2.0
**Last Updated**: 2026-02-17
**Maintained By**: Claude Code Hooks Daemon Contributors
**License**: MIT
