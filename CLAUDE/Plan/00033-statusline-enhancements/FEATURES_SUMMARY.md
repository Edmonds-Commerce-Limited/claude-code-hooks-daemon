# PowerShell Status Line Features Summary

Quick reference of all 10 features from the PowerShell implementation.

## Feature List

### HIGH Priority (5 features)

1. **Token Formatting** - Convert 50000 → "50k", 1500000 → "1.5m"
2. **Progress Bars** - Visual bars: ●●●○○○○○○○ with color coding
3. **API Usage Client** - Fetch real-time data from `/api/oauth/usage`
4. **Usage Caching** - TTL cache to reduce API calls
5. **5h/7d Windows** - Real-time 5-hour and 7-day usage tracking

### MEDIUM Priority (3 features)

6. **Reset Times** - Show when limits refresh ("3:45pm", "Feb 15, 4:30pm")
7. **Thinking Mode** - Display thinking mode status (On/Off)
8. **Multi-line Display** - 3-line output format (research needed)

### LOW Priority (2 features)

9. **Percentage Remaining** - Show both used and remaining context
10. **Extra Usage** - Display overage credits if enabled

## PowerShell Display Example

```
Line 1: Claude Sonnet 4.5 | 50k / 200k | 25% used 50,000 | 75% remain 150,000 | thinking: On
Line 2: current: ●●●○○○○○○○ 30% | weekly: ●●●●●○○○○○ 50% | extra: ●○○○○○○○○○ $5.23/$50.00
Line 3: resets 3:45pm | resets Feb 15, 4:30pm | resets Mar 1
```

## Implementation Components

### New Utilities (Phase 1)
- `format_token_count(count: int) -> str`
- `build_progress_bar(pct: float, width: int) -> str`
- `format_reset_time(iso_str: str, style: str) -> str`

### New Classes (Phase 2)
- `ApiUsageClient` - OAuth authentication and API calls
- `UsageCache` - TTL-based caching system

### New Handlers (Phase 3)
- `api_usage_five_hour.py` - 5-hour window with progress bar
- `api_usage_seven_day.py` - 7-day window with progress bar
- `api_usage_extra.py` - Extra usage credits (optional)
- `thinking_mode.py` - Thinking mode status

### Enhanced Handlers (Phase 3)
- `model_context.py` - Add token counts and remaining percentage

## Key Technical Details

**API Endpoint**: `https://api.anthropic.com/api/oauth/usage`

**Authentication**: OAuth token from `~/.claude/.credentials.json`

**Cache Location**: `~/.claude/status-line-cache.json`

**Cache TTL**: 60s (configurable)

**Progress Bar**: 10 characters wide (configurable)
- Filled: ● (U+25CF)
- Empty: ○ (U+25CB)
- Colors: green → orange → yellow → red

**Unicode Characters**:
- Filled circle: ● (U+25CF)
- Empty circle: ○ (U+25CB)

**API Response Format**:
```json
{
  "five_hour": {
    "utilization": 0.30,
    "resets_at": "2026-02-09T21:45:00Z"
  },
  "seven_day": {
    "utilization": 0.50,
    "resets_at": "2026-02-15T22:30:00Z"
  },
  "extra_usage": {
    "is_enabled": true,
    "used_credits": 523,
    "monthly_limit": 5000,
    "utilization": 0.1046
  }
}
```

## Security Notes

- ⚠️ Never log OAuth tokens
- Handle 401 (expired token) gracefully
- Silent fail on API errors (don't crash status line)
- Use timeout on API calls (non-blocking)

## See Also

- `PLAN.md` - Complete implementation plan with TDD tasks
- `powershell-reference.ps1` - Full PowerShell source code
