# Plan: Update Plan 00032 with Model-Aware Agent Team Advisor Handler

## Context

Plan 00032 (Sub-Agent Orchestration) needs updating to be model-aware. The key insight: Opus 4.6+ is the optimal model for agent team orchestration (spawning teammates, coordinating multi-agent workflows). Users running Sonnet or Haiku should be advised to switch to Opus for best agent team support.

**Critical constraint**: This handler is GENERIC - it ships with the daemon and runs on ANY project, not just this one. No project-specific references (worktrees, 4-gate verification, plan workflows, etc.).

## What We're Building

### 1. New SessionStart Handler: `OpusAgentTeamAdvisorHandler`

A generic, advisory handler that:
- Detects the current model from `hook_input.get("model")` (e.g., `"claude-opus-4-6"`)
- **If Opus 4.6+**: Injects context confirming agent team orchestration is fully supported
- **If NOT Opus**: Suggests switching to Opus for best agent team support
- Non-terminal, advisory - never blocks anything

**Handler spec**:
- **Location**: `src/claude_code_hooks_daemon/handlers/session_start/opus_agent_team_advisor.py`
- **Priority**: 45 (workflow range, after YOLO detection at 40, before suggest_statusline at 55)
- **Terminal**: False
- **Tags**: ADVISORY, WORKFLOW, NON_TERMINAL
- **Event**: SessionStart only

**Matching logic**:
```python
def matches(self, hook_input):
    # Always match SessionStart - we always want to advise about model choice
    return hook_input.get("hook_event_name") == "SessionStart"
```

**Handle logic**:
```python
def handle(self, hook_input):
    model_id = hook_input.get("model", "")

    if _is_opus(model_id):
        # Opus detected - confirm agent team support
        context = [
            "✅ Running Opus 4.6+ - full agent team orchestration supported.",
            "Agent teams, multi-role verification, and sub-agent delegation are optimized for this model.",
        ]
    else:
        # Non-Opus - suggest switching
        model_name = _format_model_name(model_id)
        context = [
            f"💡 Currently running {model_name}.",
            "For best agent team orchestration (spawning teammates, multi-agent coordination),",
            "consider switching to Opus 4.6+: claude --model claude-opus-4-6",
        ]

    return HookResult(decision=Decision.ALLOW, context=context)
```

**Model detection helper** (private function in handler module):
```python
def _is_opus(model_id: str) -> bool:
    """Check if model ID indicates Opus."""
    return "opus" in model_id.lower()

def _format_model_name(model_id: str) -> str:
    """Extract human-readable model name from ID."""
    # "claude-sonnet-4-5-20250929" -> "Sonnet"
    # "claude-haiku-4-5-20251001" -> "Haiku"
    lower = model_id.lower()
    if "haiku" in lower:
        return "Haiku"
    elif "sonnet" in lower:
        return "Sonnet"
    return model_id or "Unknown model"
```

### 2. Constants Updates

**File**: `src/claude_code_hooks_daemon/constants/handlers.py`
- Add `OPUS_AGENT_TEAM_ADVISOR = HandlerIDMeta(...)` to HandlerID enum

**File**: `src/claude_code_hooks_daemon/constants/priority.py`
- Add `OPUS_AGENT_TEAM_ADVISOR = 45` to Priority enum

### 3. Config Entry

**File**: `.claude/hooks-daemon.yaml` under `session_start:`:
```yaml
opus_agent_team_advisor:
  enabled: true
  priority: 45
```

### 4. Tests (TDD - Write First)

**File**: `tests/unit/handlers/session_start/test_opus_agent_team_advisor.py`

Test scenarios:
- `test_init`: Verify handler_id, priority 45, terminal=False, correct tags
- `test_matches_session_start`: Returns True for SessionStart events
- `test_matches_rejects_other_events`: Returns False for PreToolUse, PostToolUse, etc.
- `test_matches_rejects_none`: Returns False for None input
- `test_handle_opus_model`: When model contains "opus", returns context confirming support
- `test_handle_sonnet_model`: When model is Sonnet, suggests switching to Opus
- `test_handle_haiku_model`: When model is Haiku, suggests switching to Opus
- `test_handle_missing_model`: When model field missing, suggests switching (graceful)
- `test_handle_empty_model`: When model is empty string, handles gracefully
- `test_handle_opus_various_ids`: Test different Opus model IDs (claude-opus-4-6, claude-opus-4-20250514, etc.)
- `test_context_is_generic`: Verify no project-specific references in output

### 5. Update Plan 00032 PLAN.md

Add to Plan 00032:
- New task in Phase 4: Create `opus_agent_team_advisor` handler
- Update Phase 1 to note model detection capability exists at SessionStart
- Add model-awareness as a design principle
- Add success criterion: "Model detection advises Opus for agent teams"

### 6. Registration in session_start.py

**File**: `src/claude_code_hooks_daemon/hooks/session_start.py`
- Import and register `OpusAgentTeamAdvisorHandler` in the handler list

## Files to Modify/Create

| Action | File |
|--------|------|
| **Create** | `src/claude_code_hooks_daemon/handlers/session_start/opus_agent_team_advisor.py` |
| **Create** | `tests/unit/handlers/session_start/test_opus_agent_team_advisor.py` |
| **Edit** | `src/claude_code_hooks_daemon/constants/handlers.py` (add HandlerID) |
| **Edit** | `src/claude_code_hooks_daemon/constants/priority.py` (add Priority) |
| **Edit** | `src/claude_code_hooks_daemon/hooks/session_start.py` (register handler) |
| **Edit** | `.claude/hooks-daemon.yaml` (add config entry) |
| **Edit** | `CLAUDE/Plan/00032-subagent-orchestration-context-preservation/PLAN.md` (update plan) |

## Existing Code to Reuse

- **Handler base**: `claude_code_hooks_daemon.core.Handler` (standard base class)
- **HookResult**: `claude_code_hooks_daemon.core.HookResult` with `Decision.ALLOW`
- **Constants**: `HandlerID`, `Priority`, `HandlerTag` from constants module
- **Pattern**: Follow `yolo_container_detection.py` as closest example (SessionStart, env detection, context injection)
- **Tags**: `HandlerTag.ADVISORY`, `HandlerTag.WORKFLOW`, `HandlerTag.NON_TERMINAL`

## Verification

1. **Unit tests**: `pytest tests/unit/handlers/session_start/test_opus_agent_team_advisor.py -v`
2. **Full test suite**: `pytest tests/ -v` (no regressions)
3. **QA suite**: `./scripts/qa/run_all.sh` (all 7 checks pass)
4. **Daemon restart**: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` then verify status RUNNING
5. **Dogfooding**: Handler enabled in project config, dogfooding tests pass
