# Plan 00094: Stop Explainer & Auto-Continue

**Status**: Complete (2026-03-30)
**Created**: 2026-03-30
**Owner**: Claude Code
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Claude stopping unexpectedly is expensive — requires a human to notice and re-prompt. Currently the daemon's `auto_continue_stop` handler only fires when the last assistant message contains a confirmation question pattern ("would you like me to continue?"). When Claude silently stops after a QA failure, no pattern matches, the Stop passes through, and the user has to type "go".

**The fix**: make the Stop handler always intercept (with `stop_hook_active: false`), read the transcript to understand why Claude is stopping, and either:

1. **Force continuation** — if the last tool use failed with a recognisable error
2. **Force explanation** — otherwise, block until Claude outputs `STOPPING BECAUSE: <reason>`; then log it and allow through

This gives two things at once:

- Every stop is either auto-continued or visibly explained in the conversation
- Every stop event is logged to `untracked/stop-events.jsonl` for future fine-tuning

## Goals

- [ ] ⬜ Claude never silently stops after a QA tool failure — auto-continues with fix instructions
- [ ] ⬜ Claude never stops without explaining why in the conversation
- [ ] ⬜ All stop events logged as structured JSONL for fine-tuning raw material
- [ ] ⬜ Existing `stop_hook_active` infinite-loop protection preserved

## Non-Goals

- Sub-agent deployment (separate plan when ready)
- Report generation scripts (separate concern)
- Changes to handlers other than `auto_continue_stop`

## Context & Background

### The Stop Protocol (How This Works)

```
Claude finishes/gives up → Stop event fires (stop_hook_active: false)
  ↓
Handler reads transcript_path → last assistant message + last tool use result
  ↓
  ├─ Last tool use was a QA command with errors?
  │    → BLOCK: "Fix the N failures and continue"
  │
  ├─ Last assistant message starts with "STOPPING BECAUSE:"?
  │    → LOG the reason to stop-events.jsonl → ALLOW (explanation already given)
  │
  └─ Everything else (unclear reason, or task seemed complete)?
       → BLOCK: "Before stopping: if there is unfinished/broken work, fix it and
                 continue. Otherwise start your response with 'STOPPING BECAUSE:
                 <one sentence reason>'."

Second Stop fires (stop_hook_active: true)
  → ALWAYS LOG + ALLOW  (prevents infinite loop)
```

### Why `transcript_path`

Every Stop hook input already contains `transcript_path` — the path to the current session's JSONL transcript. The existing `TranscriptReader` (`core/transcript_reader.py`) can read this lazily. We use `read_incremental()` to get only the last N messages without re-parsing the whole file.

### The JSONL Log Format

```json
{"session_id": "abc123", "timestamp": "...", "stop_reason": "STOPPING BECAUSE: task complete", "was_blocked": false, "stop_hook_active": false, "last_tool_name": "Bash", "last_tool_failed": false, "transcript_path": "/path/to/transcript.jsonl"}
```

This log becomes training signal: each entry tells us whether the stop was legitimate (human eventually said "yes done") or premature (human said "go" → Claude resumed).

### Current `auto_continue_stop` Behaviour

The existing handler:

- Has `stop_hook_active` check (infinite loop prevention) ✅
- Reads transcript via `TranscriptReader` ✅
- Matches only when confirmation question detected ← gap
- Has `continue_on_errors` option (blunt instrument) ← replace with smarter logic
- Returns `decision=deny` (which maps to Stop block) ✅

We extend this handler. We do NOT add a new handler — ordering and config would be messier.

### Known QA Tool Patterns

Default list for auto-continue on failure:

```
pytest, python -m pytest, ruff, mypy, bandit, black, shellcheck,
./scripts/qa/, npm test, npm run test, yarn test, go test, cargo test,
eslint, tsc, php -l, phpunit
```

When the last Bash tool use matches one of these AND the output contains error/failure indicators → block with "fix and continue", don't require explanation.

## Tasks

### Phase 1: Core Handler Enhancement (TDD)

- [ ] ⬜ **Task 1.1**: Read `auto_continue_stop` handler fully

  ```bash
  # Read the full implementation before touching anything
  cat src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py
  ```

- [ ] ⬜ **Task 1.2**: Write failing tests first — new behaviours to cover:

  - Stop with no transcript/last message and `stop_hook_active: false` → block with explanation request
  - Stop after pytest failure (last tool = `pytest tests/`, output has "FAILED") → block with "fix and continue"
  - Stop after `./scripts/qa/run_all.sh` failure → block with "fix and continue"
  - Stop with "STOPPING BECAUSE:" in last message → allow (log, pass through)
  - Stop with `stop_hook_active: true` → always allow
  - Second stop after explanation (via `stop_hook_active: true`) → allow

- [ ] ⬜ **Task 1.3**: Implement in `auto_continue_stop.py`:

  - Extract `transcript_path` from `hook_input` (alongside existing `last_assistant_message`)
  - Add `_is_qa_failure(tool_name, tool_output)` helper — checks QA patterns + error indicators
  - Add `_has_stop_explanation(last_message)` helper — checks for "STOPPING BECAUSE:" prefix
  - Update `handle()` to route through the three branches (QA failure / has explanation / needs explanation)
  - Keep all existing confirmation-question logic as a fourth path (for backwards compat)

- [ ] ⬜ **Task 1.4**: Add `qa_tool_patterns` config option (list of regex patterns, default = known QA commands). Document in handler's `options` metadata.

- [ ] ⬜ **Task 1.5**: Run tests — all must pass

  ```bash
  /workspace/untracked/venv/bin/python -m pytest tests/unit/handlers/stop/test_auto_continue_stop.py -v
  ```

### Phase 2: Stop Event Logger

- [ ] ⬜ **Task 2.1**: Write failing test for logging behaviour — after a stop is allowed, a JSONL entry must appear in `untracked/stop-events.jsonl`

- [ ] ⬜ **Task 2.2**: Implement `_log_stop_event()` private method:

  - File: `{UNTRACKED_DIR}/stop-events.jsonl`
  - Append-only (one JSON object per line)
  - Fields: `session_id`, `timestamp`, `stop_reason`, `was_blocked`, `stop_hook_active`, `last_tool_name`, `last_tool_failed`, `transcript_path`
  - Never raise — silently skip on I/O error (logging must not block the hook)

- [ ] ⬜ **Task 2.3**: Call `_log_stop_event()` in both the ALLOW paths:

  - When "STOPPING BECAUSE:" explanation is given → log with `was_blocked: false`
  - When `stop_hook_active: true` (final stop after forced continue) → log the final state

- [ ] ⬜ **Task 2.4**: Run tests — all must pass

### Phase 3: Config, QA, Daemon Verification

- [ ] ⬜ **Task 3.1**: Update `hooks-daemon.yaml` config schema to include new options:

  - `force_explanation: true` (default) — enable/disable the explanation requirement
  - `qa_tool_patterns` — user-extensible list
  - `max_auto_continues: 3` — safety cap: after N auto-continues in a session, allow stop

- [ ] ⬜ **Task 3.2**: Update `.claude/hooks-daemon.yaml` (dogfooding config) with sensible defaults

- [ ] ⬜ **Task 3.3**: Regenerate `.claude/HOOKS-DAEMON.md`:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli generate-docs
  ```

- [ ] ⬜ **Task 3.4**: Run full QA suite:

  ```bash
  ./scripts/qa/llm_qa.py all
  ```

- [ ] ⬜ **Task 3.5**: Daemon restart verification:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  $PYTHON -m claude_code_hooks_daemon.daemon.cli status
  ```

### Phase 4: Acceptance Testing

- [ ] ⬜ **Task 4.1**: Update `auto_continue_stop.get_acceptance_tests()` with new test cases:

  - QA failure path
  - Explanation-forced path
  - `stop_hook_active: true` path

- [ ] ⬜ **Task 4.2**: Generate playbook and execute relevant tests:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md
  ```

  Execute the `auto_continue_stop` tests in the main thread.

- [ ] ⬜ **Task 4.3**: Commit:

  ```
  Add: Stop explainer — force explanation or auto-continue on failures
  ```

## The Three Stop Branches (Summary)

| Situation                                    | Action                                                   | User sees                                 |
| -------------------------------------------- | -------------------------------------------------------- | ----------------------------------------- |
| Last Bash was a QA tool that failed          | BLOCK → "Fix the N failures, re-run to verify, continue" | Claude immediately continues fixing       |
| Last message starts with "STOPPING BECAUSE:" | LOG + ALLOW                                              | Clear stop reason in conversation history |
| Anything else                                | BLOCK → "Explain or continue"                            | Claude either explains or resumes         |
| `stop_hook_active: true`                     | LOG + ALLOW                                              | Claude stops cleanly                      |

## Success Criteria

- [ ] Running `./scripts/qa/run_all.sh` with failures no longer stops Claude — it auto-continues
- [ ] Any non-QA stop produces a "STOPPING BECAUSE:" explanation visible in the conversation
- [ ] `untracked/stop-events.jsonl` is written after every allowed stop
- [ ] `stop_hook_active: true` still prevents infinite loops
- [ ] All existing `auto_continue_stop` tests continue to pass
- [ ] Full QA suite passes (8/8)
- [ ] Daemon restarts cleanly

## Files Changed

| File                                                  | Change                                                                    |
| ----------------------------------------------------- | ------------------------------------------------------------------------- |
| `src/.../handlers/stop/auto_continue_stop.py`         | Add QA failure detection, explanation forcing, JSONL logging              |
| `tests/unit/handlers/stop/test_auto_continue_stop.py` | New test cases for all three branches                                     |
| `.claude/hooks-daemon.yaml`                           | Add `qa_tool_patterns`, `force_explanation`, `max_auto_continues` options |
| `.claude/HOOKS-DAEMON.md`                             | Regenerated                                                               |
