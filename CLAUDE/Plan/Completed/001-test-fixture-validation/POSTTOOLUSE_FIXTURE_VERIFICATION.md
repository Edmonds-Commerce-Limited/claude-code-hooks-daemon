# PostToolUse Test Fixture Verification Report

**Date**: 2026-01-27
**Task**: Verify PostToolUse test fixtures match real Claude Code event data

## Executive Summary

**CRITICAL MISMATCH FOUND**: PostToolUse test fixtures use incorrect field names that do not match real Claude Code event data.

- **Test Fixtures Use**: `tool_output` (with `exit_code`, `stdout`, `stderr`)
- **Real Events Use**: `tool_response` (with `stdout`, `stderr`, `interrupted`, `isImage`)

## Detailed Findings

### 1. Real Event Structure (from Daemon Logs)

**Bash Tool PostToolUse Event:**
```json
{
  "session_id": "b49f6c51-140e-4cd0-9827-9bb65ef504b8",
  "transcript_path": "/root/.claude/projects/-workspace/b49f6c51-140e-4cd0-9827-9bb65ef504b8.jsonl",
  "cwd": "/workspace",
  "permission_mode": "acceptEdits",
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "tail -50 untracked/logs/hooks/notifications.jsonl 2>/dev/null | grep -v \"Test notification\" | head -20",
    "description": "Get recent real notification events from logs, excluding test data"
  },
  "tool_response": {
    "stdout": "",
    "stderr": "",
    "interrupted": false,
    "isImage": false
  },
  "tool_use_id": "toolu_01MiGeLHUXmtjhecku5uhRcb"
}
```

**Read Tool PostToolUse Event:**
```json
{
  "tool_name": "Read",
  "tool_input": {
    "file_path": "/workspace/scripts/debug_hooks.sh"
  },
  "tool_response": {
    "type": "text",
    "file": {
      "filePath": "/workspace/scripts/debug_hooks.sh",
      "content": "...",
      "numLines": 147,
      "startLine": 1,
      "totalLines": 147
    }
  },
  "tool_use_id": "toolu_014CArophhZmhDNPvtWkJUzr"
}
```

**Glob Tool PostToolUse Event:**
```json
{
  "tool_name": "Glob",
  "tool_input": {
    "pattern": "tests/**/*post_tool*.py"
  },
  "tool_response": {
    "filenames": [
      "/workspace/tests/unit/hooks/test_post_tool_use.py"
    ],
    "durationMs": 38,
    "numFiles": 1,
    "truncated": false
  },
  "tool_use_id": "toolu_011xpYLCGGSmcV1qfPZ2Bg8A"
}
```

**Grep Tool PostToolUse Event:**
```json
{
  "tool_name": "Grep",
  "tool_response": {
    "mode": "content",
    "numFiles": 0,
    "filenames": [],
    "content": "...",
    "numLines": 22,
    "appliedLimit": 30
  }
}
```

### 2. Test Fixture Structure (Incorrect)

**File**: `/workspace/tests/unit/handlers/post_tool_use/test_bash_error_detector.py`

**Lines 38, 47, 90, 100, 111, etc.** all use:
```python
hook_input = {
    "tool_name": "Bash",
    "tool_input": {"command": "npm run build"},
    "tool_output": {"exit_code": 0, "stdout": "Build successful"},  # WRONG FIELD NAME!
}
```

### 3. Handler Implementation (Also Incorrect)

**File**: `/workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/bash_error_detector.py`

**Line 45**:
```python
tool_output = hook_input.get("tool_output", {})  # WRONG FIELD NAME!
```

The handler looks for `tool_output` but real events have `tool_response`.

### 4. Key Differences

| Aspect | Test Fixtures | Real Events |
|--------|---------------|-------------|
| **Field Name** | `tool_output` | `tool_response` |
| **Bash stdout** | `tool_output.stdout` | `tool_response.stdout` |
| **Bash stderr** | `tool_output.stderr` | `tool_response.stderr` |
| **Bash exit code** | `tool_output.exit_code` | **NOT PRESENT** |
| **Interrupted flag** | **NOT PRESENT** | `tool_response.interrupted` |
| **Image flag** | **NOT PRESENT** | `tool_response.isImage` |
| **Read file content** | N/A | `tool_response.file.content` |
| **Read type** | N/A | `tool_response.type` |
| **Glob filenames** | N/A | `tool_response.filenames` |

### 5. Critical Missing Field: `exit_code`

**IMPORTANT**: Real Bash PostToolUse events do NOT include `exit_code` in `tool_response`. The handler's logic on line 53:

```python
exit_code = tool_output.get("exit_code", 0)
```

Will ALWAYS default to 0 because:
1. It's looking in the wrong field (`tool_output` vs `tool_response`)
2. Even if it looked in `tool_response`, there is no `exit_code` field there

This means the error detection logic that depends on exit codes **will never work in production**.

### 6. Impact Assessment

**Severity**: HIGH

**Affected Components**:
1. ✅ `BashErrorDetectorHandler` - Uses `tool_output`, will NOT match real events
2. ✅ All test files in `tests/unit/handlers/post_tool_use/` - Use incorrect fixture structure
3. ⚠️  `ValidateEslintOnWriteHandler` - Uses `tool_input` (correct) but may have issues
4. ⚠️  `ValidateSitemapHandler` - Uses `tool_input` (correct) but may have issues

**Functionality Impact**:
- ❌ BashErrorDetectorHandler **DOES NOT WORK** in production (handler never matches real events)
- ❌ Exit code detection **DOES NOT WORK** (field missing from real events)
- ✅ Tests pass because they use wrong fixtures that match wrong handler code
- ❌ No integration tests exist to catch this field name mismatch

### 7. Tool-Specific Response Structures

Based on real events, each tool has a different `tool_response` structure:

**Bash:**
```json
{
  "stdout": "string",
  "stderr": "string",
  "interrupted": boolean,
  "isImage": boolean
}
```

**Read:**
```json
{
  "type": "text",
  "file": {
    "filePath": "string",
    "content": "string",
    "numLines": number,
    "startLine": number,
    "totalLines": number
  }
}
```

**Glob:**
```json
{
  "filenames": ["string"],
  "durationMs": number,
  "numFiles": number,
  "truncated": boolean
}
```

**Grep:**
```json
{
  "mode": "content",
  "numFiles": number,
  "filenames": ["string"],
  "content": "string",
  "numLines": number,
  "appliedLimit": number
}
```

## Recommendations

### Immediate Actions Required

1. **Fix Handler Implementation**:
   - Change `tool_output` to `tool_response` in `bash_error_detector.py`
   - Remove dependency on `exit_code` field (not available in real events)
   - Update error detection logic to work without exit codes

2. **Fix All Test Fixtures**:
   - Change `tool_output` to `tool_response` in all test files
   - Remove `exit_code` from test fixtures
   - Add `interrupted` and `isImage` fields to Bash test fixtures

3. **Add Integration Tests**:
   - Create tests that use real event structures from daemon logs
   - Verify handlers work with actual Claude Code event format

4. **Update Documentation**:
   - Document correct `tool_response` structures for each tool type
   - Add examples from real events to handler development guide

### Files Requiring Changes

**Handler Implementation:**
- `/workspace/src/claude_code_hooks_daemon/handlers/post_tool_use/bash_error_detector.py`

**Test Files:**
- `/workspace/tests/unit/handlers/post_tool_use/test_bash_error_detector.py` (281 lines)
- `/workspace/tests/unit/handlers/post_tool_use/test_validate_eslint_on_write.py` (340 lines)
- `/workspace/tests/unit/handlers/post_tool_use/test_validate_sitemap.py` (204 lines)
- `/workspace/tests/unit/hooks/test_post_tool_use.py` (371 lines)

**Documentation:**
- `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md`
- `/workspace/CLAUDE/DEBUGGING_HOOKS.md`

## Verification Method

This report was generated by:
1. Extracting real PostToolUse events from daemon logs (200+ events analyzed)
2. Comparing against test fixtures in test files
3. Cross-referencing handler implementation code
4. Identifying structural mismatches in field names and data shapes

**Log Analysis Command Used:**
```bash
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs -n 200 -l DEBUG
```

## Conclusion

The PostToolUse test fixtures do NOT match real Claude Code event data. This is a critical issue that prevents the BashErrorDetectorHandler from working in production, while allowing tests to pass with incorrect fixtures.

**Action Required**: Update all handlers, tests, and documentation to use `tool_response` instead of `tool_output`, and remove dependencies on the non-existent `exit_code` field.
