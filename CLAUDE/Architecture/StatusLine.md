# Status Line System Architecture

**Last Updated**: July 2026

---

## Overview

The status line system provides a real-time information display in the Claude Code terminal, showing model name, context window usage, git branch, account identity, and daemon health metrics. It is implemented as a hook event type (`status_line`) processed by the daemon, so a render costs one warm socket round-trip instead of a cold Python start per update.

Claude Code calls the status line hook repeatedly during a session to refresh the terminal status bar, making it the highest-frequency surface (~0.3 renders/s observed). It is **not** free of process spawning: a render is measured at **62-66 ms, roughly 76% of it client-side spawn cost** (two `jq` spawns plus `python3` in the wrapper), with ~16 ms of git forks daemon-side. The daemon removes the per-render Python import, not the wrapper's spawns — the remaining headroom is in the wrapper. Figures from `CLAUDE/Plan/Completed/00154-daemon-performance-rust-vs-python-research/RESEARCH.md`.

---

## Architecture

### Data Flow

```
Claude Code
    |
    | Calls .claude/hooks/status-line (bash script)
    | Passes JSON via stdin: { model, context_window, workspace, ... }
    |
    v
.claude/hooks/status-line
    |
    | source .claude/init.sh (ensure daemon running)
    | jq: adds hook_event_name, wraps in {event: "Status", hook_input: ...}
    | Pipes JSON to daemon via Unix socket (send_request_stdin)
    |
    v
Daemon (Unix socket server)
    |
    | FrontController routes to EventType.STATUS_LINE
    | HandlerChain executes all matching handlers in priority order
    | All status line handlers are non-terminal (accumulate context)
    |
    v
HandlerChain returns ChainExecutionResult
    |
    | HookResult.to_json("Status") joins context[] with spaces
    | Returns: {"text": "username | Model | Ctx: 12.3% | main | hook-icon 5.2m 34MB | INFO"}
    |
    v
.claude/hooks/status-line
    |
    | jq: extracts .result.context, joins with space
    | Outputs plain text to stdout
    |
    v
Claude Code displays in terminal status bar
```

### Key Components

| Component        | Path                                                 | Role                                                       |
| ---------------- | ---------------------------------------------------- | ---------------------------------------------------------- |
| Hook script      | `.claude/hooks/status-line`                          | Entry point; forwards JSON to daemon, extracts text output |
| Init script      | `.claude/init.sh`                                    | Daemon lifecycle (ensure running, send via socket)         |
| Handler chain    | `src/claude_code_hooks_daemon/core/chain.py`         | Executes handlers in priority order, accumulates context   |
| HookResult       | `src/claude_code_hooks_daemon/core/hook_result.py`   | `to_json("Status")` joins context array into plain text    |
| Handler registry | `src/claude_code_hooks_daemon/handlers/registry.py`  | Maps `status_line` directory to `EventType.STATUS_LINE`    |
| Handlers         | `src/claude_code_hooks_daemon/handlers/status_line/` | Individual status line handlers                            |
| Configuration    | `.claude/hooks-daemon.yaml`                          | Enable/disable handlers, set priorities                    |
| Settings         | `.claude/settings.json`                              | Registers `statusLine.command` with Claude Code            |

---

## Handler Chain

All status line handlers are **non-terminal** (`terminal=False`). They all return `matches() = True` for every status event. Each handler contributes context fragments that are accumulated and joined with spaces.

### Handler Execution Order

| Priority | Handler                       | Config Key              | Output Example                                     | Data Source                                                          |
| -------- | ----------------------------- | ----------------------- | -------------------------------------------------- | -------------------------------------------------------------------- |
| 5        | `AccountDisplayHandler`       | `account_display`       | `username \|`                                      | `~/.claude/.last-launch.conf`                                        |
| 10       | `ModelContextHandler`         | `model_context`         | `Claude Opus 4.5 \| Ctx: [colored]12.3%[/colored]` | `hook_input.model`, `hook_input.context_window`, `hook_input.effort` |
| 11       | `EnvironmentIndicatorHandler` | `environment_indicator` | `\| 💻 desktop` / `\| 🐳 docker` / `\| 📦 podman`  | `ProjectContext.container_runtime()` (cached at startup)             |
| 20       | `GitBranchHandler`            | `git_branch`            | `\| main`                                          | `git branch --show-current` subprocess                               |
| 30       | `DaemonStatsHandler`          | `daemon_stats`          | `\| hook-icon 5.2m 34MB \| INFO`                   | `DaemonController.get_stats()`, `psutil`                             |
| 32       | `UpgradeNotifierHandler`      | `upgrade_notifier`      | `\| 📦 v3.41.0 → v3.42.0`                          | `version_check_cache.json` (written by `version_check` SessionStart) |

> The table lists the core informational elements. Additional status handlers exist (e.g. `git_repo_name`, `environment_indicator`, `current_time`, `supervisor_indicator`, `multithread_indicator`, `working_directory`, `startup_cleanup`, `context_sidecar`) — see `.claude/HOOKS-DAEMON.md` (regenerated by `generate-docs`) for the full, live-config list and their priorities.

### Handler Details

#### AccountDisplayHandler (Priority 5)

- **Purpose**: Shows the logged-in Claude account username
- **Data source**: Reads `~/.claude/.last-launch.conf`, extracts `LAST_TOKEN="..."` via regex
- **Output format**: `{username} |`
- **Failure mode**: Returns empty context (silent fail)

#### ModelContextHandler (Priority 10)

- **Purpose**: Shows model display name, effort-level signal bars, and colour-coded context window usage
- **Data source**: `hook_input["model"]["display_name"]` and `hook_input["context_window"]["used_percentage"]`
- **Output format**: `{model} {effort_bars} | Ctx: {colored_percentage}`
- **Colour coding** (ANSI escape codes, traffic light system):
  - 0-40%: Green background, black text
  - 41-60%: Yellow background, black text
  - 61-80%: Orange background, black text
  - 81-100%: Red background, white text
- **Failure mode**: Defaults to "Claude" model name, 0% usage
- **Effort level bars**: 5-segment bar (`▌▌▌▌▌`) over the tiers `low`/`medium`/`high`/`xhigh`/`max`, one active (orange) bar per tier position, remaining bars dim grey. Sourced primarily from the LIVE `hook_input["effort"]["level"]` field Claude Code sends on every status-line request — this is the only way to see a session-only `/effort` override, since those are never written to `~/.claude/settings.json`. Falls back to `effortLevel` in settings.json (via the shared `settings_reader.read_claude_settings()`, mtime-cached) when the live field is absent, defaulting further to `"high"` for Claude 4+ models when neither is set. An unrecognized effort string renders as the `"high"` tier's bar count rather than crashing.

#### EnvironmentIndicatorHandler (Priority 11)

- **Purpose**: Confirms at a glance whether the session runs at desktop (host) level or inside a container
- **Data source**: `ProjectContext.container_runtime()` — the container runtime is detected ONCE at daemon startup (honest OS-level markers only: `container` env var, `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup`) and cached on the frozen `ProjectContext` singleton. The handler does NO per-render probing.
- **Output format**: `| 💻 desktop` (host) / `| 🐳 docker` / `| 📦 podman` / `| 📦 container` (generic runtime)
- **Honesty note**: detection NEVER counts the tautological `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT` signals — those mean "running under Claude Code" (always true for this daemon), not "in a container"
- **Failure mode**: `container_runtime()` is `None` on a host → shows the desktop icon

#### GitBranchHandler (Priority 20)

- **Purpose**: Shows current git branch
- **Data source**: Runs `git rev-parse --show-toplevel` then `git branch --show-current` as subprocesses
- **Output format**: `| {branch_name}`
- **Working directory**: Uses `hook_input["workspace"]["current_dir"]` or `["project_dir"]`
- **Timeout**: `Timeout.GIT_STATUS_SHORT` (defined in constants)
- **Failure mode**: Returns empty context on non-git directories, subprocess errors, or timeouts

#### DaemonStatsHandler (Priority 30)

- **Purpose**: Shows daemon health metrics (developer diagnostics)
- **Default**: OFF (`get_default_enabled() -> False`, since v3.40.0). Enabled only in THIS dev repo as a documented exception.
- **Data source**: `DaemonController.get_stats()` for uptime/errors, `psutil.Process().memory_info()` for memory
- **Output format**: `| hook-icon {uptime}{memory} | {log_level}` and optionally `| error-icon {count} err`
- **Uptime formatting**: `<60s` = seconds, `<3600s` = minutes, `>=3600s` = hours
- **Memory**: Only shown if `psutil` package is available
- **Error count**: Only shown if `stats.errors > 0`
- **Note**: The `📦` upgrade arrow used to live here; it was extracted to `UpgradeNotifierHandler` (Plan 00167) so the on-by-default upgrade prompt no longer depends on this off-by-default health line.
- **Failure mode**: Returns empty context (silent fail)

#### UpgradeNotifierHandler (Priority 32)

- **Purpose**: Shows a daemon-upgrade-available prompt, independent of the developer health line
- **Default**: ON (`get_default_enabled() -> True`) — safe because it renders NOTHING unless an upgrade is genuinely available
- **Data source**: `version_check_cache.json` (in the daemon untracked dir), written by the `version_check` SessionStart handler
- **Output format**: `| 📦 v{current} → v{latest}` (or `| 📦 upgrade → v{latest}` when only the latest is known)
- **Staleness defence**: ignores a cache whose `current_version` differs from the running `__version__` (i.e. a cache written before an in-place upgrade)
- **Failure mode**: any error (missing/malformed cache, unexpected exception) → empty context (silent fail)

---

## Output Format

### How Context Fragments Become Text

1. Each handler returns `HookResult(context=[...])` with a list of string fragments
2. The `HandlerChain` accumulates all context lists from non-terminal handlers into a single list
3. `HookResult.to_json("Status")` **normalises** each fragment (strips its OUTER `|` and surrounding whitespace, preserving any INTERNAL `|`) and re-joins the surviving fragments with a single `|` separator (`_STATUS_JOIN`). Normalising both sides means a config-driven REORDER can never place two same-side segments adjacent and drop the `|` between them.
4. The result is `{"text": "joined string"}` (note: NOT the standard `hookSpecificOutput` format)
5. The bash hook script extracts `.result.context` (or `.text`) and prints it verbatim — including any embedded newlines from wrapping (below)

### Example Composed Output

```
jdoe | Claude Opus 4.5 | Ctx: [green]12.3%[/green] | main | hook-icon 5.2m 34MB | INFO
```

### Separator Convention

Handlers self-embed `|` (pipe with surrounding spaces) as the visual separator. A fragment may carry its `|` on either side (most lead with `| ...`; `AccountDisplayHandler` trails). Because `to_json` strips each fragment's outer separator and re-joins consistently, the side a handler picks no longer affects the boundary — only priority order does.

### Terminal-width-aware wrapping (Plan 00167)

When Claude Code forwards the real terminal width, the joined line wraps onto multiple rows at `|` segment boundaries so no segment ever runs off a narrow screen (Claude Code renders one terminal row per `\n`). The mechanics:

- **Width transport**: the daemon is a separate long-running process and does NOT inherit the client's `COLUMNS`/`LINES`. The jq-free transport in `init.sh` (`send_request_stdin`, Status branch) runs in the wrapper's own environment and forwards them into the Status payload as `terminal_columns` / `terminal_lines` (integers; omitted when unset or non-numeric so pre-v2.1.153 clients degrade cleanly). These are declared `["integer","null"]` in `STATUS_LINE_INPUT_SCHEMA` and survive on `HookInput` (`extra="allow"`).
- **Wrap**: `to_json` takes a `terminal_columns` argument (threaded from `controller.py`, `server.py`, and `front_controller.py`). When it is a positive int, `_wrap_status_parts` greedily first-fit-packs the normalised segments into rows no wider than the width, joined by `\n`; an oversize single segment gets its own row. When width is absent/invalid, the single-line `|` join is used (backwards-compatible).
- **Display width**: `_display_width` measures each row by stripping ANSI escapes, counting East-Asian Wide/Fullwidth code points as 2 columns and combining/format characters (e.g. ZWJ, VS16) as 0. It is dependency-free and accurate to ±1 column — acceptable because wrapping only ever breaks at whole-segment boundaries, never mid-segment.

---

## Status Input Fields (used vs available)

Claude Code sends a JSON payload on every status-line call. The daemon accepts unknown keys (`additionalProperties: True`), so any field is reachable from a handler even before the schema names it.

**Currently READ by handlers**: `model.{id,display_name}`, `context_window.*`, `workspace.{current_dir,project_dir}`, `cost`, `effort.level`, `session_id`, `session_name`, `agent_type`, plus the forwarded `terminal_columns` / `terminal_lines` (see wrapping, above).

**Documented but currently UNUSED** (available opportunistically): top-level `version`, `cwd`, `output_style`, `exceeds_200k_tokens`, `rate_limits.*`, `prompt_id`, and nested `agent.*`, `pr.*`, `worktree.*`, `vim.*`. The highest-value unused fields are `rate_limits` (a natural home for a usage indicator built from live payload data — the old `usage_tracking` handler was REMOVED in Plan 00237, so this would be new work, not a re-enable) and `version`.

> `COLUMNS` / `LINES` are NOT in this JSON — they are environment variables the `init.sh` transport forwards explicitly as `terminal_columns` / `terminal_lines`.

### Scheduled crons are not in the Status payload (feasible from disk)

A "⏰ N crons scheduled" indicator is a common request. The Status **input JSON carries no scheduled-cron information**, so it cannot be surfaced from the payload alone. It IS, however, **feasible from disk** and is documented here as a future enhancement rather than an impossibility:

- `~/.claude/jobs/<id>/state.json` records `inFlight.kinds: [session_cron]` and `selfWake: true` for backgrounded / self-waking jobs.
- `CronList` is the live per-session API for scheduled jobs.
- `~/.claude/jobs/<id>/pins.json` and per-session `~/.claude/tasks/` dirs also exist.

A status handler could read that on-disk store to render a cron indicator. Out of scope for Plan 00167 (see its Non-Goals); the enabling facts are captured here so the next attempt starts from "feasible", not "no data".

---

## Configuration

### Claude Code Settings (`settings.json`)

The status line hook is registered in `.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": ".claude/hooks/status-line"
  }
}
```

### Daemon Configuration (`hooks-daemon.yaml`)

Each handler can be enabled/disabled and have its priority overridden:

```yaml
handlers:
  status_line:
    account_display:
      enabled: true
      priority: 5

    model_context:
      enabled: true
      priority: 10

    git_branch:
      enabled: true
      priority: 20

    daemon_stats:
      enabled: true
      priority: 30
```

### Disabling a Handler

Set `enabled: false` in `hooks-daemon.yaml`:

```yaml
handlers:
  status_line:
    daemon_stats:
      enabled: false
```

### Reordering Handlers

Change the `priority` value. Lower numbers execute first and appear earlier (leftmost) in the output:

```yaml
handlers:
  status_line:
    git_branch:
      priority: 8   # Move git branch before model context
```

---

## Performance

### Why It Is Fast

1. **No process spawn**: After daemon warmup, all status updates go through an already-running Python process via Unix socket IPC. This avoids the ~200ms Python interpreter startup cost on every call.
2. **Non-terminal chain**: All handlers execute in a single pass through the chain. No early exits, no re-dispatching.
3. **Minimal I/O**: Most handlers read from in-memory state or fast local files. Only `GitBranchHandler` shells out to a subprocess.
4. **Silent failures**: Every handler catches exceptions and returns empty context rather than crashing the chain.

### Performance Characteristics by Handler

| Handler                 | I/O Type                                  | Expected Latency |
| ----------------------- | ----------------------------------------- | ---------------- |
| `AccountDisplayHandler` | File read (`~/.claude/.last-launch.conf`) | \<1ms            |
| `ModelContextHandler`   | In-memory (from hook_input)               | \<0.1ms          |
| `GitBranchHandler`      | Subprocess (`git`)                        | 5-50ms           |
| `DaemonStatsHandler`    | In-process (`get_stats()` + `psutil`)     | \<2ms            |

### Total Expected Latency

Under normal conditions, the full status line handler chain completes in **10-60ms**, dominated by the git subprocess call. Without git, it completes in under 5ms.

---

## Concurrency & Thread Safety (FIRST-CLASS CONCERN)

Status-line code is **inherently concurrent** — treat thread/process safety as a design constraint, not an afterthought:

- `handle()` runs on **every** render, and **multiple Claude sessions can share one daemon** (Plan 00127), so any shared on-disk file has concurrent readers/writers across processes.
- Several status files are also written by the **ccy PTY supervisor** — a *separate* process plus its `--worker` subprocess. `context_sidecar` writes a sidecar the supervisor reads; `supervisor_indicator` reads the `supervise/status-message.json` the supervisor writes and renders it ATTACHED to the top hat (Plan 00173).

Three non-negotiable rules (already honoured by `context_sidecar.py`, `thread_registry.py`, `supervisor_indicator.py` — mirror them in any new element):

1. **Writes are atomic-replace only.** Write to a private temp file (`.{name}.{pid}[.{tid}].tmp`), then `os.replace()` (atomic on POSIX). Never write a shared file in place; a reader must only ever see a **complete** file. Last writer wins. Skip stray `.*.tmp` files when scanning a directory.
2. **Reads are fail-silent and defensive.** A missing / malformed / partial / foreign-schema file yields **no segment**, never an exception — a broken status line is worse than a missing element. Wrap the `handle()` body so any unexpected error returns `HookResult(context=[])`.
3. **In-process shared mutable state is lock-guarded.** State touched from more than one thread (e.g. a poster's rate-limit counter) uses a `threading.Lock` around the check-and-update. Per-instance caches (e.g. `supervisor_indicator`'s memoised pid) are per-process — never assume you are the sole writer of a shared *file*.

The paired **writer-side** guidance lives at the top of `.claude/ccy/claude-supervise.py`; the package-level checklist is in `src/claude_code_hooks_daemon/handlers/status_line/CLAUDE.md`.

---

## Adding New Status Line Elements

### Step 1: Create Handler

Create a new file in `src/claude_code_hooks_daemon/handlers/status_line/`:

```python
"""My new status element handler."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Handler, HookResult


class MyElementHandler(Handler):
    """Display my element in the status line."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MY_ELEMENT,  # Add to HandlerID first
            priority=Priority.MY_ELEMENT,      # Add to Priority first
            terminal=False,                     # MUST be False for status line
            tags=[HandlerTag.STATUS, HandlerTag.NON_TERMINAL],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always run for status events."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Generate status text."""
        # Include leading separator
        return HookResult(context=["| my-data"])
```

### Step 2: Register Constants

1. Add `HandlerIDMeta` to `src/claude_code_hooks_daemon/constants/handlers.py`
2. Add priority value to `src/claude_code_hooks_daemon/constants/priority.py`
3. Add to `HandlerKey` literal type in `handlers.py`

### Step 3: Export from Package

Add the import and `__all__` entry in `src/claude_code_hooks_daemon/handlers/status_line/__init__.py`.

### Step 4: Configure

Add to `.claude/hooks-daemon.yaml` under `handlers.status_line`.

### Step 5: Write Tests

Create `tests/handlers/status_line/test_my_element.py` with tests for `matches()` and `handle()`.

### Important Rules

- **Always set `terminal=False`** -- terminal handlers would stop the chain and suppress all subsequent status elements.
- **Always return `HookResult(context=[...])`** -- never use `decision="deny"`.
- **Always fail silently** -- catch all exceptions and return `HookResult(context=[])`.
- **Include the `|` separator** in your output fragment.
- **Priority determines position** -- lower priority = further left in the status line.

---

## Troubleshooting

### Status line shows "DAEMON FAILED"

The daemon is not running. Check:

```bash
./bin/hooks-daemon status
./bin/hooks-daemon restart
```

### Status line shows "NO STATUS DATA"

All handlers returned empty context. Check:

- Are handlers enabled in `hooks-daemon.yaml`?
- Check daemon logs: `./bin/hooks-daemon logs`

### Status line shows "ERROR: ..."

The daemon returned an error. The jq in the hook script formats `.error` from the response. Check daemon logs for details.

### Git branch not showing

- Not in a git repository
- `git` command not found or not in PATH
- Git subprocess timed out (`Timeout.GIT_STATUS_SHORT`)
- Working directory from `hook_input` does not exist

### Memory not showing in daemon stats

The `psutil` package is not installed. It is an optional dependency.

### Account name not showing

- `~/.claude/.last-launch.conf` does not exist
- File does not contain `LAST_TOKEN="..."` pattern

### Context percentage always 0%

The `hook_input.context_window.used_percentage` field is not being provided by Claude Code or is null. The handler defaults to 0.

### Changing what appears in the status line

Edit `.claude/hooks-daemon.yaml` under `handlers.status_line`. Set `enabled: false` to hide elements, or adjust `priority` to reorder them. Restart the daemon after config changes.
