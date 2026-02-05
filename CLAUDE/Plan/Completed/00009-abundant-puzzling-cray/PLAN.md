# Status Line Enhancement Plan

## Overview

Fix critical TypeError bug and enhance status line with account display and usage tracking.

**Current Issues:**
1. TypeError: `used_percentage` can be `None`, causing `'<=' not supported between NoneType and int`
2. Schema validation rejects `None` values in strict mode before reaching handler
3. No account display in status line
4. No daily/weekly usage tracking

## Critical Findings

### Bug Root Causes (Two Issues)
1. **Handler Bug** (`model_context.py:42`): `.get("used_percentage", 0)` returns `None` if key exists with null value
2. **Schema Bug** (`input_schemas.py`): `STATUS_LINE_INPUT_SCHEMA` defines `used_percentage` as `{"type": "number"}` which rejects `null`

### Current Architecture
- 3 status line handlers: ModelContextHandler (10), GitBranchHandler (20), DaemonStatsHandler (30)
- All handlers registered and enabled (dogfooding verified)
- Daemon running in self-install mode at `/workspace`
- Strict validation enabled: `input_validation.strict_mode: true`

### Data Sources Available
- **Account**: `~/.claude/.last-launch.conf` contains `LAST_TOKEN="ballicom_rohil"`
- **Usage**: `~/.claude/stats-cache.json` contains `dailyModelTokens` with token counts per day/model
- **Context**: Hook input provides `model.display_name`, `context_window.used_percentage`

## Implementation Plan

### Phase 1: Fix Schema Validation (CRITICAL)

**1.1 Update Input Schema**
- File: `src/claude_code_hooks_daemon/core/input_schemas.py`
- Line ~245: Change `used_percentage` schema:
  ```python
  # Before:
  "used_percentage": {"type": "number"}

  # After:
  "used_percentage": {"type": ["number", "null"]}
  ```
- Also update: `total_input_tokens`, `context_window_size` (may also be null)

**1.2 Write Test for Schema Change**
- File: `tests/unit/core/test_input_schemas.py`
- Add test: `test_status_line_schema_allows_null_used_percentage`
- Verify schema validation passes with `null` values

### Phase 2: Fix Handler Bug

**2.1 Write Failing Test**
- File: `tests/unit/handlers/status_line/test_model_context.py`
- Add test: `test_handle_with_null_used_percentage`
- Input: `{"context_window": {"used_percentage": None}}`
- Expected: Should not raise TypeError, should default to 0.0%

**2.2 Implement Handler Fix**
- File: `src/claude_code_hooks_daemon/handlers/status_line/model_context.py:42`
- Change: `used_pct = ctx_data.get("used_percentage", 0)`
- To: `used_pct = ctx_data.get("used_percentage") or 0`

**2.3 Verify Fix**
- Run: `pytest tests/unit/handlers/status_line/test_model_context.py -v`
- Test with daemon: `echo '{"hook_event_name":"Status","context_window":{"used_percentage":null}}' | .claude/hooks/status-line`

### Phase 3: Account Display Handler

**3.1 Create Handler**
- File: `src/claude_code_hooks_daemon/handlers/status_line/account_display.py`
- Class: `AccountDisplayHandler(Handler)`
- Priority: 5 (before ModelContextHandler)
- Logic:
  ```python
  def handle(self, hook_input: dict[str, Any]) -> HookResult:
      try:
          conf_path = Path.home() / ".claude" / ".last-launch.conf"
          if not conf_path.exists():
              return HookResult(context=[])

          content = conf_path.read_text()
          match = re.search(r'LAST_TOKEN="([^"]+)"', content)
          if not match:
              return HookResult(context=[])

          username = match.group(1)
          return HookResult(context=[f"{username} |"])
      except Exception:
          return HookResult(context=[])  # Silent fail
  ```

**3.2 Create Tests**
- File: `tests/unit/handlers/status_line/test_account_display.py`
- Tests: handler properties, matches(), valid conf file, missing file, invalid format

**3.3 Register Handler**
- File: `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`
- Add import and export

**3.4 Add to Config**
- File: `.claude/hooks-daemon.yaml`
- Add under `status_line:`:
  ```yaml
  account_display:
    enabled: true
    priority: 5
  ```

### Phase 4: Usage Tracking Handler

**4.1 Create Stats Reader Utility**
- File: `src/claude_code_hooks_daemon/handlers/status_line/stats_cache_reader.py`
- Functions:
  - `read_stats_cache(path: Path) -> dict | None`
  - `calculate_daily_usage(cache_data: dict, model_id: str) -> float`
  - `calculate_weekly_usage(cache_data: dict, model_id: str) -> float`
- Token limits:
  ```python
  DAILY_LIMITS = {
      "claude-sonnet-4-5-20250929": 200_000,
      "claude-opus-4-5-20251101": 100_000,
  }
  ```

**4.2 Create Tests for Stats Reader**
- File: `tests/unit/handlers/status_line/test_stats_cache_reader.py`
- Test file reading, daily/weekly calculations, missing data handling

**4.3 Create Usage Handler**
- File: `src/claude_code_hooks_daemon/handlers/status_line/usage_tracking.py`
- Class: `UsageTrackingHandler(Handler)`
- Priority: 15 (after ModelContext, before Git)
- Features: Read stats-cache.json, calculate percentages, cache with 10s TTL
- Format: `"| daily: XX% | weekly: XX%"`

**4.4 Create Tests for Usage Handler**
- File: `tests/unit/handlers/status_line/test_usage_tracking.py`
- Test handler with mock data, caching, options (show_daily/weekly)

**4.5 Register Handler**
- File: `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`
- Add import and export

**4.6 Add to Config**
- File: `.claude/hooks-daemon.yaml`
- Add under `status_line:`:
  ```yaml
  usage_tracking:
    enabled: true
    priority: 15
    options:
      show_daily: true
      show_weekly: true
      cache_ttl_seconds: 10
  ```

### Phase 5: Integration & Testing

**5.1 Run QA Suite**
```bash
./scripts/qa/run_all.sh
```

**5.2 Manual Testing**
```bash
# Restart daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart

# Test status line
# Expected: "ballicom_rohil | Sonnet 4.5 | Ctx: 42.5% | daily: 15% | weekly: 45% | main | ⚡ 5m 12MB INFO"
```

**5.3 Verify with null values**
```bash
echo '{"hook_event_name":"Status","context_window":{"used_percentage":null}}' | .claude/hooks/status-line
# Should return default status without errors
```

## Critical Files

### Modified Files
1. `src/claude_code_hooks_daemon/core/input_schemas.py` - Allow null in schema
2. `src/claude_code_hooks_daemon/handlers/status_line/model_context.py:42` - Fix null handling
3. `tests/unit/handlers/status_line/test_model_context.py` - Add null test
4. `tests/unit/core/test_input_schemas.py` - Add schema test
5. `src/claude_code_hooks_daemon/handlers/status_line/__init__.py` - Register new handlers
6. `.claude/hooks-daemon.yaml` - Add new handler configs

### New Files
1. `src/claude_code_hooks_daemon/handlers/status_line/account_display.py`
2. `tests/unit/handlers/status_line/test_account_display.py`
3. `src/claude_code_hooks_daemon/handlers/status_line/stats_cache_reader.py`
4. `tests/unit/handlers/status_line/test_stats_cache_reader.py`
5. `src/claude_code_hooks_daemon/handlers/status_line/usage_tracking.py`
6. `tests/unit/handlers/status_line/test_usage_tracking.py`

## Expected Output

**Before:**
```
Sonnet 4.5 | Ctx: 42.5% | main | ⚡ 5m 12MB INFO
```

**After:**
```
ballicom_rohil | Sonnet 4.5 | Ctx: 42.5% | daily: 15% | weekly: 45% | main | ⚡ 5m 12MB INFO
```

**Handler Order:**
1. AccountDisplayHandler (5): `"ballicom_rohil |"`
2. ModelContextHandler (10): `"Sonnet 4.5 | Ctx: 42.5%"`
3. UsageTrackingHandler (15): `"| daily: 15% | weekly: 45%"`
4. GitBranchHandler (20): `"| main"`
5. DaemonStatsHandler (30): `"| ⚡ 5m 12MB INFO"`

## Verification Steps

1. **Schema Fix**: Input validation logs should no longer show errors for null values
2. **Handler Fix**: Status line should render with 0% when used_percentage is null
3. **Account Display**: Should show username from .last-launch.conf
4. **Usage Tracking**: Should show daily/weekly percentages from stats-cache.json
5. **Performance**: Status line should render in < 50ms
6. **QA**: All tests pass, 95% coverage maintained

## Success Criteria

- [ ] Schema allows null values for context_window fields
- [ ] Handler gracefully handles null used_percentage
- [ ] Account name displays correctly
- [ ] Daily/weekly usage percentages calculated correctly
- [ ] All handlers work together in correct priority order
- [ ] No validation errors in daemon logs
- [ ] QA suite passes
- [ ] Dogfooding test still passes (all handlers enabled)
