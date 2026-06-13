# Caching / Memoisation Infrastructure Review

**Purpose**: Recommend a standard pattern for caching daemon-lifetime-invariant facts
(e.g. "are we in a container") so the status line never recomputes them per render.

**Scope**: Investigation only — no source files were modified.

---

## 1. Status Event Dispatch Model & Render Frequency

### Bash entry → socket

- Claude Code invokes the status-line command, which runs
  `/workspace/.claude/hooks/status-line` (`status-line:9-32`).
- The script sources `init.sh`, calls `ensure_daemon` (lazy start), then pipes the
  event JSON through `send_request_stdin` and renders `.text`:
  ```bash
  jq -c '. + {hook_event_name: "Status"} | {event: "Status", hook_input: .}' \
    | send_request_stdin | jq -r '... .text ...'
  ```
- `send_request_stdin` (`init.sh:782+`) is a **stdlib-only `python3 -c` socket client** —
  it opens the daemon's Unix socket, writes the request, reads the response. It uses no
  venv packages so transport works even mid-upgrade. There is **one socket round-trip per
  status render**; no daemon spawn after warm-up.

### Socket → daemon → handlers (all in-process, per request)

- `HooksDaemonServer._process_request` (`daemon/server.py:554-638`) parses the request and,
  for normal events, dispatches via the controller inside a thread executor
  (`loop.run_in_executor(None, self.controller.process_request, request)` — line 622, new
  controller; or `self.controller.dispatch` — line 630, legacy).
- The new `Controller` owns an `EventRouter` (`daemon/controller.py:134`). The router holds
  **persistent `HandlerChain` instances keyed by `EventType`** (`core/router.py:39, 52`).
- Handlers are **discovered and registered exactly once** at `Controller.initialise()`
  (`daemon/controller.py:144-205`, `register_all` at line 195; `_router.register` at 314).
  Handler objects are long-lived singletons stored in `chain._handlers`.
- The legacy `FrontController.dispatch` (`core/front_controller.py:53-130`) iterates every
  registered handler, calling `handler.matches()` then `handler.handle()` in priority order.

### Does each render re-run all status handlers? — YES

Every Status render re-executes the **entire `Status` chain** in-process. Each status
handler's `matches()` returns `True` unconditionally (e.g. `git_repo_name.py:30-32`,
`daemon_stats.py:42-44`), so `handle()` runs on **every** render for all ~10 Status handlers
(see `.claude/HOOKS-DAEMON.md` → Status section: model_context, thinking_mode, current_time,
git_branch, git_repo_name, working_directory, startup_cleanup, daemon_stats, account_display,
usage_tracking). The handler instances persist, but their `handle()` bodies re-run from scratch.

### Render frequency

Claude Code invokes the statusline command **very frequently** — in practice on every prompt
submit and on UI refreshes/redraws (general Claude Code behaviour; the repo does not pin a
number). Treat it as "many times per minute during active use." Therefore any per-render work
inside a Status handler (env-var scans, filesystem `stat`s, subprocess calls) is on a hot path
and should be avoided for values that cannot change during the daemon's lifetime.

---

## 2. Inventory of Existing Caching Primitives

### (a) `ProjectContext` — startup-computed class-attribute singleton

File: `core/project_context.py`.

- A classmethod singleton: `_instance: ClassVar[_ProjectContextData | None]` and
  `_initialized: ClassVar[bool]` (`project_context.py:63-64`).
- `initialize(config_path)` runs **once** during daemon startup (`:66-166`), computes
  project_root, config paths, self_install_mode, git repo name (subprocess), git toplevel
  (subprocess), and the untracked dir, then freezes them into a `@dataclass(frozen=True)`
  `_ProjectContextData` (`:31-53`, stored at `:155-164`).
- Re-initialisation raises (`:80-84`) — FAIL FAST, computed exactly once.
- Accessors are classmethods that `_ensure_initialized()` then return the cached field, e.g.
  `git_repo_name()` (`:343-358`), `self_install_mode()` (`:329-341`), `project_root()`
  (`:287-299`). No recomputation on access.
- `reset()` (`:398-405`) exists **for tests only**.
- **This is the canonical existing pattern for daemon-lifetime-invariant facts.** It is
  already consumed on the Status hot path: `GitRepoNameHandler.handle()` calls
  `ProjectContext.git_repo_name()` (`git_repo_name.py:43`) instead of shelling out to git
  each render — exactly the optimisation we want to generalise.

### (b) `functools.lru_cache` / `cached_property`

**Not used anywhere in `src/`.** A repo-wide grep for `lru_cache`/`cached_property` returned
zero hits in source. The project has no precedent for decorator-based memoisation.

### (c) `stats_cache_reader.py` and other `*_cache*` modules — TTL/mtime-style external caches

These cache **mutable external state**, not lifetime-invariants, and deliberately re-read:

- `handlers/status_line/stats_cache_reader.py` — reads `~/.claude/stats-cache.json` every call
  (`read_stats_cache`, `:19-38`). No in-process memoisation; it parses fresh JSON each render
  and computes daily/weekly usage by current date (`:57`, `:99-100`). Invalidation is implicit:
  the file is rewritten by Claude Code and re-read each time; date arithmetic uses `now()`.
- `daemon_stats.py` reads a **version-check cache file** each render:
  `ProjectContext.daemon_untracked_dir() / "version_check_cache.json"` (`:104-124`). That JSON
  is produced by the `version_check` SessionStart handler; the reader file-exists-checks and
  json-parses it every render, with a staleness guard comparing `current_version` to the live
  `__version__` (`:113-118`). This is a **file-backed cache with content-based invalidation**,
  appropriate because the value (an available upgrade) can change while the daemon runs.
- `daemon_stats.py` also pulls live daemon metrics via `get_controller().get_stats()`
  (`daemon_stats.py:59`; stats counters in `controller.py:48-99`) and a block count from the
  data layer (`:96`). These are intentionally live, not cached.

**Takeaway**: existing `*_cache*` code caches things that *do* change (usage stats, available
upgrades) using file/TTL/date invalidation. None of it is the right model for a value that is
fixed for the daemon's whole life.

### Where the container fact is computed today (the hot-path problem)

`utils/container_detection.py`:

- `get_container_confidence_score()` (`:20-85`) reads ~8 env vars and does up to two filesystem
  `exists()` checks plus `os.getuid()` **on every call**.
- `is_container_environment()` (`:88-102`) calls the scorer each time — **no memoisation**.

Callers today are cold-path (daemon startup `init_config.py:19`, `enforcement.py:49`), so the
absence of caching has not mattered. The moment a **Status** handler calls
`is_container_environment()` per render, that env-scan + stat work runs on the hot path. This
is precisely the scenario the recommendation below must prevent.

---

## 3. Recommendation: memoising daemon-lifetime-invariants

A "container/environment" fact is fixed for the daemon process's entire lifetime — the env
vars and mount layout that `container_detection` inspects cannot change without restarting the
daemon. It should be computed **once** and read trivially thereafter.

### Options compared

| Option                                                      | Mechanism                                                                   | Pros                                                                                                                                                                                                                                                                   | Cons                                                                                                                                                                                                                                                                                                                                                                            |
| ----------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| (a) module-level `functools.lru_cache`                      | `@lru_cache(maxsize=1)` on `is_container_environment()`                     | One-line change; lazy                                                                                                                                                                                                                                                  | **Zero precedent in this codebase** (grep: 0 hits) — violates "consistent with existing patterns"; `lru_cache` on a no-arg fn is an idiom reviewers here won't recognise; cache lifetime is import-scoped, not "daemon-scoped", so tests that fork/re-init the daemon in one process see stale values with no `reset()` hook; the threshold parameter complicates the cache key |
| (b) `ProjectContext`-style startup-computed class attribute | Store the fact on a frozen startup singleton; accessor returns cached field | **Matches the dominant existing pattern** (`ProjectContext`); explicit `initialize()`/`reset()` lifecycle already understood; FAIL-FAST if accessed pre-init; trivially type-safe; the Status hot path already reads `ProjectContext` this way (`git_repo_name.py:43`) | Slightly more boilerplate than a decorator; must wire `initialize()` into daemon startup                                                                                                                                                                                                                                                                                        |
| (c) compute in daemon at startup, pass into handlers        | Controller computes the fact and injects it into each handler's constructor | Most explicit dependency flow                                                                                                                                                                                                                                          | Heaviest change: touches `register_all`/handler constructors/`Handler` ABC; breaks the uniform zero-arg handler construction; over-engineered (YAGNI) for a single boolean; no existing precedent                                                                                                                                                                               |

### Recommendation: (b) — a `ProjectContext`-style startup-computed cached attribute

**Compute the environment fact once at daemon startup and expose it as a cached
classmethod/attribute, mirroring `ProjectContext`.**

Two clean shapes, both consistent with the codebase:

1. **Add it to `ProjectContext`** — e.g. an `in_container: bool` field on `_ProjectContextData`
   computed during `initialize()` (right where `self_install_mode` and git facts already are,
   `project_context.py:105-164`), exposed via a new `ProjectContext.in_container()` accessor
   alongside `self_install_mode()`. This is the lowest-friction option: handlers already import
   `ProjectContext`, the freeze/reset/FAIL-FAST lifecycle is reused verbatim, and the Status
   handlers get the value with the same call shape they already use for repo name.
   *Caveat*: `container_detection` currently imports `ProjectContext` (`container_detection.py:12`)
   — to avoid a cycle, have `ProjectContext.initialize()` call the existing
   `is_container_environment()` (or its scorer) rather than the reverse.

2. **A dedicated `EnvironmentContext` singleton** in `utils/` (or `core/`) modelled exactly on
   `ProjectContext`: `_instance`/`_initialized` ClassVars, an `initialize()` that calls
   `is_container_environment()` once and freezes the result, an `in_container()` accessor, and a
   test-only `reset()`. Use this if you'd rather not widen `ProjectContext`'s responsibility
   (Single Responsibility) — it keeps "project facts" and "environment facts" separate while
   reusing the identical, already-blessed pattern.

**Rationale**

- **Consistency / least surprise**: `ProjectContext` is *the* established way this codebase
  caches "computed once at startup, never changes" facts. Reviewers, tests, and CLAUDE.md
  guidance all already describe it ("calculated once at daemon startup and cached for the
  session", `project_context.py:1-17`). `lru_cache` (option a) has no precedent and would be
  the only such usage in `src/`.
- **Correct cache lifetime + invalidation**: the value is keyed to the **daemon process
  lifetime**, which is exactly what an explicit `initialize()`-at-startup + `reset()`-in-tests
  lifecycle expresses. `lru_cache`'s lifetime is "module import," which diverges from daemon
  lifetime and has no clean test reset, risking cross-test bleed where the daemon is re-init'd
  in one interpreter.
- **Hot-path elimination**: after startup the Status render does a single attribute read — no
  env scan, no `stat`, no subprocess — matching how `GitRepoNameHandler` already avoids
  per-render git calls.
- **FAIL FAST + type safety**: the `_ensure_initialized()` guard surfaces ordering bugs
  immediately, and the frozen dataclass keeps the value immutable and fully typed.
- **YAGNI vs option (c)**: passing the value through handler constructors is more plumbing than
  a single boolean warrants and would disturb the uniform handler-registration path
  (`controller.py:195-314`).

**Not recommended**: option (a) `lru_cache` (no precedent, wrong-scoped lifetime, awkward test
reset) and option (c) constructor injection (over-engineered, disrupts handler construction).

---

## Appendix — key file:line references

- `/workspace/.claude/hooks/status-line:9-32` — bash entry, builds Status request, renders `.text`
- `/workspace/init.sh:782+` — `send_request_stdin` stdlib socket client (one round-trip/render)
- `daemon/server.py:554-638` — `_process_request`; dispatch via `run_in_executor` (lines 622/630)
- `daemon/controller.py:134,144-205,229,314` — EventRouter owned; handlers registered once at `initialise()`
- `core/router.py:39,52,54-61` — persistent `HandlerChain` per `EventType`
- `core/front_controller.py:53-130` — per-request iterate `matches()`/`handle()` over all handlers
- `core/project_context.py:31-53,63-64,66-166,287-358,398-405` — startup-computed frozen singleton (THE pattern)
- `handlers/status_line/git_repo_name.py:30-44` — Status handler reading cached `ProjectContext` (precedent)
- `handlers/status_line/daemon_stats.py:42-44,59,96,104-124` — always-matches; live stats + file-backed version cache
- `handlers/status_line/stats_cache_reader.py:19-38,57,99-100` — external file cache, re-read each render
- `utils/container_detection.py:20-102` — `get_container_confidence_score` / `is_container_environment`, **no memoisation**
- grep: **no `functools.lru_cache` or `cached_property` anywhere in `src/`**
