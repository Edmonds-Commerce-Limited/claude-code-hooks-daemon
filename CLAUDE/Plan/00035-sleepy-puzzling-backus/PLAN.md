# Plan: StatusLine Data Cache + Model-Aware Agent Team Advisor

## Context

Plan 00032 (Sub-Agent Orchestration) needs model-awareness: advise users to switch to Opus when they're about to use agent teams. But PreToolUse events don't include model info - only StatusLine events do.

**Root problem**: StatusLine events contain rich data (model, context %, workspace) but this data is siloed - other event handlers (PreToolUse, PostToolUse, SessionStart) can't access it.

**Solution**: Cache StatusLine data in daemon memory. Since the daemon is a persistent process (Unix socket server with shared DaemonController), StatusLine data cached in memory is naturally available to all handlers across all event types.

**Critical constraint**: The agent team advisor handler must be GENERIC - works on any project, no project-specific references.

---

## Part 1: StatusLine Data Cache (Infrastructure)

### Architecture

The daemon already has persistent state patterns:
- `DaemonController` (singleton, holds router + stats)
- `ProjectContext` (singleton, caches project paths)
- `DaemonStats` (accumulates metrics across requests)

**New**: Add `SessionState` - a lightweight cache for runtime session data from StatusLine events.

### Design

**New file**: `src/claude_code_hooks_daemon/core/session_state.py`

```python
@dataclass
class SessionState:
    """Cached runtime session data from StatusLine events.

    Populated by StatusLine event processing, readable by any handler.
    The daemon is a persistent process so this naturally persists across events.
    """
    model_id: str | None = None           # e.g., "claude-opus-4-6"
    model_display_name: str | None = None  # e.g., "Claude Opus 4.6"
    context_used_percentage: float = 0.0
    workspace_dir: str | None = None
    last_updated: float = 0.0             # timestamp

    def update_from_status_line(self, hook_input: dict) -> None:
        """Update cache from StatusLine event data."""
        model = hook_input.get("model", {})
        self.model_id = model.get("id")
        self.model_display_name = model.get("display_name")
        ctx = hook_input.get("context_window", {})
        self.context_used_percentage = ctx.get("used_percentage", 0.0)
        ws = hook_input.get("workspace", {})
        self.workspace_dir = ws.get("current_dir")
        self.last_updated = time.time()

    def is_opus(self) -> bool:
        """Check if current model is Opus."""
        if self.model_id:
            return "opus" in self.model_id.lower()
        if self.model_display_name:
            return "opus" in self.model_display_name.lower()
        return False

    def model_name_short(self) -> str:
        """Human-readable short model name."""
        if self.model_display_name:
            return self.model_display_name
        if self.model_id:
            lower = self.model_id.lower()
            if "opus" in lower: return "Opus"
            if "sonnet" in lower: return "Sonnet"
            if "haiku" in lower: return "Haiku"
            return self.model_id
        return "Unknown"
```

**Singleton access** (same pattern as ProjectContext):

```python
_session_state: SessionState | None = None

def get_session_state() -> SessionState:
    global _session_state
    if _session_state is None:
        _session_state = SessionState()
    return _session_state
```

### Integration Point

In the daemon's StatusLine processing, after handlers run, update the cache:

```python
# In DaemonController.process_event() or EventRouter
if event_type == EventType.STATUS_LINE:
    get_session_state().update_from_status_line(hook_input)
```

This is a ONE-LINE integration in the existing event flow.

### What This Unlocks

Any handler, in ANY event type, can now do:
```python
from claude_code_hooks_daemon.core.session_state import get_session_state

state = get_session_state()
if state.is_opus():
    # Model-specific behavior
if state.context_used_percentage > 80:
    # Context-aware behavior
```

---

## Part 2: Model-Aware Agent Team Advisor (Handler)

### Design

**PreToolUse handler** that fires when TeamCreate or Task (agent spawning) tools are used.

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/opus_agent_team_advisor.py`

- **Priority**: 58 (advisory range)
- **Terminal**: False (advisory, never blocks)
- **Tags**: ADVISORY, WORKFLOW, NON_TERMINAL

**Matching logic**:
```python
def matches(self, hook_input):
    tool_name = hook_input.get("tool_name", "")
    # Fire on agent team tools
    return tool_name in ("TeamCreate", "Task")
```

**Handle logic**:
```python
def handle(self, hook_input):
    state = get_session_state()

    if state.model_id is None:
        # No StatusLine data yet (first tool use before status update)
        # Don't advise without data
        return HookResult(decision=Decision.ALLOW)

    if state.is_opus():
        # Opus - confirm support
        return HookResult(
            decision=Decision.ALLOW,
            context=["✅ Opus detected - full agent team orchestration supported."],
        )
    else:
        # Non-Opus - suggest switching
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                f"💡 Running {state.model_name_short()} - agent teams work best with Opus.",
                "For optimal multi-agent orchestration, consider: claude --model claude-opus-4-6",
            ],
        )
```

---

## Files to Modify/Create

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `src/claude_code_hooks_daemon/core/session_state.py` | StatusLine data cache |
| **Create** | `src/claude_code_hooks_daemon/handlers/pre_tool_use/opus_agent_team_advisor.py` | Model-aware advisor |
| **Create** | `tests/unit/core/test_session_state.py` | SessionState tests |
| **Create** | `tests/unit/handlers/pre_tool_use/test_opus_agent_team_advisor.py` | Handler tests |
| **Edit** | `src/claude_code_hooks_daemon/core/__init__.py` | Export SessionState |
| **Edit** | `src/claude_code_hooks_daemon/daemon/controller.py` | Wire up StatusLine → SessionState |
| **Edit** | `src/claude_code_hooks_daemon/constants/handlers.py` | Add HandlerID |
| **Edit** | `src/claude_code_hooks_daemon/constants/priority.py` | Add Priority |
| **Edit** | `.claude/hooks-daemon.yaml` | Add config entry |
| **Edit** | `CLAUDE/Plan/00032-.../PLAN.md` | Update plan with model-awareness |

## Existing Code to Reuse

- `core/handler.py` - Handler base class
- `core/hook_result.py` - HookResult with Decision.ALLOW
- `core/project_context.py` - Singleton pattern to follow for SessionState
- `daemon/controller.py` - DaemonController.process_event() integration point
- `handlers/pre_tool_use/global_npm_advisor.py` - Advisory handler pattern
- `constants/` - HandlerID, Priority, HandlerTag enums

## Test Scenarios

### SessionState Tests
- `test_initial_state`: All fields None/zero
- `test_update_from_status_line`: Correctly parses StatusLine data
- `test_is_opus_true`: Returns True for opus model IDs
- `test_is_opus_false`: Returns False for sonnet/haiku
- `test_is_opus_no_data`: Returns False when no model set
- `test_model_name_short`: Correct short names for all model types
- `test_singleton`: get_session_state() returns same instance

### Handler Tests
- `test_matches_team_create`: Returns True for TeamCreate
- `test_matches_task`: Returns True for Task tool
- `test_matches_rejects_bash`: Returns False for Bash, Write, etc.
- `test_handle_opus`: Context confirms agent team support
- `test_handle_sonnet`: Context suggests switching to Opus
- `test_handle_haiku`: Context suggests switching to Opus
- `test_handle_no_state`: Gracefully handles no StatusLine data yet
- `test_context_is_generic`: No project-specific references in output
- `test_never_blocks`: Always returns Decision.ALLOW

## Verification

1. Unit tests: `pytest tests/unit/core/test_session_state.py tests/unit/handlers/pre_tool_use/test_opus_agent_team_advisor.py -v`
2. Full suite: `pytest tests/ -v`
3. QA: `./scripts/qa/run_all.sh`
4. Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status`
5. Dogfooding: Handler enabled in config, dogfooding tests pass
