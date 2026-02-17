# Workflows

Repeatable processes that survive conversation compaction through persistent state files.

**Version**: 1.0
**Status**: Production-ready
**License**: MIT

---

## Important Distinction

**Workflows vs Plans** - These are two completely separate concepts:

- **Workflows** (this document): Repeatable processes (like `page-orchestration`, `qa-skill`, `release`) that survive conversation compaction through state files in `./untracked/workflow-state/`.
- **Plans** (see [PLAN_SYSTEM.md](PLAN_SYSTEM.md)): Numbered folders (`00001-`, `00002-`, etc.) for tracking development work. Each plan has a `PLAN.md` with tasks and goals.

This document covers **Workflows only**. For plan documentation, see [PLAN_SYSTEM.md](PLAN_SYSTEM.md).

---

## What is a Workflow?

A **workflow** is structured sub-agent orchestration with:

- **Clearly defined steps** - Sequential phases with specific objectives
- **Gates** - Validation checkpoints between phases
- **Compaction resilience** - Must survive multiple conversation compaction cycles
- **State tracking** - Persistent state file tracking progress and context
- **Required reading** - Documentation that must be read at workflow start/resume

Workflows are NOT ad-hoc task sequences. They are formal, documented processes with explicit phase tracking.

**Key principle**: Workflows are REPEATABLE. You might run the release workflow 100 times. Each execution is independent but follows the same phases.

---

## Workflow Types

| Type | Description | Phases | Example |
|------|-------------|--------|---------|
| `release` | Release process workflow | 10+ | Version detection → Changelog → Opus review → QA → Acceptance testing → Commit/Push/Tag |
| `custom` | Custom workflows | Variable | Any structured process |

**Note**: The workflow system was originally developed for the Edmonds Commerce site project with workflows like `page-orchestration`, `qa-skill`, `sitemap-skill`, `eslint-skill`. This hooks daemon project is adopting the workflow system for its release process.

---

## State File Lifecycle

### 1. Workflow START

**When**: Agent begins a formal workflow

**Action**: Create state file

**Location**: `./untracked/workflow-state/{workflow-name}/state-{workflow-name}-{start-time}.json`

**Example**:
```bash
./untracked/workflow-state/release/state-release-20260217_143052.json
```

**Agent Responsibility**: Create state file at workflow start with:
- Workflow name and type
- Initial phase (1/total)
- Required reading list (with @ syntax)
- Context variables (version number, target branch, etc.)
- Key reminders

### 2. Phase Transitions

**When**: Moving from one phase to another

**Action**: UPDATE existing state file (same file, preserve `created_at`)

**Agent Responsibility**: Update state file with:
- New phase number and name
- Updated status
- Any new context or reminders

### 3. PreCompact Hook

**When**: Before conversation compaction occurs

**Action**: PreCompact hook UPDATES existing state file

**How it works**:
1. Hook detects active workflow (checks CLAUDE.local.md or active plans)
2. Extracts current workflow state
3. Looks for existing state file matching workflow name
4. **If found**: UPDATES file with current state (preserves `created_at`)
5. **If not found**: CREATES new file with start_time timestamp

**No agent action needed** - hook handles this automatically.

### 4. Compaction

**When**: Conversation context window fills up

**What happens**: State file survives (filesystem-based, not in conversation)

### 5. SessionStart Hook (Post-Compaction)

**When**: Session resumes after compaction

**Action**: SessionStart hook READS state file (DOES NOT DELETE)

**How it works**:
1. Hook finds all state files in `./untracked/workflow-state/*/`
2. Reads most recently modified state file
3. Provides guidance to agent with:
   - Workflow name and current phase
   - **REQUIRED READING** with @ syntax (forces file reading)
   - Key reminders
   - Context variables
4. **DOES NOT DELETE** - file persists

**Agent sees guidance** with workflow context and must read required files.

### 6. Continue Workflow

**When**: Agent continues working through phases

**Action**: Agent continues updating state file at phase transitions

**Agent Responsibility**: Keep state file current.

### 7. Workflow COMPLETE

**When**: All phases complete, workflow finished

**Action**: DELETE state file

**Agent Responsibility**: Remove state file when workflow is done.

**Example**:
```bash
rm -rf ./untracked/workflow-state/release/
```

---

## State File Format

### Required Fields

```json
{
  "workflow": "Release Process",
  "workflow_type": "release",
  "phase": {
    "current": 4,
    "total": 10,
    "name": "QA Verification Gate",
    "status": "in_progress"
  },
  "required_reading": [
    "@CLAUDE/development/RELEASING.md",
    "@.claude/skills/release/SKILL.md"
  ],
  "context": {
    "version": "2.14.0",
    "bump_type": "minor"
  },
  "key_reminders": [
    "QA gate is BLOCKING - release cannot proceed if QA fails",
    "Acceptance testing gate follows QA verification"
  ],
  "created_at": "2025-02-17T14:30:52.123456Z"
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | string | ✅ | Human-readable workflow name |
| `workflow_type` | enum | ✅ | Machine-readable type (see Workflow Types above) |
| `phase.current` | integer | ✅ | Current phase number (1-indexed) |
| `phase.total` | integer | ✅ | Total number of phases |
| `phase.name` | string | ✅ | Human-readable phase name |
| `phase.status` | enum | ✅ | `not_started` \| `in_progress` \| `completed` \| `blocked` |
| `required_reading` | array | ✅ | File paths with **@ prefix** to force reading |
| `context` | object | ⬜ | Flexible key-value pairs (workflow-specific) |
| `key_reminders` | array | ⬜ | Critical rules that must survive compaction |
| `created_at` | string | ✅ | ISO 8601 timestamp (preserved across updates) |

### @ Syntax for REQUIRED READING

**CRITICAL**: All file paths in `required_reading` must use **@ prefix**.

**Why**: The @ syntax forces agents to actually READ files, not just be contextually aware of them.

**Examples**:
- `@CLAUDE/development/RELEASING.md` - Forces reading
- `@.claude/skills/release/SKILL.md` - Forces reading
- `@CLAUDE/AcceptanceTests/GENERATING.md` - Forces reading

**When agent resumes after compaction**: SessionStart hook provides these files with @ syntax in guidance, ensuring agent reads them.

---

## Directory Structure

```
./untracked/workflow-state/
├── release/
│   └── state-release-20260217_143052.json
└── custom-workflow/
    └── state-custom-workflow-20260217_160000.json
```

**Benefits**:
- One directory per workflow (clean organization)
- Multiple concurrent workflows supported
- Easy to find and manage workflow state
- Safe workflow name sanitization (spaces → hyphens)

---

## Workflow Detection

The PreCompact hook detects active workflows using:

### Method 1: CLAUDE.local.md Markers

If `CLAUDE.local.md` exists and contains:
- `"WORKFLOW STATE"` marker
- `"workflow:"` field
- `"Phase:"` field

**Example**:
```markdown
# Current Workflow State

Workflow: Release Process
Phase: 4/10 - QA Verification Gate

@CLAUDE/development/RELEASING.md
@.claude/skills/release/SKILL.md
```

### Method 2: Active Plans

If `CLAUDE/Plan/*/PLAN.md` exists with:
- `🔄 In Progress` status
- `"phase"` or `"workflow"` keywords in content

**Generic Detection**: The question is "Are you in a formal workflow?" - NOT a hardcoded whitelist.

---

## Compaction Resilience

### The Problem

Conversation compaction loses:
- Procedural workflow details (phase tracking)
- Document references (which files to read)
- Conditional logic (e.g., "skip Phase 3" becomes vague)
- Context state (version numbers, target branches)

**Example failure**: Agent hallucinates "skip Phase 3 because no upgrade guide" when guide exists.

### The Solution

**State file + hooks** = Compaction resilience

1. **PreCompact hook** saves complete workflow state to file BEFORE compaction
2. **Compaction** happens (conversation cleared)
3. **State file survives** (filesystem, not conversation)
4. **SessionStart hook** reads state file and provides guidance with @ syntax
5. **Agent reads required docs** (forced by @ syntax)
6. **Workflow continues** without loss of context

### Multiple Compaction Cycles

State files persist across MULTIPLE compactions:
- PreCompact updates existing file (cycle 1)
- Compaction happens (cycle 1)
- SessionStart reads file (cycle 1)
- Work continues, PreCompact updates file again (cycle 2)
- Compaction happens (cycle 2)
- SessionStart reads file (cycle 2)
- etc.

**Lossless preservation** across unlimited compaction cycles.

---

## Agent Responsibilities

### At Workflow Start

1. **Create state file** in `./untracked/workflow-state/{workflow-name}/`
2. Use sanitized workflow name (lowercase, hyphens, no spaces)
3. Include start_time timestamp in filename
4. Populate all required fields
5. Use **@ syntax** for all `required_reading` paths

### During Workflow

1. **Update state file** at each phase transition
2. Keep `phase.current`, `phase.name`, `phase.status` current
3. Preserve original `created_at` timestamp
4. Add context or reminders as needed

### After Compaction (SessionStart Guidance)

1. **Acknowledge hook guidance**: "✅ Workflow restored: {workflow}, Phase {current}/{total}"
2. **Read ALL required files** using @ syntax
3. **Confirm understanding** of current phase and context
4. **Do NOT proceed** with assumptions or hallucinated logic

### At Workflow Completion

1. **Delete state file** and directory:
   ```bash
   rm -rf ./untracked/workflow-state/{workflow-name}/
   ```
2. Clean up after yourself

---

## Example: Release Workflow

### Start (Phase 1 - Pre-Release Validation)

```json
{
  "workflow": "Release Process",
  "workflow_type": "release",
  "phase": {"current": 1, "total": 10, "name": "Pre-Release Validation", "status": "in_progress"},
  "required_reading": [
    "@CLAUDE/development/RELEASING.md",
    "@.claude/skills/release/SKILL.md"
  ],
  "context": {"version": "2.14.0", "bump_type": "minor"},
  "key_reminders": ["All validation checks must pass before proceeding"],
  "created_at": "2026-02-17T14:30:52Z"
}
```

### Update (Phase 7 - QA Verification Gate)

```json
{
  "workflow": "Release Process",
  "workflow_type": "release",
  "phase": {"current": 7, "total": 10, "name": "QA Verification Gate", "status": "in_progress"},
  "required_reading": [
    "@CLAUDE/development/RELEASING.md",
    "@.claude/skills/release/SKILL.md"
  ],
  "context": {
    "version": "2.14.0",
    "bump_type": "minor",
    "changelog_generated": true,
    "opus_approved": true
  },
  "key_reminders": [
    "QA gate is BLOCKING - must run ./scripts/qa/run_all.sh",
    "If ANY check fails, ABORT release immediately"
  ],
  "created_at": "2026-02-17T14:30:52Z"
}
```

---

## Handlers Supporting Workflows

### 1. WorkflowStatePreCompactHandler

**Event**: PreCompact
**Priority**: N/A (PreCompact doesn't use priorities)
**Type**: Non-blocking (state preservation)

**Purpose**: Preserves workflow state before context compaction.

**What it does**:
- Detects if workflow active (via CLAUDE.local.md or active plans)
- Extracts workflow state from conversation
- Sanitizes workflow name for directory/filename
- Looks for existing state file matching workflow name
- If found: UPDATES existing file (preserves `created_at`)
- If not found: CREATES new file with start_time timestamp
- Always returns allow (never blocks compaction)

**Location**: `.claude/hooks/controller/handlers/pre_compact/workflow_state_pre_compact_handler.py`

### 2. WorkflowStateRestorationHandler

**Event**: SessionStart (source=compact)
**Priority**: Default
**Type**: Non-blocking (advisory)

**Purpose**: Restores workflow state after compaction.

**What it does**:
- Finds all state files in `./untracked/workflow-state/*/`
- If none: Returns allow, no guidance
- If found: Sorts by modification time (most recent first)
- Reads most recently modified state file
- Builds guidance message with:
  - Workflow name and phase info
  - **REQUIRED READING** (@ syntax)
  - Key reminders
  - Context variables
  - ACTION REQUIRED section
- **DOES NOT DELETE** state file
- Returns allow with guidance context

**Location**: `.claude/hooks/controller/handlers/session_start/workflow_state_restoration_handler.py`

**Example guidance**:
```
⚠️ WORKFLOW RESTORED AFTER COMPACTION ⚠️

Workflow: Release Process
Type: release
Phase: 7/10 - QA Verification Gate (in_progress)

REQUIRED READING (read ALL now with @ syntax):
@CLAUDE/development/RELEASING.md
@.claude/skills/release/SKILL.md

CONTEXT:
- version: 2.14.0
- bump_type: minor
- opus_approved: true

KEY REMINDERS:
- QA gate is BLOCKING - must run ./scripts/qa/run_all.sh
- If ANY check fails, ABORT release immediately

ACTION REQUIRED:
1. Read ALL files listed above using @ syntax
2. Confirm understanding of workflow phase
3. DO NOT proceed with assumptions or hallucinated logic
```

---

## Creating a Workflow

### Step 1: Define Workflow Phases

Document your workflow phases in a dedicated document (e.g., `CLAUDE/development/MY_WORKFLOW.md`):

```markdown
# My Workflow

## Phases

1. **Preparation** - Gather inputs and validate prerequisites
2. **Execution** - Perform main work
3. **Verification** - Validate results
4. **Completion** - Clean up and finalize
```

### Step 2: Create Workflow State at Start

When starting a workflow:

```bash
# Create state directory
mkdir -p ./untracked/workflow-state/my-workflow

# Create state file
cat > ./untracked/workflow-state/my-workflow/state-my-workflow-$(date +%Y%m%d_%H%M%S).json << 'EOF'
{
  "workflow": "My Custom Workflow",
  "workflow_type": "custom",
  "phase": {
    "current": 1,
    "total": 4,
    "name": "Preparation",
    "status": "in_progress"
  },
  "required_reading": [
    "@CLAUDE/development/MY_WORKFLOW.md"
  ],
  "context": {},
  "key_reminders": [],
  "created_at": "2026-02-17T14:30:52Z"
}
EOF
```

### Step 3: Update State at Phase Transitions

When moving to next phase, update the existing state file:

```bash
# Update phase number and name in the same file
# Preserve created_at timestamp
```

### Step 4: Delete State at Completion

When workflow completes:

```bash
rm -rf ./untracked/workflow-state/my-workflow/
```

---

## Troubleshooting

### State file not created?

**Check**:
1. Is workflow formally documented?
2. Does CLAUDE.local.md contain workflow markers?
3. Check `.claude/hooks/controller/tests/` for test examples

### State file not updated after phase transition?

**Agent responsibility**: Update the file manually when moving between phases.

### Workflow lost after compaction?

**Check**:
1. Was state file created before compaction?
2. Check `./untracked/workflow-state/{workflow-name}/`
3. Did SessionStart hook provide guidance?
4. Did agent read @ prefixed files?

### Multiple state files accumulating?

**Normal if multiple workflows active**. Each workflow gets its own directory.

**Cleanup**: Delete state file when workflow completes.

---

## Related Documentation

- **Handler Development**: `CLAUDE/HANDLER_DEVELOPMENT.md` - How handlers work
- **Architecture**: `CLAUDE/ARCHITECTURE.md` - System design
- **Plan System**: [PLAN_SYSTEM.md](PLAN_SYSTEM.md) - Development work tracking (different from workflows)

---

**Document Version**: 1.0
**Last Updated**: 2026-02-17
**Status**: Production-ready
