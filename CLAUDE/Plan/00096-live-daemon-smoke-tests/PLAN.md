# Plan 00096: Live Daemon Smoke Tests in QA Stack

**Status**: Not Started
**Created**: 2026-03-30
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The current QA stack has a critical gap: it never tests the running daemon. Unit tests
run handler code in Python isolation. Integration tests exercise the DaemonController
in-process. Neither catches the #1 dogfooding failure mode: **the daemon is running
stale code** because it was never restarted after a handler change.

The Plan 00094 incident proved this: all unit tests passed, QA was 8/8, but the
daemon had been running old `auto_continue_stop` code for the entire session. The stop
hook silently returned `{}` (allow) instead of `{"decision":"block",...}`. A single
nc probe would have caught it immediately.

**The fix**: add a `smoke_test` QA check (check 9 of 9) that sends known inputs to
the live hook scripts and asserts the responses. Runs in ~2 seconds. Fails loudly if
the daemon is down, stale, or broken.

## Goals

- [ ] ⬜ A new `scripts/qa/run_smoke_test.sh` that probes the live daemon via hook scripts
- [ ] ⬜ `llm_qa.py all` includes `smoke_test` as check 9 and fails the suite if it fails
- [ ] ⬜ Three core probes cover the highest-value signal: Stop, PreToolUse blocking, stop_hook_active loop guard
- [ ] ⬜ Daemon-down case produces a clear actionable error (not a silent pass)
- [ ] ⬜ No external dependencies beyond `bash`, the existing hook scripts, and `jq`

## Non-Goals

- Full acceptance test suite (that is the pre-release gate, not everyday QA)
- Testing every handler (3 probes gives sufficient coverage for smoke purposes)
- Requiring a real Claude Code session (probes go via hook scripts, not the CLI)

## Background

### Why This Gap Exists

The QA stack was designed bottom-up (unit → integration → type → security). The
daemon itself was always assumed to be running correctly. But the daemon is a process
that loads Python modules once at startup — file edits are invisible to it. Tests that
import the same modules directly never notice the discrepancy.

### The Probe Pattern

Hook scripts are plain bash executables that accept JSON on stdin and write JSON to
stdout. They connect to the daemon socket, send the event, and return the response.
This makes them perfect for scripted smoke testing:

```bash
RESPONSE=$(echo '{"hook_event_name":"Stop","stop_hook_active":false}' \
  | /workspace/.claude/hooks/stop 2>/dev/null)
DECISION=$(echo "$RESPONSE" | jq -r '.decision // empty')
[ "$DECISION" = "block" ] || fail "Stop hook did not block"
```

### The Three Core Probes

| Probe                            | Input                                         | Expected                                   | What it catches                                              |
| -------------------------------- | --------------------------------------------- | ------------------------------------------ | ------------------------------------------------------------ |
| **Stop (no explanation)**        | `Stop, stop_hook_active:false, no transcript` | `decision=block, reason contains STOPPING` | Stale daemon, handler disabled, wrong code path              |
| **Stop (loop guard)**            | `Stop, stop_hook_active:true`                 | `{}` (empty/allow)                         | Loop guard regression — if this blocks, infinite loops occur |
| **PreToolUse (destructive git)** | `Bash, command="git reset --hard HEAD"`       | `decision=block`                           | Blocking handler down, stale code, import error              |

## Tasks

### Phase 1: Script Implementation (TDD)

- [ ] ⬜ **Task 1.1**: Write `tests/unit/qa/test_smoke_test.py` — unit tests for the
  probe logic using subprocess mocks. Tests should cover:

  - All 3 probes pass → exit 0
  - Probe 1 fails (daemon down) → exit 1 with clear message
  - Probe 2 returns `decision=block` (loop guard broken) → exit 1
  - Probe 3 allows destructive command → exit 1
  - Daemon socket missing → exit 1 with "daemon not running" message

- [ ] ⬜ **Task 1.2**: Implement `scripts/qa/run_smoke_test.sh`:

  - Source socket path from daemon (same lookup as hook scripts)
  - Check socket exists before probing (fast-fail with actionable message)
  - Run 3 probes in sequence, report PASS/FAIL per probe
  - Exit 0 only if all 3 pass
  - Output format matches other QA scripts (for llm_qa.py JSON parsing)

- [ ] ⬜ **Task 1.3**: Run tests — all must pass

### Phase 2: Integration with llm_qa.py

- [ ] ⬜ **Task 2.1**: Add `smoke_test` to `scripts/qa/llm_qa.py`:

  - Add as check 9 (after `error_hiding`, before summary)
  - Use same JSON output pattern as other checks
  - Key: `smoke_test`, label: `Smoke Test (live daemon)`
  - Failure message: show which probe failed and what it returned

- [ ] ⬜ **Task 2.2**: Add `untracked/qa/smoke_test.json` to the output convention
  (llm_qa.py reads/writes JSON files for each check)

- [ ] ⬜ **Task 2.3**: Update `scripts/qa/run_all.sh` to include `run_smoke_test.sh`
  as step 9

- [ ] ⬜ **Task 2.4**: Verify the smoke test shows in `llm_qa.py all` output:

  ```
  ✅ smoke_test: 3/3 probes passed
  ```

### Phase 3: QA + Daemon Verification

- [ ] ⬜ **Task 3.1**: Run full QA suite — all 9 checks must pass:

  ```bash
  ./scripts/qa/llm_qa.py all
  ```

- [ ] ⬜ **Task 3.2**: Confirm smoke test fails as expected when daemon is stopped:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli stop
  ./scripts/qa/run_smoke_test.sh
  # Expected: FAILED — daemon not running
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  ```

- [ ] ⬜ **Task 3.3**: Daemon restart verification:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  $PYTHON -m claude_code_hooks_daemon.daemon.cli status
  ```

## Success Criteria

- [ ] `./scripts/qa/llm_qa.py all` shows 9/9 PASSED (smoke test included)
- [ ] Stopping the daemon makes the smoke test fail loudly
- [ ] The 3 probes cover Stop (no explanation), Stop (loop guard), and PreToolUse blocking
- [ ] Probe failure message shows exactly what was sent, what came back, and what was expected
- [ ] Shell scripts pass `shellcheck`
- [ ] No changes needed to handler code — this is purely QA infrastructure

## Files Changed

| File                               | Change                               |
| ---------------------------------- | ------------------------------------ |
| `scripts/qa/run_smoke_test.sh`     | New: 3-probe live daemon smoke test  |
| `scripts/qa/llm_qa.py`             | Add smoke_test as check 9            |
| `scripts/qa/run_all.sh`            | Add run_smoke_test.sh as step 9      |
| `tests/unit/qa/test_smoke_test.py` | New: unit tests for smoke test logic |
