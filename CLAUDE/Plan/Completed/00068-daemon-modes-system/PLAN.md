# Plan: Daemon Modes System

## Context

Claude Code often stops mid-work and asks for confirmation or just halts, requiring human input to continue. The existing `AutoContinueStopHandler` uses pattern matching against 52 confirmation patterns in the transcript, but it misses many cases where Claude stops without asking a recognizable question. The user wants a more aggressive approach: an **unattended mode** where every Stop event is blocked unconditionally, keeping Claude working without interruption.

This requires a new concept: **daemon modes** -- runtime-mutable state on the daemon process that changes how events are processed. Modes can be set temporarily via IPC or configured as the default in `hooks-daemon.yaml`.

## Design Decisions

1. **Mode state** lives in a dedicated `ModeManager` class held by `DaemonController` (Single Responsibility)
2. **Mode affects processing** via a pre-dispatch interceptor in `process_event()` -- before the handler chain runs, the interceptor can short-circuit the response. Handlers never need to know about modes (Open/Closed)
3. **Only Stop events** are blocked in unattended mode (not SubagentStop -- per user preference)
4. **Re-entry protection** is preserved -- `stop_hook_active` / `stopHookActive` is checked to prevent infinite loops
5. **Default mode** has no interceptor -- existing behavior is completely unchanged
6. **Optional custom message** -- the unattended mode block reason can include an extra user-provided message appended to the default directive
7. **Skill interface** -- `/configure mode unattended` sets the mode via IPC (subcommand of existing `/configure` skill pattern)

## Implementation Phases

### Phase 1: Core Mode Infrastructure
**New files:**
- `src/claude_code_hooks_daemon/constants/modes.py` -- `DaemonMode` StrEnum (`default`, `unattended`), `ModeConstant` (action names, config keys, block reason text)
- `src/claude_code_hooks_daemon/core/mode.py` -- `ModeManager` class (holds current mode, validates transitions, serializes to dict)
- `tests/unit/core/test_mode.py` -- TDD tests for ModeManager

**Key details:**
- `DaemonMode(StrEnum)`: `DEFAULT = "default"`, `UNATTENDED = "unattended"`
- `ModeManager.__init__(initial_mode, custom_message=None)` -- stores mode + optional extra message
- `ModeManager.set_mode(mode, custom_message=None)` -- validates and changes mode
- `ModeManager.to_dict()` -- returns `{"mode": "...", "custom_message": "..."|None}`
- Add exports to `constants/__init__.py` and `core/__init__.py`

### Phase 2: Mode Interceptor
**New files:**
- `src/claude_code_hooks_daemon/core/mode_interceptor.py` -- `ModeInterceptor` Protocol + `UnattendedModeInterceptor` + `get_interceptor_for_mode()` factory
- `tests/unit/core/test_mode_interceptor.py` -- TDD tests

**Key details:**
- `ModeInterceptor` Protocol with `intercept(event_type, hook_input) -> HookResult | None`
- `UnattendedModeInterceptor.__init__(custom_message: str | None = None)` -- takes optional extra text
- Only intercepts `EventType.STOP` (not SubagentStop)
- Checks `stop_hook_active` / `stopHookActive` for re-entry -- returns `None` if active
- Returns `HookResult(decision=Decision.DENY, reason=<directive message + optional custom>)`
- `get_interceptor_for_mode(mode, custom_message) -> ModeInterceptor | None` -- factory function, returns `None` for default mode

### Phase 3: Controller Integration
**Modified files:**
- `src/claude_code_hooks_daemon/daemon/controller.py` -- add `_mode_manager` to `__slots__`, init from config, pre-dispatch intercept in `process_event()`, expose `get_mode()`/`set_mode()`, include mode in `get_health()`
- `src/claude_code_hooks_daemon/config/models.py` -- add `default_mode: str = "default"` field to `DaemonConfig` with validator

**New files:**
- `tests/unit/daemon/test_controller_modes.py` -- TDD tests

**Key change in `process_event()`** (insert after degraded-mode check, before `model_dump`):
```python
interceptor = get_interceptor_for_mode(
    self._mode_manager.current_mode,
    self._mode_manager.custom_message,
)
if interceptor is not None:
    hook_input_dict = event.hook_input.model_dump(by_alias=False)
    intercept_result = interceptor.intercept(event.event_type, hook_input_dict)
    if intercept_result is not None:
        # Record stats, log, return short-circuited result
        ...
```

### Phase 4: IPC System Actions
**Modified files:**
- `src/claude_code_hooks_daemon/daemon/server.py` -- add `get_mode` and `set_mode` actions in `_handle_system_request()`

**New files:**
- `tests/unit/daemon/test_server_mode_actions.py` -- TDD tests

**IPC protocol:**
- `{event: "_system", hook_input: {action: "get_mode"}}` -> `{result: {mode: "default", custom_message: null}}`
- `{event: "_system", hook_input: {action: "set_mode", mode: "unattended", custom_message: "finish the release"}}` -> `{result: {mode: "unattended", status: "changed"}}`

### Phase 5: CLI Commands
**Modified files:**
- `src/claude_code_hooks_daemon/daemon/cli.py` -- add `mode` subcommand with `get` and `set` sub-subcommands

**New files:**
- `tests/unit/daemon/test_cli_mode_commands.py` -- TDD tests

**Usage:**
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli mode get
# Output: Mode: default

$PYTHON -m claude_code_hooks_daemon.daemon.cli mode set unattended
# Output: Mode changed to: unattended

$PYTHON -m claude_code_hooks_daemon.daemon.cli mode set unattended --message "finish all tasks in the plan"
# Output: Mode changed to: unattended (custom message set)

$PYTHON -m claude_code_hooks_daemon.daemon.cli mode set default
# Output: Mode changed to: default
```

### Phase 6: Skill + Config + Integration Tests
**New files:**
- `.claude/skills/mode/SKILL.md` -- skill documentation
- `.claude/skills/mode/invoke.sh` -- skill entry point that sends IPC via CLI
- `tests/integration/test_mode_stop_integration.py` -- end-to-end integration tests

**Modified files:**
- `.claude/hooks-daemon.yaml` -- add `default_mode: default` under `daemon:` section

**Skill usage:**
```bash
/mode unattended                              # Set unattended mode
/mode unattended "finish the release tasks"   # With custom message
/mode default                                 # Back to default
/mode                                         # Show current mode
```

## Critical Files

| File | Action | Purpose |
|------|--------|---------|
| `src/claude_code_hooks_daemon/constants/modes.py` | Create | DaemonMode enum, ModeConstant |
| `src/claude_code_hooks_daemon/core/mode.py` | Create | ModeManager class |
| `src/claude_code_hooks_daemon/core/mode_interceptor.py` | Create | ModeInterceptor protocol + UnattendedModeInterceptor |
| `src/claude_code_hooks_daemon/daemon/controller.py` | Modify | Add mode_manager, pre-dispatch intercept |
| `src/claude_code_hooks_daemon/daemon/server.py` | Modify | Add get_mode/set_mode system actions |
| `src/claude_code_hooks_daemon/daemon/cli.py` | Modify | Add mode subcommand |
| `src/claude_code_hooks_daemon/config/models.py` | Modify | Add default_mode field |
| `src/claude_code_hooks_daemon/constants/__init__.py` | Modify | Export DaemonMode, ModeConstant |
| `src/claude_code_hooks_daemon/core/__init__.py` | Modify | Export ModeManager, ModeInterceptor |
| `.claude/hooks-daemon.yaml` | Modify | Add default_mode config |
| `.claude/skills/mode/SKILL.md` | Create | Skill docs |
| `.claude/skills/mode/invoke.sh` | Create | Skill entry point |

## Reusable Patterns

- **Re-entry protection**: Mirror `AutoContinueStopHandler._is_stop_hook_active()` at `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py:77-94`
- **System action pattern**: Follow `_handle_system_request()` at `src/claude_code_hooks_daemon/daemon/server.py:594-648`
- **CLI subcommand pattern**: Follow existing subcommand registration in `cli.py`
- **Config field pattern**: Follow `strict_mode` field at `src/claude_code_hooks_daemon/config/models.py:411-414`
- **Skill structure**: Follow `/configure` skill at `.claude/skills/configure/`
- **Constants module**: Follow `constants/priority.py` pattern for `constants/modes.py`

## Verification

After each phase:
1. `pytest tests/unit/... -v` (phase-specific tests pass)
2. `./scripts/qa/run_all.sh` (full QA green)
3. `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && $PYTHON -m claude_code_hooks_daemon.daemon.cli status` (daemon loads)

Final verification:
1. Set unattended mode via CLI: `$PYTHON -m claude_code_hooks_daemon.daemon.cli mode set unattended`
2. Verify mode is set: `$PYTHON -m claude_code_hooks_daemon.daemon.cli mode get`
3. Verify health shows mode: `$PYTHON -m claude_code_hooks_daemon.daemon.cli health`
4. Live test: trigger a Stop event and confirm it gets blocked with the directive message
5. Verify default mode is unchanged: set back to default, confirm auto-continue handler works normally
