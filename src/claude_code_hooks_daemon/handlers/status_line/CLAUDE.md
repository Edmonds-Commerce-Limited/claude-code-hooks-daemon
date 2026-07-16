# Status Line Handlers

This directory contains all handlers for the `status_line` hook event type. These handlers generate the terminal status line displayed by Claude Code, showing model info, context usage, git branch, account details, and daemon health.

**Architecture documentation**: See [CLAUDE/Architecture/StatusLine.md](/CLAUDE/Architecture/StatusLine.md) for the single source of truth on the status line system design, handler chain, output format, configuration, and how to add new elements.

## Handlers

| File                       | Handler                       | Priority | Description                                                                                                                                                   |
| -------------------------- | ----------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git_repo_name.py`         | `GitRepoNameHandler`          | 3        | Shows git repository name at start (cached for performance)                                                                                                   |
| `environment_indicator.py` | `EnvironmentIndicatorHandler` | 4        | Shows 💻 desktop / 🐳 docker / 📦 podman / 🧊 lxc from the runtime `ProjectContext` cached at startup                                                         |
| `account_display.py`       | `AccountDisplayHandler`       | 5        | Reads Claude account username from `~/.claude/.last-launch.conf`                                                                                              |
| `model_context.py`         | `ModelContextHandler`         | 10       | Formats color-coded model name (blue=Haiku, green=Sonnet, orange=Opus), 5-tier effort signal bars, and context percentage                                     |
| `usage_tracking.py`        | `UsageTrackingHandler`        | 15       | Daily/weekly token usage percentages (currently disabled - needs rework)                                                                                      |
| `git_branch.py`            | `GitBranchHandler`            | 20       | Shows current git branch name (pink name + 🌳 when inside a linked worktree)                                                                                  |
| `daemon_stats.py`          | `DaemonStatsHandler`          | 30       | Shows daemon uptime, memory usage, log level, and error count (developer diagnostics; OFF by default, on here as a dev-repo exception)                        |
| `upgrade_notifier.py`      | `UpgradeNotifierHandler`      | 32       | Shows `📦 vX → vY` when a newer daemon version is available (ON by default; reads `version_check_cache.json`). Extracted from `daemon_stats.py` in Plan 00167 |

> This table lists the core informational elements. Several more status handlers exist (`supervisor_indicator`, `multithread_indicator`, `current_time`, `working_directory`, `startup_cleanup`, `context_sidecar`, …) — see `.claude/HOOKS-DAEMON.md` for the full live-config list. The assembled line is **width-aware**: when Claude Code forwards the terminal width (`terminal_columns`, via the `init.sh` transport), `hook_result.py` wraps the segments onto multiple rows at `|` boundaries so nothing is lost on a narrow screen (Plan 00167).

## Supporting Modules

| File                    | Description                                                                       |
| ----------------------- | --------------------------------------------------------------------------------- |
| `stats_cache_reader.py` | Utility for reading `~/.claude/stats-cache.json` (used by `UsageTrackingHandler`) |
| `settings_reader.py`    | mtime-cached reader for `~/.claude/settings.json` (used by `ModelContextHandler`) |
