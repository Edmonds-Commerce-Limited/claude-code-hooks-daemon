# Plan: Reminder Pseudo-Event System with Adaptive Triggers

## Context

The pseudo-event system currently supports **fixed-frequency triggers** (N/D notation: "fire N times every D events"). The nitpick pseudo-event uses this to scan transcripts every 5th PreToolUse.

**Problem**: The workflow state system only injects reminders at session start (after compaction). During normal work, the workflow state is forgotten and never kept up to date.

**Solution**: Extend pseudo-events with **adaptive-frequency triggers** where the check interval changes based on whether a reminder was actually fired:
- No reminder needed → check again in `check_interval` events (e.g., 4)
- Reminder fired → wait `cooldown_interval` events before next check (e.g., 8)

First consumer: **workflow reminder** that periodically checks for active workflow state files and reminds the agent about phase, key reminders, and prompts to update state.

---

## Phase 1: AdaptiveTrigger Dataclass (TDD)

**Goal**: New frozen dataclass alongside existing `PseudoEventTrigger`.

**File**: `src/claude_code_hooks_daemon/core/pseudo_event.py`
**Tests**: `tests/unit/core/test_pseudo_event.py`

```python
@dataclass(frozen=True, slots=True)
class AdaptiveTrigger:
    event_type: EventType
    check_interval: int       # Events between checks (no reminder case)
    cooldown_interval: int    # Events to wait after firing a reminder

    def __post_init__(self) -> None:
        # Validate both > 0
```

Add type alias: `Trigger = PseudoEventTrigger | AdaptiveTrigger`

**Tests**: creation, frozen immutability, validation (positive intervals), from_dict parsing.

---

## Phase 2: Extend Config Parsing for Dict Triggers

**Goal**: `PseudoEventConfig.from_dict()` accepts both string triggers (fixed) and dict triggers (adaptive).

**File**: `src/claude_code_hooks_daemon/core/pseudo_event.py` (lines 114-142)

Current line 134 assumes all triggers are strings:
```python
triggers = tuple(PseudoEventTrigger.from_string(s) for s in trigger_strs)
```

Change to dispatch on type:
- `str` → `PseudoEventTrigger.from_string(s)` (existing)
- `dict` → `AdaptiveTrigger(event_type=..., check_interval=..., cooldown_interval=...)` (new)

Update type annotation: `triggers: tuple[PseudoEventTrigger | AdaptiveTrigger, ...]`

**Config format for adaptive triggers**:
```yaml
triggers:
  - event_type: pre_tool_use
    check_interval: 4
    cooldown_interval: 8
```

**Tests**: dict trigger parsing, mixed string+dict triggers, validation errors for missing fields.

---

## Phase 3: Adaptive Firing Logic in Dispatcher (TDD)

**Goal**: Extend `PseudoEventDispatcher` with threshold-based adaptive firing.

**File**: `src/claude_code_hooks_daemon/core/pseudo_event.py`

**New state** (add to `__slots__`):
```python
_adaptive_thresholds: dict[str, dict[str, dict[str, int]]]
# {session_id: {pseudo_event_name: {event_type_value: next_fire_at_count}}}
```

**Algorithm**:
1. On each matching event, increment counter (shared `_counters`)
2. For `AdaptiveTrigger`: check `counter >= threshold` (initial threshold = `check_interval`)
3. If threshold reached → call `_fire()` (setup + chain)
4. After fire: update threshold based on result:
   - Setup returned data (reminder fired) → `threshold = counter + cooldown_interval`
   - Setup returned None (no reminder) → `threshold = counter + check_interval`

**Key change in `check_and_fire()`** (line 209-217): dispatch based on trigger type:
```python
if isinstance(trigger, AdaptiveTrigger):
    result = self._check_and_fire_adaptive(registered, trigger, hook_input, session_id)
else:
    # existing fixed-frequency path
```

New method `_check_and_fire_adaptive()` combines should-fire check + threshold update (tightly coupled for adaptive triggers).

**Refactor**: Extract `_increment_counter()` from `_should_fire()` for reuse by adaptive path.

**Tests**: fires after check_interval, cooldown after producing data, check_interval after None, per-session independence, initial threshold behaviour.

---

## Phase 4: WorkflowReminderSetup (TDD)

**Goal**: Setup callable that checks for active workflow state files.

**Create**: `src/claude_code_hooks_daemon/pseudo_events/reminder.py`
**Tests**: `tests/unit/pseudo_events/test_reminder.py`
**Pattern**: Follow `NitpickSetup` at `pseudo_events/nitpick.py`

```python
class WorkflowReminderSetup:
    """Check ./untracked/workflow-state/ for active state files."""

    def __call__(self, hook_input: dict[str, Any], session_id: str) -> dict[str, Any] | None:
        # 1. Find state files in ./untracked/workflow-state/*/state-*.json
        # 2. If none found → return None (no active workflow)
        # 3. Read most recent state file (sorted by mtime)
        # 4. Return enriched hook_input with workflow_state, workflow_name,
        #    workflow_phase, key_reminders
```

Reuse `ProjectContext.project_root()` for workspace path.

**Tests**: no state dir → None, empty dir → None, valid state → enriched dict, corrupt JSON → None, multiple files → most recent, preserves original hook_input fields.

---

## Phase 5: WorkflowReminderHandler (TDD)

**Goal**: Advisory handler that formats workflow state into reminder context.

**Create**: `src/claude_code_hooks_daemon/handlers/reminder/workflow_reminder.py`
**Create**: `src/claude_code_hooks_daemon/handlers/reminder/__init__.py`
**Tests**: `tests/unit/handlers/reminder/test_workflow_reminder.py`
**Pattern**: Follow `HedgingLanguageNitpickHandler` at `handlers/nitpick/hedging_language.py`

- `matches()`: Check for `workflow_state` key in hook_input
- `handle()`: Build advisory context lines:
  - Active workflow name and type
  - Current phase (N/M - name - status)
  - Key reminders from state file
  - "Update workflow state if phase has changed"
- Returns `HookResult(decision=Decision.ALLOW, context=[...])`
- Non-terminal, advisory

**Tests**: init (ID, priority, terminal=False, tags), matches positive/negative, handle output with phase info, key reminders, update prompt.

---

## Phase 6: Constants and Registration

**Modify**: `src/claude_code_hooks_daemon/constants/handlers.py` - Add `WORKFLOW_REMINDER` HandlerIDMeta
**Modify**: `src/claude_code_hooks_daemon/constants/priority.py` - Add priority constant
**Modify**: `src/claude_code_hooks_daemon/core/__init__.py` - Export `AdaptiveTrigger`
**Modify**: `src/claude_code_hooks_daemon/daemon/controller.py` - Register in `_get_pseudo_event_setup_registry()`:
```python
"workflow_reminder": (
    WorkflowReminderSetup(),
    [WorkflowReminderHandler],
),
```

---

## Phase 7: Configuration

**Modify**: `.claude/hooks-daemon.yaml` - Add under `pseudo_events:`:
```yaml
  workflow_reminder:
    enabled: true
    triggers:
      - event_type: pre_tool_use
        check_interval: 4
        cooldown_interval: 8
    handlers:
      workflow_reminder:
        enabled: true
```

---

## Phase 8: Verification

1. Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` → RUNNING
2. Full QA: `./scripts/qa/run_all.sh` → ALL CHECKS PASSED
3. Daemon logs: no import errors
4. Regenerate docs: `$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs`

---

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| MODIFY | `src/claude_code_hooks_daemon/core/pseudo_event.py` | AdaptiveTrigger, config parsing, adaptive dispatcher |
| MODIFY | `src/claude_code_hooks_daemon/core/__init__.py` | Export AdaptiveTrigger |
| MODIFY | `src/claude_code_hooks_daemon/constants/handlers.py` | WORKFLOW_REMINDER HandlerIDMeta |
| MODIFY | `src/claude_code_hooks_daemon/constants/priority.py` | Priority constant |
| MODIFY | `src/claude_code_hooks_daemon/daemon/controller.py` | Register in setup registry |
| MODIFY | `.claude/hooks-daemon.yaml` | Add workflow_reminder config |
| MODIFY | `tests/unit/core/test_pseudo_event.py` | Adaptive trigger + dispatcher tests |
| CREATE | `src/claude_code_hooks_daemon/pseudo_events/reminder.py` | WorkflowReminderSetup |
| CREATE | `src/claude_code_hooks_daemon/handlers/reminder/__init__.py` | Package init |
| CREATE | `src/claude_code_hooks_daemon/handlers/reminder/workflow_reminder.py` | Handler |
| CREATE | `tests/unit/pseudo_events/test_reminder.py` | Setup tests |
| CREATE | `tests/unit/handlers/reminder/__init__.py` | Test package init |
| CREATE | `tests/unit/handlers/reminder/test_workflow_reminder.py` | Handler tests |

## Success Criteria

- AdaptiveTrigger is frozen, validated, works alongside existing PseudoEventTrigger
- Existing nitpick pseudo-event continues working unchanged (backwards compatible)
- Dispatcher correctly applies check_interval vs cooldown_interval based on setup result
- WorkflowReminderSetup reads state files, returns None when no active workflow
- WorkflowReminderHandler produces advisory context with phase info and update prompt
- 95%+ test coverage on all new code
- Daemon restarts successfully, full QA passes
