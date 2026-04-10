# Plan 00077: TranscriptReader Enhancement & AskUserQuestion Bug Fix

## Context

**Bug**: The `AutoContinueStopHandler` incorrectly auto-continues when Claude calls `AskUserQuestion`. The assistant message text contains confirmation-like phrasing ("Would you like to...") which matches the handler's patterns, so it blocks the Stop and tells Claude to continue — the user never sees the question.

**DRY violation**: `AutoContinueStopHandler` and `HedgingLanguageDetectorHandler` both have identical ~53-line `_get_last_assistant_message()` and ~14-line `_is_stop_hook_active()` methods copy-pasted.

**TranscriptReader gap**: The existing `TranscriptReader` parses `"type": "human"/"assistant"` format but the real Claude Code JSONL uses `"type": "message"` with nested `message.role`. The reader also doesn't parse embedded `tool_use` content blocks within messages. Handlers bypass it entirely.

**User vision**: A generic transcript object that can answer contextual questions — "Has AskUserQuestion just been called?", "What tool was last used?", "Are we in the middle of X?"

## Approach

Extend `TranscriptReader` to:

1. Parse the **real** JSONL format (`"type": "message"` with nested role)
2. Parse **embedded content blocks** (text + tool_use) within messages
3. Provide high-level query methods for handlers
4. Replace duplicated private methods in both Stop handlers

Then fix the bug: `AutoContinueStopHandler.matches()` checks if the last assistant message used `AskUserQuestion` tool and returns `False` if so.

## Files to Modify

| File                                                                      | Action                                                                     |
| ------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `src/claude_code_hooks_daemon/core/transcript_reader.py`                  | Extend with content blocks + query methods                                 |
| `tests/unit/core/test_transcript_reader.py`                               | Add tests for new features (TDD)                                           |
| `src/claude_code_hooks_daemon/core/__init__.py`                           | Export new `ContentBlock` type                                             |
| `src/claude_code_hooks_daemon/utils/stop_hook_helpers.py`                 | **Create** — shared `is_stop_hook_active()` + `get_last_assistant_text()`  |
| `tests/unit/utils/test_stop_hook_helpers.py`                              | **Create** — tests for shared utilities                                    |
| `src/claude_code_hooks_daemon/utils/__init__.py`                          | Export new utilities                                                       |
| `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py`        | Remove duplicated methods, use shared utilities, add AskUserQuestion check |
| `src/claude_code_hooks_daemon/handlers/stop/hedging_language_detector.py` | Remove duplicated methods, use shared utilities                            |
| `tests/unit/handlers/stop/test_auto_continue_stop.py`                     | Add AskUserQuestion bug-fix tests                                          |

## Phases

### Phase 1: Enhance TranscriptReader (TDD)

**1a. Add `ContentBlock` dataclass:**

```python
@dataclass(frozen=True, slots=True)
class ContentBlock:
    block_type: str        # "text", "tool_use", etc.
    text: str = ""         # For "text" blocks
    tool_name: str = ""    # For "tool_use" blocks
    tool_input: dict = field(default_factory=dict)
    raw: dict = field(repr=False, default_factory=dict)
```

**1b. Add `content_blocks` field to `TranscriptMessage`:**

```python
content_blocks: tuple[ContentBlock, ...] = ()  # backward-compat default
```

**1c. Fix `_parse()` to handle real JSONL format:**

- Support `"type": "message"` with `message.role` (real format)
- Keep support for `"type": "human"/"assistant"` (legacy/test format)
- When `message.content` is a list, parse each block into `ContentBlock`
- Concatenate text blocks into `content` string (existing field)

**1d. Add query methods:**

- `get_last_assistant_message() -> TranscriptMessage | None`
- `get_last_assistant_text() -> str`
- `last_assistant_used_tool(tool_name: str) -> bool`
- `get_last_tool_use_in_message() -> ContentBlock | None`

### Phase 2: Shared Stop Hook Utilities (TDD)

Create `src/claude_code_hooks_daemon/utils/stop_hook_helpers.py` with:

- `is_stop_hook_active(hook_input) -> bool` — checks both `stop_hook_active` and `stopHookActive`
- `get_transcript_reader(hook_input) -> TranscriptReader | None` — loads transcript from hook_input, returns reader or None

### Phase 3: Refactor Stop Handlers

Replace duplicated private methods in both handlers with calls to shared utilities. **All existing tests must pass without modification** (behaviour-preserving refactor).

### Phase 4: Fix AskUserQuestion Bug (TDD)

Add to `AutoContinueStopHandler.matches()` after confirmation pattern match:

```python
if transcript.last_assistant_used_tool(ToolName.ASK_USER_QUESTION):
    return False  # Don't override AskUserQuestion — user must answer
```

New tests:

- Transcript with AskUserQuestion tool_use block + confirmation text → `matches()` returns `False`
- Transcript with confirmation text but NO AskUserQuestion → `matches()` returns `True` (unchanged)

### Phase 5: QA & Daemon Verification

- Export `ContentBlock` from `core/__init__.py`
- Export utilities from `utils/__init__.py`
- `./scripts/qa/run_all.sh` — all checks pass
- `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && status` — RUNNING

## Verification

```bash
# Run all new + existing tests
pytest tests/unit/core/test_transcript_reader.py -v
pytest tests/unit/utils/test_stop_hook_helpers.py -v
pytest tests/unit/handlers/stop/test_auto_continue_stop.py -v
pytest tests/unit/handlers/stop/test_hedging_language_detector.py -v

# Full QA
./scripts/qa/run_all.sh

# Daemon restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```
