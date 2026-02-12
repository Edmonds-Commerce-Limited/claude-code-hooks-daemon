# Status Line Handlers

This directory contains all handlers for the `status_line` hook event type. These handlers generate the terminal status line displayed by Claude Code, showing model info, context usage, git branch, account details, and daemon health.

**Architecture documentation**: See [CLAUDE/Architecture/StatusLine.md](/CLAUDE/Architecture/StatusLine.md) for the single source of truth on the status line system design, handler chain, output format, configuration, and how to add new elements.

## Handlers

| File | Handler | Priority | Description |
|------|---------|----------|-------------|
| `git_repo_name.py` | `GitRepoNameHandler` | 3 | Shows git repository name at start (cached for performance) |
| `account_display.py` | `AccountDisplayHandler` | 5 | Reads Claude account username from `~/.claude/.last-launch.conf` |
| `model_context.py` | `ModelContextHandler` | 10 | Formats color-coded model name (blue=Haiku, green=Sonnet, orange=Opus) and context percentage |
| `usage_tracking.py` | `UsageTrackingHandler` | 15 | Daily/weekly token usage percentages (currently disabled - needs rework) |
| `git_branch.py` | `GitBranchHandler` | 20 | Shows current git branch name |
| `thinking_mode.py` | `ThinkingModeHandler` | 12 | Shows thinking mode On/Off and effort level from `~/.claude/settings.json` |
| `daemon_stats.py` | `DaemonStatsHandler` | 30 | Shows daemon uptime, memory usage, log level, and error count |

## Supporting Modules

| File | Description |
|------|-------------|
| `stats_cache_reader.py` | Utility for reading `~/.claude/stats-cache.json` (used by `UsageTrackingHandler`) |
