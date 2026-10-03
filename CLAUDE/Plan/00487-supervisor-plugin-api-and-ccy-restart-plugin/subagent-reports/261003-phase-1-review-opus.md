# Plan 00487 Phase 1 review (opus)

Scope: `git diff main...worktree-p487-supervisor-plugins`. The code under review is
`.claude/ccy/claude-supervise.py` (+1746 lines). I also read the new tests and the
CcySupervisor.md section. This was a read-only review.

## Verdict: CHANGES REQUIRED

## Version skew: clean (verified)

I ran a probe that loads `main`'s supervisor alongside this branch's. These four
checks all pass:

- An old host imports the new worker's `export_state` without error, because the
  new keys are ignored.
- An old host decodes the new `_outcome_to_json`.
- A new worker takes empty plugin flags from the argv an old host passes
  (`--worker --arm`).
- A new host decodes an old outcome. The plugin fields fall back to their defaults.

With no `--plugin` flag, the host builds no `PluginHost`, passes no `extra_argv`,
writes the status payload unchanged, and in `decide_once` only calls
`next_plugin_notice()` on an empty list. The supervisor therefore behaves exactly
as before. The one exception is that the worker's reply JSON now carries four extra
keys with default values, and old hosts ignore them.

Probe: `untracked/scratch/p487-probe/probe_skew.py` (main repo scratch).

## Defects

### 1. CRITICAL: plugin `print()` corrupts the worker protocol and can crash the PTY host

- **Location:** `claude-supervise.py:7654`, `7419`/`7500` and `7803`.
- **Cause:** a hook's stdout is the worker's reply pipe. `on_idle` doing `print(42)`
  puts `42\n` ahead of the JSON reply. `PolicyWorker.decide` passes that line to
  `_outcome_from_json`, which raises **TypeError**. `decide` only catches
  ValueError/KeyError. `on_poll()` (`8289`) has no guard around it, so the exception
  reaches `_forward_io` and the session dies.
- **Non-JSON prints:** these do not crash the host, but `decide` returns None on
  every tick. The plugin is never disabled, and the host stays on the in-process
  path (see defect 2), where the same `print` writes over Claude's TUI.
- **Fix, worker side:** keep the protocol on a private dup of fd 1, and point
  `sys.stdout` (and fd 1) at the error log before any plugin is loaded.
- **Fix, host side:** make `decide` treat any decode exception as None.
- **Test to add:** a plugin that prints, run through a real `PolicyWorker`.
- **Probe:** `untracked/scratch/p487-probe/probe_stdout.py` confirms the TypeError
  escapes.

### 2. IMPORTANT: the in-process fallback imports and runs plugins inside the PTY host

- **Location:** `8627` and `4395`.
- **Trigger:** one silent tick is enough, for example the hot-reload tick, a slow
  plugin load, or defect 1. After that, every plugin is imported into the host and
  stays there for the rest of the process.
- **What runs on the select loop:** the build happens synchronously inside
  `_on_poll`, at up to 1.5 s per plugin. After it, every in-process tick runs
  `run_idle` for up to 1 s.
- **Consequences:**
  - An overrun thread in the host leaks for the life of the session, because
    restarting the worker does not reach it.
  - A wedge that holds the GIL (for example a pathological `re`) freezes the PTY
    itself.
  - The worker's isolation is lost exactly when it is most needed.
- **Fix:** never run plugins in the host, and pass `plugins=None` in-process. If
  plugins must run in-process, only do it while `WorkerCrashGuard` has given up,
  never after a single timeout.

### 3. IMPORTANT: an abandoned exit-for-restart is re-requested with no cooldown

- **Location:** `8102` and `8515`.
- **Problem:** after a 30 s abandon, the plugin's next idle answer types `/exit`
  again, so `/exit` is typed and held every ~30 s indefinitely. Each hold also
  blocks compaction.
- **Fix:** add a per-process backoff or cap. For example, after N abandons, disable
  that plugin's exit requests and log it.
- **Test gap:** the existing test at `test_plugin_exit_for_restart.py:338` only
  checks that injections resume after an abandon.

### 4. MINOR: plugin-controlled `str()` runs outside the time budget

- **Location:** `4036`.
- **Problem:** `_clean_text(outcome.value.reason)` calls `str()` on a value the
  plugin chose. It runs on the worker main thread, or on the host thread when
  in-process. A `__str__` that raises or hangs escapes the budget. In-process, it
  escapes `on_poll`.
- **Fix:** coerce the reason inside the budgeted thread, or require
  `type(reason) is str` and treat anything else as a bad result.

### 5. MINOR: a non-OSError exception in the load path is not contained

- **Location:** `3983` and `8627`.
- **Problem:** `in_process_runtime()` -> `load()` only expects
  `PluginLoadError`/`OSError`. Anything else, such as `RuntimeError` from
  `Thread.start` or a non-str `version` from a property that changes between reads,
  propagates into `on_poll`.
- **Fix:** wrap the runtime build and hook dispatch in `except Exception`, and
  disable plugins wholesale when they fire.

## Checked and found sound

- **Notice text:** it is built only from a validated name and closed-set phrases,
  and unknown kinds and hooks are dropped on the host.
- **Loader vetting:** it uses `lstat` and refuses symlinks, checks owner and mode
  for the file and its parent, and never scans a directory. A TOCTOU window remains
  between the vet and `exec_module`, but that is out of scope under the threat
  model.
- **Session id:** an ambiguous id is refused.
- **Exit request file:** written via a tmp file and replace, with mode 0600.
- **Exit status 75:** documented at CcySupervisor.md:271-286.

## Test gaps

- A plugin that writes to stdout.
- An in-process overrun or wedge, which would leak a host thread.
- Repeated exit-for-restart requests after an abandon.
- An end-to-end hot reload with a slow plugin load longer than 2 s.
