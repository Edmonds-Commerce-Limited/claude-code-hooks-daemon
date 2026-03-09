# Bug Report: `validate_plan_number` Handler Ignores `track_plans_in_project` Config

**Severity**: HIGH — Produces incorrect plan number warnings for every plan operation in projects using non-default plan directories.

**Daemon Version**: 2.10.0 (installed)
**Affected Handler**: `validate_plan_number` (PreToolUse)
**Config Key**: `handlers.pre_tool_use.validate_plan_number`

## Summary

The `validate_plan_number` daemon handler hardcodes `"CLAUDE/Plan"` (singular) for its directory scan, ignoring the `track_plans_in_project` config option. Projects that configure `CLAUDE/Plans` (plural) — or any other custom path — get incorrect plan number validation warnings on every Write and Bash mkdir operation that touches plan folders.

## Root Cause

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/validate_plan_number.py`

### Problem 1: Hardcoded scan path (line 188)

```python
def _get_highest_plan_number(self) -> int:
    plan_root = self.workspace_root / "CLAUDE/Plan"  # ← HARDCODED
```

This scans `CLAUDE/Plan/` which doesn't exist in this project. The directory is `CLAUDE/Plans/`. Because the path doesn't exist, `_get_highest_plan_number()` returns `0`, making the handler think the next plan should be `00001`.

### Problem 2: No config integration

Unlike its sibling handlers, `validate_plan_number` does NOT:
- Declare `_track_plans_in_project` attribute
- Use `shares_options_with` to inherit config from `markdown_organization`
- Read any config options at all

**Compare with `plan_number_helper`** (which works correctly):

```python
class PlanNumberHelperHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            ...
            shares_options_with="markdown_organization",  # ← Inherits config
        )
        self._track_plans_in_project: str | None = None  # ← Reads from config
```

### Problem 3: Hardcoded error messages (lines 144-173)

All error message strings reference `CLAUDE/Plan` (singular):

```python
error_message = f"""
PLAN NUMBER INCORRECT

You are creating: CLAUDE/Plan/{plan_number}-{plan_name}/        # ← hardcoded
Highest existing plan: {highest}
Expected next number: {expected_number}

BOTH active plans (CLAUDE/Plan/) AND completed plans (CLAUDE/Plan/Completed/) were checked.  # ← hardcoded

...
mkdir -p CLAUDE/Plan/{expected_number}-{plan_name}              # ← hardcoded

See: CLAUDE/Plan/CLAUDE.md for full instructions                # ← hardcoded
"""
```

## Observed Behavior

### Project config (`.claude/hooks-daemon.yaml`):
```yaml
handlers:
  pre_tool_use:
    validate_plan_number:
      enabled: true
      priority: 30
    plan_number_helper:
      enabled: true
      priority: 30
      options:
        track_plans_in_project: CLAUDE/Plans    # ← plural
    markdown_organization:
      enabled: true
      priority: 35
      options:
        track_plans_in_project: CLAUDE/Plans    # ← plural
```

### Actual project structure:
```
CLAUDE/Plans/
├── 00036-operational-readiness/
├── 00064-frontend-code-quality-audit/
├── ...
├── 00089-form-validation-overhaul-rhf-zod/
├── 00090-code-review-phase4-rhf-migration/   ← just created
├── README.md
└── completed/
    ├── 00001-initial-market-research-and-prd/
    ├── ...
    └── 00081-repository-interfaces-phpstan-rules-migration/
```

### What happens when creating plan 00090:

**`plan_number_helper`** (CORRECT): Reads `track_plans_in_project: CLAUDE/Plans` from config, scans `CLAUDE/Plans/` + `CLAUDE/Plans/completed/`, finds highest = 00089, says next = 00090. Works correctly.

**`validate_plan_number`** (BROKEN): Ignores config, scans hardcoded `CLAUDE/Plan/` which doesn't exist, finds highest = 0, says next = 00001. Outputs:

```
PLAN NUMBER INCORRECT

You are creating: CLAUDE/Plan/90-code-review-phase4-rhf-migration/
Highest existing plan: 0
Expected next number: 1

BOTH active plans (CLAUDE/Plan/) AND completed plans (CLAUDE/Plan/Completed/) were checked.
```

This is completely wrong — the handler scanned the wrong directory entirely.

## Impact

1. **Every plan operation triggers a false warning** — Write to any file under `CLAUDE/Plans/NNNNN-*/` produces the incorrect advisory message
2. **The warning is actively misleading** — It says "use plan number 00001" when the real next number is 00090+
3. **Error messages reference wrong paths** — Suggests `mkdir -p CLAUDE/Plan/00001-...` which is the wrong directory
4. **Confuses LLMs** — Claude sees the warning and may try to "fix" the plan number, potentially creating duplicate plans in the wrong directory

## Architectural Issue: No Single Source of Truth for Plan Workflow Config

Beyond the immediate bug, there is a deeper design problem: **plan workflow configuration is fragmented across multiple handlers with no single source of truth**.

Currently, plan-related config is scattered:

| Handler | How it gets plan path | Config location |
|---------|----------------------|-----------------|
| `markdown_organization` | Direct `options.track_plans_in_project` | Own config section |
| `plan_number_helper` | `shares_options_with: "markdown_organization"` | Inherited from markdown_organization |
| `validate_plan_number` | **Hardcoded** `"CLAUDE/Plan"` | None — ignores config entirely |
| `plan_workflow` | Unknown | Needs audit |
| `plan_completion_advisor` | Unknown | Needs audit |
| `task_tdd_advisor` | Unknown | Needs audit |

This means:
1. **Every handler that touches plans must independently know where to find config** — some inherit, some hardcode, some have their own options
2. **Adding a new plan-aware handler requires knowing which handler to `shares_options_with`** — non-obvious, easy to get wrong (as this bug proves)
3. **Changing the plan directory requires updating multiple config sections** — currently `plan_number_helper.options` AND `markdown_organization.options` must both be set

### Recommended: Top-level `plan_workflow` config section

All plan-related handlers should read from a single top-level config section:

```yaml
# Single source of truth for ALL plan-aware handlers
plan_workflow:
  plan_directory: "CLAUDE/Plans"           # Used by all handlers
  completed_directory: "CLAUDE/Plans/completed"  # Derived or explicit
  plan_workflow_docs: "CLAUDE/PlanWorkflow.md"
  plan_file_name: "PLAN.md"

handlers:
  pre_tool_use:
    validate_plan_number:
      enabled: true
      # No plan path config needed — reads from plan_workflow section
    plan_number_helper:
      enabled: true
      # No plan path config needed — reads from plan_workflow section
    markdown_organization:
      enabled: true
      # No plan path config needed — reads from plan_workflow section
```

Every plan-aware handler would read `config.plan_workflow.plan_directory` instead of having its own copy or hardcoding a default. One config change updates all handlers.

---

## Proposed Fix (Immediate)

### Option A: Add `shares_options_with` (recommended — minimal change)

```python
class ValidatePlanNumberHandler(Handler):
    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.VALIDATE_PLAN_NUMBER,
            priority=Priority.VALIDATE_PLAN_NUMBER,
            terminal=False,
            tags=[...],
            shares_options_with="markdown_organization",  # ← ADD THIS
        )
        self.workspace_root = ProjectContext.project_root()
        self._track_plans_in_project: str | None = None  # ← ADD THIS
```

Then update `_get_highest_plan_number()`:

```python
def _get_highest_plan_number(self) -> int:
    # Use configured path, fall back to default
    plan_dir = self._track_plans_in_project or ProjectPath.PLAN_DIR
    plan_root = self.workspace_root / plan_dir
    ...
```

And update error messages to use the configured path instead of hardcoded `CLAUDE/Plan`.

### Option B: Add dedicated config option

Add `track_plans_in_project` as a direct option on `validate_plan_number` in the config schema, same as `plan_number_helper`.

## Affected Handlers Summary

| Handler | Uses config `track_plans_in_project`? | Scan path | Status |
|---------|--------------------------------------|-----------|--------|
| `markdown_organization` | Yes (direct option) | Configurable | OK |
| `plan_number_helper` | Yes (via `shares_options_with`) | Configurable | OK |
| `validate_plan_number` | **No — hardcoded** | `CLAUDE/Plan` only | **BUG** |
| `plan_completion_advisor` | Unknown (not checked) | Unknown | Needs check |
| `plan_workflow` | Unknown (not checked) | Unknown | Needs check |

## Additional Hardcoded References

The following files also contain hardcoded `CLAUDE/Plan` (singular) references that may need updating if projects use custom paths:

| File | Line(s) | Context |
|------|---------|---------|
| `constants/paths.py` | 51-52 | `PLAN_DIR = "CLAUDE/Plan"`, `PLAN_COMPLETED_DIR = "CLAUDE/Plan/Completed"` |
| `constants/paths.py` | 68 | `PLAN_README = "CLAUDE/Plan/README.md"` |
| `daemon/init_config.py` | 147-148 | Default config template |
| `handlers/utils/plan_numbering.py` | 24, 33, 36, 39 | Docstring examples only |

The `constants/paths.py` defaults are fine as fallbacks — the bug is that `validate_plan_number` doesn't check config before falling back to the constant.

## Workaround

Disable the `validate_plan_number` handler in project config:

```yaml
handlers:
  pre_tool_use:
    validate_plan_number:
      enabled: false    # ← Disable broken handler
```

The `plan_number_helper` handler (which works correctly) provides equivalent functionality for bash command interception. The project-level `validate_plan_number_handler.py` (in `.claude/hooks/controller/`) also provides correct validation using the right path.

## Steps to Reproduce

1. Install hooks daemon in a project that uses `CLAUDE/Plans/` (plural)
2. Configure `track_plans_in_project: CLAUDE/Plans` in `plan_number_helper` and `markdown_organization`
3. Create a plan folder: `mkdir -p CLAUDE/Plans/00002-test/`
4. Write a file: Write to `CLAUDE/Plans/00002-test/PLAN.md`
5. Observe the `validate_plan_number` handler warning incorrectly says "Expected next number: 00001"

## Environment

- Hooks daemon: v2.10.0
- Python: 3.11
- Platform: Linux (Podman container)
- Project plan directory: `CLAUDE/Plans/` (89 active + completed plans)
