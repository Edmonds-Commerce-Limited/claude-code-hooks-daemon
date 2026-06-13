# Status-Line Handler Memoisation Audit

> Audit of every handler in `src/claude_code_hooks_daemon/handlers/status_line/` for per-render cost and caching. The status line is re-rendered by Claude Code on **every refresh** (frequently), so any per-render subprocess / file I/O / network / heavy compute is wasteful and should be memoised by the daemon. Pure-compute and in-memory reads are fine.

## Summary Table

| Handler                                         | Per-render work                                                                                                                                               | Cached?                                                                             | Verdict                                              |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `git_repo_name` (`GitRepoNameHandler`)          | Read `ProjectContext.git_repo_name()` (startup singleton attribute)                                                                                           | ✅ Yes — computed once at daemon `initialize()`                                     | **OK**                                               |
| `current_time` (`CurrentTimeHandler`)           | `datetime.now().strftime("%H:%M")` — pure compute                                                                                                             | n/a — must be live                                                                  | **OK** (correctly NOT cached)                        |
| `model_context` (`ModelContextHandler`)         | **File read** `~/.claude/settings.json` (every render, via `_read_effort_level`) + regex + pure compute                                                       | ❌ No — `read_text()` + `json.loads()` per render                                   | **SHOULD-MEMOISE** (file read)                       |
| `thinking_mode` (`ThinkingModeHandler`)         | **File read** `~/.claude/settings.json` (every render, via `_read_settings`)                                                                                  | ❌ No — `read_text()` + `json.loads()` per render                                   | **SHOULD-MEMOISE** (file read)                       |
| `working_directory` (`WorkingDirectoryHandler`) | Path compare from `hook_input` workspace dict — pure compute                                                                                                  | n/a — derives from event payload                                                    | **OK**                                               |
| `account_display` (`AccountDisplayHandler`)     | **File read** `~/.claude/.last-launch.conf` + regex (every render)                                                                                            | ❌ No — `read_text()` per render                                                    | **SHOULD-MEMOISE** (file read; near-invariant)       |
| `daemon_stats` (`DaemonStatsHandler`)           | In-memory stats + `psutil` proc RSS read + in-memory block count + **file read** `version_check_cache.json`                                                   | ⚠️ Partial — stats/blocks in-memory; psutil + version-cache file read per render    | **SHOULD-MEMOISE** (proc read + file read)           |
| `startup_cleanup` (`StartupCleanupHandler`)     | **File read** `cleanup_status.json`, but only within a 30s post-startup window                                                                                | ❌ No, but self-limiting to ~30s after start                                        | **OK** (bounded; see nuance)                         |
| `usage_tracking` (`UsageTrackingHandler`)       | **File read** `~/.claude/stats-cache.json` + date compute                                                                                                     | ❌ No (but `matches()` returns `False` — handler is DISABLED)                       | **OK while disabled** / SHOULD-MEMOISE if re-enabled |
| `git_branch` (`GitBranchHandler`)               | **3–5 git subprocesses** per render (`rev-parse`, `branch --show-current`, `status --porcelain=v2`, `stash list`, + default-branch detection on first render) | ⚠️ Partial — default branch memoised after first render; everything else recomputed | **EXPENSIVE** (subprocess per render)                |
| `stats_cache_reader` (module, helper)           | File read + date compute — only invoked by disabled `usage_tracking`                                                                                          | n/a — pure helper, no handler                                                       | **OK** (dead path while usage_tracking disabled)     |

**Net classification:** 1 EXPENSIVE (`git_branch`), 4 SHOULD-MEMOISE (`model_context`, `thinking_mode`, `account_display`, `daemon_stats`), the rest OK.

---

## Per-Handler Detail

### `git_repo_name` — `GitRepoNameHandler` — OK

- **Work:** `handle()` returns `f"📁 {ProjectContext.git_repo_name()}"`.
  - `git_repo_name.py:43` — `repo_name = ProjectContext.git_repo_name()`.
- **Caching:** `ProjectContext.git_repo_name()` (`core/project_context.py:344-358`) returns `cls._instance.git_repo_name`, a frozen attribute on the startup singleton populated once in `initialize()` (`core/project_context.py:127`, `:160`). The git subprocess that derives the name (`_get_git_repo_name`) runs **once at daemon startup**, never per render.
- **Verdict:** **OK** — repo name is invariant and correctly cached at startup. This is the model the other handlers should follow.

### `current_time` — `CurrentTimeHandler` — OK (must stay live)

- **Work:** `current_time.py:28-29` — `datetime.now().strftime("%H:%M")`. Pure compute, no I/O.
- **Caching:** None, by design.
- **Verdict:** **OK.** This is the one handler that *must not* be cached — the displayed clock has to advance with each render. Memoising it would freeze the clock. Pure `datetime.now()` is negligible cost. **Note: do not "fix" this.**

### `model_context` — `ModelContextHandler` — SHOULD-MEMOISE (file read)

- **Work:** Most output is pure compute from `hook_input` (model name colour, context-percentage tier). The cost is the effort-bar lookup:
  - `model_context.py:159` — `effort_suffix = self._get_effort_suffix(...)` →
  - `model_context.py:186` — `_read_effort_level(model_id)` →
  - `model_context.py:216-219` — `settings_path.exists()` + `settings_path.read_text()` + `json.loads(raw)` on `~/.claude/settings.json` **every render**.
- **Caching:** None. The file is opened, read and JSON-parsed on each refresh.
- **Invariant:** `~/.claude/settings.json` changes rarely (only when the user runs `/model` or edits config). `effortLevel` is effectively static within a session.
- **Cheapest fix:** Share a single mtime-keyed settings cache (see Fix #2) — this handler and `thinking_mode` read the *same* file, so a module-level `~/.claude/settings.json` reader with `os.stat().st_mtime` invalidation (or a short TTL, e.g. 5s) eliminates two redundant reads per render.
- **Verdict:** **SHOULD-MEMOISE.**

### `thinking_mode` — `ThinkingModeHandler` — SHOULD-MEMOISE (file read)

- **Work:** `thinking_mode.py:46` — `settings = self._read_settings()` →
  - `thinking_mode.py:73-81` — `settings_path.exists()` + `read_text()` + `json.loads(raw)` on `~/.claude/settings.json` **every render**. Only one key (`alwaysThinkingEnabled`) is consulted.
- **Caching:** None.
- **Invariant:** Same `~/.claude/settings.json` as `model_context`. Static within a session except on explicit toggle.
- **Cheapest fix:** Same shared mtime/TTL-cached settings reader as Fix #2. This handler + `model_context` currently perform **two** independent stat+read+parse cycles of the identical file on every refresh.
- **Verdict:** **SHOULD-MEMOISE.**

### `working_directory` — `WorkingDirectoryHandler` — OK

- **Work:** `working_directory.py:35-57` — reads `current_dir`/`project_dir` from the `hook_input["workspace"]` dict, constructs `Path` objects, compares, computes `relative_to`. Pure compute on data already supplied in the event payload. No filesystem stat, no subprocess.
- **Caching:** Not applicable — derives entirely from the per-event payload (and the cwd legitimately varies between renders).
- **Verdict:** **OK** — cheap pure compute.

### `account_display` — `AccountDisplayHandler` — SHOULD-MEMOISE (file read; near-invariant)

- **Work:** `account_display.py:40-49` — `conf_path.exists()` + `conf_path.read_text()` on `~/.claude/.last-launch.conf` + `re.search` **every render**.
- **Caching:** None.
- **Invariant:** The account username changes only when the user logs in / switches accounts — essentially once per launch. It is one of the most clearly invariant values on the status line, yet it re-reads and re-regexes a file on every refresh.
- **Cheapest fix:** mtime-keyed module-level cache, or compute once and cache for the daemon lifetime with mtime invalidation (Fix #3). A simple `functools.lru_cache` keyed on `(path, st_mtime_ns)` is sufficient.
- **Verdict:** **SHOULD-MEMOISE.**

### `daemon_stats` — `DaemonStatsHandler` — SHOULD-MEMOISE (proc read + file read)

- **Work (mixed):**
  - In-memory & cheap: `get_controller().get_stats()` (`daemon_stats.py:59-60`) returns the live `_stats` object (`daemon/controller.py:703-709`); `uptime_seconds` is a `time.time()` delta and `errors` is an int counter. Block count `get_data_layer().history.count_blocks()` (`daemon_stats.py:96`) is an in-memory bounded-`deque` scan (`core/handler_history.py:126-132`). These are fine.
  - **Per-render process read:** `daemon_stats.py:75-76` — `psutil.Process()` + `process.memory_info().rss`. Reads `/proc/self` (procfs) on every render to report RSS in MB.
  - **Per-render file read:** `daemon_stats.py:104-106` — `ProjectContext.daemon_untracked_dir() / "version_check_cache.json"` `.exists()` + `read_text()` + `json.loads()` on every render.
- **Caching:** None for the psutil read or the version-cache file read. The version cache is itself a TTL artifact written by `version_check`, but `daemon_stats` re-reads/parses it from disk on every single refresh rather than reading it once per TTL window.
- **Invariants:** RSS drifts slowly — a 2–5s TTL is imperceptible on a status line. The version-cache file changes at most once per `version_check` interval (hours).
- **Cheapest fix:** (a) Wrap the psutil RSS read in a short TTL (e.g. 2–5s) memo. (b) Read+parse `version_check_cache.json` behind an mtime/TTL cache instead of every render (Fix #4).
- **Verdict:** **SHOULD-MEMOISE** (procfs read + file read per render).

### `startup_cleanup` — `StartupCleanupHandler` — OK (bounded; minor nuance)

- **Work:** `startup_cleanup.py:50-57` — `status_file.exists()` + `read_text()` + `json.loads()` on `cleanup_status.json`, then `time.time() - timestamp`.
- **Caching:** None, but the handler returns early (empty) after `_DISPLAY_WINDOW_SECONDS = 30` (`startup_cleanup.py:18`, `:61`). The expensive read therefore only happens during the first ~30 seconds after daemon start; for the rest of the session it still does `exists()` + `read_text()` even though the result will always be "outside window".
- **Nuance:** A micro-optimisation would be a module-level boolean latch that, once `elapsed >= 30s` has been observed, short-circuits future renders to `exists()`-only or skips entirely. Given the file is tiny and the window is short, impact is low.
- **Verdict:** **OK** — bounded, low-impact. Optional latch noted under Fix #5 (low priority).

### `usage_tracking` — `UsageTrackingHandler` — OK while disabled (would be SHOULD-MEMOISE)

- **Work:** `usage_tracking.py:77-84` — `read_stats_cache(~/.claude/stats-cache.json)` (file read + JSON parse) + `calculate_daily_usage` / `calculate_weekly_usage` (date math over the cache array). The in-code comment at `usage_tracking.py:76` ("it's fast, no need for TTL caching") understates that this is a per-render file read + parse.
- **Caching:** None.
- **Current status:** `matches()` returns `False` (`usage_tracking.py:47-50`) — the handler is **DISABLED** and never dispatched, so it costs nothing today. It is also absent from the live `Status` chain in `.claude/HOOKS-DAEMON.md`.
- **Verdict:** **OK while disabled.** If re-enabled it becomes **SHOULD-MEMOISE** (mtime/TTL-cache the stats-cache read).

### `stats_cache_reader` (module helper) — OK (dead path)

- **Work:** `read_stats_cache` (`stats_cache_reader.py:19-38`) does `path.exists()` + `read_text()` + `json.loads()`; `calculate_daily_usage` / `calculate_weekly_usage` do `datetime.now()` date math over the cache array.
- **Caching:** None — but it is a pure helper with no handler of its own; only `usage_tracking` (disabled) calls it.
- **Verdict:** **OK** (currently a dead path). Any caching belongs in the caller (`usage_tracking`) if/when re-enabled.

---

## `git_branch` — Detailed Nuance (the worst offender)

`GitBranchHandler.handle()` is the only handler that shells out per render, and it does so **multiple times**:

1. `git_branch.py:80-86` — `git rev-parse --show-toplevel` (is-this-a-repo probe).
2. `git_branch.py:91-97` — `git branch --show-current`.
3. First render only: `git_branch.py:101-103` → `_get_default_branch()` runs `git symbolic-ref refs/remotes/origin/HEAD` and possibly two `git show-ref` calls (`git_branch.py:129-150`). This **is** memoised via `self._default_branch` / `self._default_branch_detected` (`git_branch.py:57-58`, `:101-104`) — good.
4. `git_branch.py:110` → `_format_git_status_icons()` → `git status --porcelain=v2 --branch` (`git_branch.py:168-174`).
5. `git_branch.py:181` → `_get_stash_count()` → `git stash list` (`git_branch.py:280-286`).

So **steady-state cost is ~4 git subprocess spawns per render** (probe + show-current + status + stash list), each with a `Timeout.GIT_STATUS_SHORT = 0.5s` ceiling (`constants/timeout.py:53`). On a frequently-refreshing status line this is the dominant cost in the whole chain.

**Legitimate nuance (why it can't be fully cached):** the ahead/behind/staged/changed/untracked/conflict/stash counts are *live working-tree state* that changes as the user works — that is the entire point of the icons. Caching them with a long TTL would show stale dirty/clean state, which is misleading. So unlike repo-name (invariant) this handler genuinely must observe current state.

**However, several reductions are safe:**

- **Collapse the repo probe.** `git rev-parse --show-toplevel` (call 1) duplicates information the daemon already has: `ProjectContext` resolves the git toplevel once at startup (`git_toplevel()` / `_get_git_toplevel`, `core/project_context.py:361-377`). The standalone repo probe per render is redundant for the dogfooded project root; it is only needed when `cwd` may be a different/non-repo directory. Gate the probe on whether `cwd` is inside the known toplevel.
- **Drop / coalesce the current-branch call.** `git status --porcelain=v2 --branch` (call 4) already emits the branch via the `# branch.head` line — the separate `git branch --show-current` (call 2) is redundant and could be parsed out of the porcelain output the handler already collects, removing one spawn.
- **Short TTL on the whole icon block.** A small TTL (e.g. 1–2s) on the combined status+stash result keeps the line responsive while collapsing the burst of renders Claude Code fires in quick succession (multiple refreshes per second during streaming) down to one git call per TTL window. Working-tree changes still surface within ~1–2s — imperceptible to a human but eliminating the per-keystroke subprocess storm.
- **`git stash list`** (call 5) is the cheapest to fold into the same TTL window as the status read.

**Verdict:** **EXPENSIVE** — up to 5 subprocess spawns on first render, ~4 per render steady-state. Default-branch detection is already correctly memoised; the live-state reads cannot be long-cached but can be (a) de-duplicated (drop calls 1 & 2) and (b) burst-coalesced behind a 1–2s TTL.

---

## Prioritised Memoisation Fixes

Ordered by per-render cost eliminated × render frequency.

### Fix #1 — `git_branch`: de-duplicate + burst-coalesce git calls (HIGHEST IMPACT)

- **Problem:** ~4 git subprocess spawns per render (`git_branch.py:80, 91, 168, 280`), 0.5s timeout each.
- **Fix:**
  1. Gate the `git rev-parse --show-toplevel` probe (call 1) on `cwd` not already being inside `ProjectContext.git_toplevel()`.
  2. Parse the branch name from the `# branch.head` line of the `--porcelain=v2 --branch` output already collected, and remove the separate `git branch --show-current` (call 2).
  3. Wrap the combined `status --porcelain=v2` + `stash list` result in a short TTL (1–2s) keyed on `cwd`, so the rapid burst of refreshes Claude Code fires collapses to one git invocation per window.
- **Invariant exploited:** repo toplevel is startup-invariant; branch name is already in porcelain output; live counts tolerate a 1–2s staleness window.
- **Net:** ~4 spawns/render → ~1 spawn per 1–2s window. Largest win in the chain.

### Fix #2 — Shared `~/.claude/settings.json` reader for `model_context` + `thinking_mode`

- **Problem:** Two handlers each do `exists()` + `read_text()` + `json.loads()` of the **same** file every render (`model_context.py:217-219`, `thinking_mode.py:75-81`) — two redundant parses per refresh.
- **Fix:** Module-level (or `ProjectContext`-level) settings reader memoised on `(path, st_mtime_ns)` — one stat per render, re-parse only when the file changes. Both handlers consume it.
- **Invariant exploited:** settings file changes only on `/model` or manual edit.
- **Net:** 2 file reads + 2 JSON parses/render → 1 stat/render, parse only on change.

### Fix #3 — `account_display`: mtime-cache `.last-launch.conf`

- **Problem:** `read_text()` + regex of `~/.claude/.last-launch.conf` every render (`account_display.py:44-48`).
- **Fix:** `functools.lru_cache` (or module dict) keyed on `(path, st_mtime_ns)`; one stat per render, re-read+regex only on change.
- **Invariant exploited:** username changes ~once per launch — among the most invariant values displayed.

### Fix #4 — `daemon_stats`: TTL the psutil RSS read and the version-cache file read

- **Problem:** procfs RSS read (`daemon_stats.py:75-76`) and `version_check_cache.json` read+parse (`daemon_stats.py:104-106`) every render.
- **Fix:** (a) memoise RSS behind a 2–5s TTL; (b) read+parse the version cache behind an mtime/TTL cache (it changes at most once per `version_check` interval).
- **Invariant exploited:** RSS drifts slowly; version cache updates hours apart.
- **Note:** the in-memory `get_stats()` and `count_blocks()` parts are already cheap — leave them.

### Fix #5 — `startup_cleanup`: latch off after the 30s window (LOW PRIORITY)

- **Problem:** `exists()` + `read_text()` of `cleanup_status.json` continues every render even though the result is always empty after 30s (`startup_cleanup.py:50-61`).
- **Fix:** module-level boolean latch set once `elapsed >= _DISPLAY_WINDOW_SECONDS` is observed, short-circuiting future renders.
- **Impact:** low (tiny file, short window) — opportunistic only.

### Fix #6 — `usage_tracking`: pre-emptive (only if re-enabled)

- Currently disabled (`matches()` → `False`); no action needed today. If re-enabled, mtime/TTL-cache the `stats-cache.json` read (`usage_tracking.py:77-78`).

### Do NOT change

- **`current_time`** — must stay live (`datetime.now()` per render is correct; caching would freeze the clock).
- **`git_repo_name`** — already startup-cached via `ProjectContext`; reference implementation for the others.
- **`working_directory`** — pure compute from the event payload; nothing to cache.
- **`git_branch` live counts** — do not long-cache the dirty/clean state; only de-dupe redundant calls and burst-coalesce with a short TTL.
