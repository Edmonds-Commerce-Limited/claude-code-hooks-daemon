# Plan 86: Plan Redirect System Overhaul

## Context

The plan redirect system has a major UX flaw: ExitPlanMode shows a redirect stub instead of plan content. Additionally, plan config is scattered across handler options with no central source of truth, and there's no enforcement that Claude Code's `plansDirectory` matches the daemon config.

**Verified**: `plansDirectory: "./CLAUDE/Plan"` in `.claude/settings.json` works - Claude Code writes plan files directly to project folder.

## Phases

### Phase 1: UX Fix (plansDirectory + Handler ALLOW)

**Goal**: User sees full plan content during ExitPlanMode approval.

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`

1. Update `is_planning_mode_write()` to detect flat file writes to `CLAUDE/Plan/*.md` (not in subfolder)
2. Update `handle_planning_mode_write()`:
   - Scan `CLAUDE/Plan/` + `Completed/` for highest plan number → NNNNN+1
   - Create `CLAUDE/Plan/{NNNNN}-{random-words}/PLAN.md` with content
   - Return **ALLOW** (flat file stays for ExitPlanMode to read)
   - Context: "Plan folder created: CLAUDE/Plan/NNNNN-random-words/"
3. Handle Edit tool: sync edits to numbered folder's PLAN.md, return ALLOW
4. Remove redirect stub logic and rename instructions
5. Ensure `plansDirectory: "./CLAUDE/Plan"` committed in `.claude/settings.json`

### Phase 2: Top-Level Plan Workflow Config + Migration

**Goal**: Plan config becomes a first-class top-level section, not handler options.

**New config structure**:
```yaml
plan_workflow:
  enabled: true
  directory: "CLAUDE/Plan"
  workflow_docs: "CLAUDE/PlanWorkflow.md"
  enforce_claude_code_sync: true
```

**Files**:
- `src/claude_code_hooks_daemon/config/models.py` - Add `PlanWorkflowConfig` model + add to root `Config`
- `src/claude_code_hooks_daemon/config/models.py` - Add migration validator: old handler options → new top-level section
- `.claude/hooks-daemon.yaml` - Add `plan_workflow:` section, remove from handler options
- All plan handlers - Read from top-level config instead of handler options

**Migration** (in `Config` model validator):
```python
@model_validator(mode="after")
def migrate_plan_config(self) -> Self:
    """Migrate handler-level track_plans_in_project to top-level plan_workflow."""
    # If old format detected and new format missing:
    #   1. Create plan_workflow from handler options
    #   2. Clear handler options
    # If both exist: top-level wins, warn about stale handler options
```

**Handler changes**:
- `markdown_organization` - Read `plan_workflow.directory` instead of `_track_plans_in_project`
- `plan_number_helper` - Read from `plan_workflow` instead of inherited options
- `validate_plan_number` - Read from `plan_workflow` instead of inherited options
- Remove `shares_options_with` pattern for plan config

**Config access pattern**: Handlers receive plan_workflow config via a new mechanism (e.g., injected during registry loading, or read from a shared config accessor).

### Phase 3: Hard Sync Enforcement (DENY)

**Goal**: Plan writes are BLOCKED if `plansDirectory` in `.claude/settings.json` doesn't match `plan_workflow.directory`.

**Enforcement point**: `markdown_organization` handler, before processing any plan write:

1. Read `.claude/settings.json` → extract `plansDirectory`
2. Compare with `plan_workflow.directory` from daemon config
3. If missing or mismatched → **DENY** with fix instructions:
   ```
   BLOCKED: plansDirectory in .claude/settings.json must be set to "./CLAUDE/Plan"
   to match hooks daemon plan_workflow.directory.

   Fix: Add to .claude/settings.json:
     "plansDirectory": "./CLAUDE/Plan"
   Then restart session.
   ```
4. If in sync → proceed with normal plan write handling

**Edge cases**:
- `plansDirectory` not set at all → DENY (must be explicitly set)
- `plansDirectory` set but different path → DENY (must match)
- `plan_workflow.enabled: false` → skip enforcement entirely
- `.claude/settings.json` doesn't exist → DENY with creation instructions

### Phase 4: QA & Verification

1. `./scripts/qa/run_all.sh` → ALL CHECKS PASSED
2. Daemon restart verification
3. E2E test: plan mode → write → approval shows content → numbered folder exists
4. E2E test: remove plansDirectory → plan write blocked with clear message
5. E2E test: config migration from old format works

## Key Files

| File | Phase | Changes |
|------|-------|---------|
| `.claude/settings.json` | 1 | `plansDirectory: "./CLAUDE/Plan"` |
| `src/.../pre_tool_use/markdown_organization.py` | 1, 3 | ALLOW flow, numbered folders, sync enforcement |
| `src/.../config/models.py` | 2 | `PlanWorkflowConfig` model, migration validator |
| `.claude/hooks-daemon.yaml` | 2 | Top-level `plan_workflow:` section |
| `src/.../pre_tool_use/plan_number_helper.py` | 2 | Read from top-level config |
| `src/.../pre_tool_use/validate_plan_number.py` | 2 | Read from top-level config |
| `tests/...` | 1-3 | Tests for each phase |

## Verification

1. Plan mode assigns file under `./CLAUDE/Plan/` (not `~/.claude/plans/`)
2. ExitPlanMode shows full plan content
3. Numbered folder created alongside flat file
4. Config migration preserves old settings
5. Plan writes blocked when plansDirectory out of sync
6. Daemon restarts, full QA passes
