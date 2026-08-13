# Status Line Handlers

This directory contains all handlers for the `status_line` hook event type. These handlers generate the terminal status line displayed by Claude Code, showing model info, context usage, git branch, account details, and daemon health.

**Architecture documentation**: See [CLAUDE/Architecture/StatusLine.md](/CLAUDE/Architecture/StatusLine.md) for the single source of truth on the status line system design, handler chain, output format, configuration, and how to add new elements.

## Handlers

| File                       | Handler                       | Priority | Description                                                                                                                                                   |
| -------------------------- | ----------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git_repo_name.py`         | `GitRepoNameHandler`          | 3        | Shows git repository name at start (cached for performance)                                                                                                   |
| `environment_indicator.py` | `EnvironmentIndicatorHandler` | 4        | Shows 💻 desktop / 🐳 docker / 📦 podman / 🧊 lxc from the runtime `ProjectContext` cached at startup                                                         |
| `account_display.py`       | `AccountDisplayHandler`       | 5        | Reads Claude account username from `~/.claude/.last-launch.conf`                                                                                              |
| `model_context.py`         | `ModelContextHandler`         | 10       | Formats colour-coded model name (blue=Haiku, green=Sonnet, orange=Opus), 5-tier effort signal bars, and context percentage                                    |
| `git_branch.py`            | `GitBranchHandler`            | 20       | Shows current git branch name (🌳 prefix + pink name when inside a linked worktree)                                                                           |
| `daemon_stats.py`          | `DaemonStatsHandler`          | 30       | Shows daemon uptime, memory usage, log level, and error count (developer diagnostics; OFF by default, on here as a dev-repo exception)                        |
| `upgrade_notifier.py`      | `UpgradeNotifierHandler`      | 32       | Shows `📦 vX → vY` when a newer daemon version is available (ON by default; reads `version_check_cache.json`). Extracted from `daemon_stats.py` in Plan 00167 |

> This table lists the core informational elements. Several more status handlers exist (`supervisor_indicator`, `multithread_indicator`, `current_time`, `working_directory`, `startup_cleanup`, `context_sidecar`, …) — see `.claude/HOOKS-DAEMON.md` for the full live-config list. The assembled line is **width-aware**: when Claude Code forwards the terminal width (`terminal_columns`, via the `init.sh` transport), `hook_result.py` wraps the segments onto multiple rows at `|` boundaries so nothing is lost on a narrow screen (Plan 00167).

## Thread Safety / Concurrency (FIRST-CLASS CONCERN)

**Read this before adding or changing any status-line handler that touches a
file or shared in-memory state.** Status-line code is inherently concurrent:

- `handle()` runs on **every** status render, and **multiple Claude sessions
  can share one daemon** (Plan 00127) — so shared on-disk files have concurrent
  readers/writers across processes.
- Several files here are also written by the **ccy PTY supervisor**, a
  *separate* process (and its `--worker` subprocess) — e.g. `context_sidecar`
  writes a sidecar the supervisor reads, and `supervisor_indicator` **reads**
  the transient message file the supervisor **writes** (rendering it attached to
  the top hat).

Non-negotiable rules (already followed by `context_sidecar.py`,
`thread_registry.py`, `supervisor_indicator.py` — match them):

1. **Writes are atomic-replace only.** Write to a private temp file
   (`.{name}.{pid}[.{tid}].tmp`) then `os.replace()` (atomic on POSIX) — never
   write a shared file in place. A reader then always sees a **complete** file,
   never a partial one; last writer wins. Skip stray `.*.tmp` files when
   scanning a directory (see `thread_registry.py`).
2. **Reads are fail-silent and defensive.** A missing / malformed / partial /
   foreign-schema file must yield "no segment", **never** raise — a broken
   status line is worse than a missing element. Wrap `handle()` bodies so any
   unexpected error returns `HookResult(context=[])` (see `daemon_stats.py`,
   `supervisor_indicator.py`).
3. **In-memory caches are per-process and must tolerate concurrent peers.** A
   handler instance's caches (e.g. `supervisor_indicator`'s memoised pid) live
   in one daemon process; never assume you are the only writer of a shared
   *file*, and guard any state shared across threads with a `threading.Lock`.

The paired writer-side guidance lives at the top of
`.claude/ccy/claude-supervise.py` and in
[CLAUDE/Architecture/StatusLine.md](/CLAUDE/Architecture/StatusLine.md).

## Supporting Modules

| File                 | Description                                                                       |
| -------------------- | --------------------------------------------------------------------------------- |
| `settings_reader.py` | mtime-cached reader for `~/.claude/settings.json` (used by `ModelContextHandler`) |
