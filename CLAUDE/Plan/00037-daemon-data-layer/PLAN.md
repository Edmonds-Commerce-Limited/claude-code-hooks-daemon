# Plan 00037: Daemon Data Layer - Persistent State & Transcript Access

**Status**: Complete (2026-02-09)

## Context

Handlers currently only see data from their own event (`hook_input`). StatusLine has model info and context %. SessionStart has transcript path. PreToolUse has tool name/input. But NO handler can see across events.

**Problem**: To build smart features (model-aware agent team advice, hallucination detection, block history tracking), handlers need access to session-wide data: current model, context usage, conversation history, previous handler decisions.

**Solution**: Build a persistent data layer in the daemon that aggregates data from multiple sources and exposes it through a clean, performant internal API. The daemon is already a persistent process - this leverages that architecture.

**Prerequisite for**: Plan 00032 (Sub-Agent Orchestration needs model detection at PreToolUse time)

**Rename folder to**: `00035-daemon-data-layer`

---

## Architecture

```
Data Sources                    Daemon Data Layer              Consumers
                                ─────────────────
StatusLine events ──────┐       ┌─────────────────┐
  (model, context %)    ├──────>│  SessionState    │───┐
                        │       │  (in-memory)     │   │
SessionStart events ────┤       ├─────────────────┤   ├──> Any Handler
  (transcript_path)     ├──────>│  TranscriptReader│   │    via get_data_layer()
                        │       │  (lazy, cached)  │   │
Handler results ────────┘       ├─────────────────┤   │
  (block history)               │  HandlerHistory  │───┘
                                │  (decision log)  │
                                └─────────────────┘
```

---

## Part 1: SessionState (StatusLine Cache)

**File**: `src/claude_code_hooks_daemon/core/session_state.py`

Lightweight in-memory cache updated on every StatusLine event.

**Data cached**:
- `model_id` / `model_display_name` - Current model
- `context_used_percentage` - Context window usage
- `workspace_dir` / `project_dir` - Workspace info
- `last_updated` - Timestamp of last StatusLine event

**Convenience methods**:
- `is_opus() -> bool` - Quick model family check
- `is_sonnet() -> bool` / `is_haiku() -> bool`
- `model_name_short() -> str` - Human-readable name

**Integration**: One-line hook in `DaemonController.process_event()` after StatusLine dispatch.

---

## Part 2: TranscriptReader (JSONL Parser)

**File**: `src/claude_code_hooks_daemon/core/transcript_reader.py`

Lazy, cached parser for Claude Code's JSONL conversation transcripts.

**Key design decisions**:
- **Lazy loading**: Don't parse until first query
- **Cached**: Parse once, cache results until transcript path changes
- **Read-only**: Never modify transcript files
- **Performant**: Stream JSONL lines, don't load entire file into memory

**API** (initial - expand as use cases emerge):
- `load(transcript_path: str) -> None`
- `get_messages() -> list[TranscriptMessage]`
- `get_tool_uses() -> list[ToolUse]`
- `get_last_n_messages(n: int) -> list[TranscriptMessage]`
- `search_messages(pattern: str) -> list[TranscriptMessage]`
- `is_loaded() -> bool`

**NOTE**: JSONL format needs research during implementation - explore actual file structure before finalizing API.

---

## Part 3: HandlerHistory (Decision Log)

**File**: `src/claude_code_hooks_daemon/core/handler_history.py`

Tracks previous handler decisions within the session.

**Data per decision**: handler_id, event_type, decision, tool_name, timestamp, reason

**API**:
- `record(...)` - Log a decision
- `get_recent(n) -> list` - Last N decisions
- `count_blocks() -> int` - Total blocks this session
- `was_blocked(tool_name) -> bool` - Was this tool blocked before?

**Integration**: FrontController records each handler result after dispatch.

---

## Part 4: DaemonDataLayer (Unified API)

**File**: `src/claude_code_hooks_daemon/core/data_layer.py`

Single entry point for handlers to access all session data.

```python
class DaemonDataLayer:
    @property
    def session(self) -> SessionState:
    @property
    def transcript(self) -> TranscriptReader:
    @property
    def history(self) -> HandlerHistory:

def get_data_layer() -> DaemonDataLayer:
    ...
```

**Handler usage**:
```python
from claude_code_hooks_daemon.core.data_layer import get_data_layer

def handle(self, hook_input):
    dl = get_data_layer()
    if dl.session.is_opus(): ...
    if dl.history.was_blocked("Bash"): ...
```

---

## Files to Create/Modify

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `src/claude_code_hooks_daemon/core/session_state.py` | StatusLine data cache |
| **Create** | `src/claude_code_hooks_daemon/core/transcript_reader.py` | JSONL transcript parser |
| **Create** | `src/claude_code_hooks_daemon/core/handler_history.py` | Decision history log |
| **Create** | `src/claude_code_hooks_daemon/core/data_layer.py` | Unified API facade |
| **Create** | `tests/unit/core/test_session_state.py` | Tests |
| **Create** | `tests/unit/core/test_transcript_reader.py` | Tests |
| **Create** | `tests/unit/core/test_handler_history.py` | Tests |
| **Create** | `tests/unit/core/test_data_layer.py` | Tests |
| **Edit** | `src/claude_code_hooks_daemon/core/__init__.py` | Export new classes |
| **Edit** | `src/claude_code_hooks_daemon/daemon/controller.py` | Wire StatusLine -> SessionState |
| **Edit** | `src/claude_code_hooks_daemon/core/front_controller.py` | Wire dispatch -> HandlerHistory |

## Existing Code to Reuse

- `core/project_context.py` - Singleton pattern for all new classes
- `daemon/controller.py:DaemonStats` - Session-scoped state accumulation pattern
- `daemon/controller.py:process_event()` - Integration point for StatusLine caching
- `core/front_controller.py` - Integration point for HandlerHistory recording

## Verification

1. Unit tests for all 4 new modules
2. Full test suite (no regressions)
3. `./scripts/qa/run_all.sh` (all 7 checks)
4. Daemon restart verification
5. Integration test: StatusLine event -> SessionState populated -> PreToolUse handler reads it

## What This Enables (Future Features)

- **Model-aware agent team advisor** (Plan 00032) - `dl.session.is_opus()` at TeamCreate
- **Hallucination detection** - scan `dl.transcript` for inconsistencies
- **Block tracking** - `dl.history.count_blocks()` for analytics
- **Context-aware compaction advice** - `dl.session.context_used_percentage > 80`
- **Repeated mistake detection** - search transcript for patterns
- **Lazy shortcut detection** - analyze agent output for cutting corners
