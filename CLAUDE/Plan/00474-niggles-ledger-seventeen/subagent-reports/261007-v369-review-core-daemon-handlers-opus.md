# Release code review: v3.68.0..HEAD, core/ + daemon/ + handlers/ (excluding pre_tool_use)

Scope: `git diff v3.68.0..HEAD -- src/claude_code_hooks_daemon/core/ src/claude_code_hooks_daemon/daemon/ src/claude_code_hooks_daemon/handlers/ ':!src/claude_code_hooks_daemon/handlers/pre_tool_use/'`.
That is 46 files, +2171/-210 lines. Read-only review: no daemon restart, and no full suite.

Targeted tests (15 files, covering stand-in, autonomy gate and drivers, plan fact-check feed, limit re-brief, registry option validation/shadowing, daemon_sync_after_merge, quota recorder, work-queue rebrief/CLI, contract staleness, issue-validity CLI and release-slate): **309 passed**.

Probe scripts, kept as evidence:

- `/workspace/untracked/scratch/rev/probe_stand_in_option.py`
- `/workspace/untracked/scratch/rev/probe_effective_cwds.py`

## Verdict: BLOCKERS FOUND (1)

---

## BLOCKER

### B1. An invalid `stand_in_delay_hours` silently removes the whole Stop enforcer (Confidence 95%)

**Location:**

- `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py:653-667`. This is the `_stand_in_delay_hours` property setter, which raises `ValueError`.
- `src/claude_code_hooks_daemon/handlers/registry.py:350-366` (`_withhold_invalid_options`) and `:948-949` (the `except Exception` around instantiation).

**Problem:** The new option is validated by a property setter that raises. `register_all` applies options with `setattr` inside the per-handler instantiation `try`. A bad value (`24`, `0`, `"3"`, `true`) therefore makes the registry log `Failed to instantiate AutoContinueStopHandler` at WARNING and drop the handler entirely. That handler is the Stop-explanation enforcer and the writer of the awaiting-human marker. Nothing reaches `option_failures`, so the SessionStart config alert stays silent.

The same release added `validate_options` to the registry for exactly this failure mode, and its own docstring describes it ("a value that raised there would drop the WHOLE handler with only a warning"). `IdleHousekeepingAdvisoryHandler` and `github_issue_assignment_guard` implement it. `AutoContinueStopHandler` does not. Its setter's docstring says "a delay that cannot work must not be silent", but the outcome is silent and much worse: the stop enforcer is gone, not just the stand-in.

**Evidence** (`probe_stand_in_option.py`):

```
2   AutoContinueStopHandler registered: True  option_failures: {}
24  AutoContinueStopHandler registered: False option_failures: {}
'3' AutoContinueStopHandler registered: False option_failures: {}
WARNING ... Failed to instantiate AutoContinueStopHandler: stand_in_delay_hours must be a number above 0 and below 24 ...
```

The unit tests (`tests/unit/handlers/stop/test_auto_continue_stop_stand_in.py:160-168`) only exercise the setter directly. No test goes through `register_all`.

**Fix:** Add a `@staticmethod validate_options(options)` to `AutoContinueStopHandler`. It should return `{"stand_in_delay_hours": <message>}` when `validate_delay_hours` raises, mirroring `IdleHousekeepingAdvisoryHandler.validate_options`. Then add a registry-level test asserting that an invalid value keeps the handler registered on its 3 h default and records the problem in `option_failures`.

Optional hardening: in `register_all`, after `_withhold_invalid_options`, catch a setter `ValueError` per option rather than per handler. Any future raising setter without `validate_options` would then degrade the same way instead of unregistering a guard.

---

## NON-BLOCKING (each to be filed as a plan task)

### N1. Plan fact-check is delivered to whichever session or sub-agent fires the next PostToolUse, and can be delivered twice (Confidence 80%)

**Location:**

- `src/claude_code_hooks_daemon/handlers/post_tool_use/plan_fact_check_feed.py:97-124` (`matches` / `handle`)
- `src/claude_code_hooks_daemon/utils/plan_fact_check.py:349-376` (`deliver_pending`)

**Problem:**

1. `deliver_pending(state)` takes no session or agent identity. The pending record is repository-wide. The first PostToolUse from ANY session in the repo, including a sub-agent such as a Haiku Edit worker, receives the "dispatch plan-fact-checker" instruction and consumes it. That one call also records the content as checked and deletes the record. If the receiver cannot or does not dispatch the agent, the check is lost permanently.
2. `deliver_pending` is an unlocked read, write, clear sequence. Two concurrent PostToolUse events (parallel tool calls, served on the thread pool) can both list and read the same record before either `clear_pending`, so the instruction is delivered twice. `set_aside_pending` can also raise `FileNotFoundError` if a concurrent delivery unlinked the file first.

The handler is opt-in by default but is enabled (dogfooded) in this repository's `.claude/hooks-daemon.yaml:936`.

**Fix:** Deliver only on main-thread events: skip when the hook input carries an `agent_id`/subagent marker. Also make the take-a-record step atomic, by holding a module lock around list-read-clear or by `os.replace`-renaming the pending file to a claimed name before reading it. Add tests for a sub-agent event (not delivered, record kept) and for two concurrent deliveries (exactly one instruction).

### N2. `daemon_sync_after_merge._is_foreign_repo` uses `effective_cwds()[-1]`, which is not "where the merge ran" (Confidence 80%)

**Location:** `src/claude_code_hooks_daemon/handlers/post_tool_use/daemon_sync_after_merge.py:197-198`

**Problem:** `effective_cwds` (`utils/secret_file_matching.py:2456`) is an over-approximation built for the secret guard. It returns every directory deduplicated by FIRST occurrence (`dict.fromkeys`), and it includes `cd`s that come after the merge. Its last element is therefore neither the last `cd` nor the merge's directory. Probe output (`probe_effective_cwds.py`):

```
'cd /repo/wt && cd /repo && git merge feature': handler uses '/repo/wt'; merge ran in '/repo'
'git pull && cd /elsewhere':                     handler uses '/elsewhere'; merge ran in '/repo'
```

The result is a wrong foreign-repo verdict, which suppresses or misattributes the restart advisory. This handler is advisory only, hence non-blocking.

**Fix:** Compute the directory in effect at the merge/pull segment: walk the segments in order and stop at the first `git merge|pull|rebase` segment. Do not reuse the secret guard's set-valued helper. Add the two probe cases as tests.

### N3. `cmd_check_effective_handlers` lets a YAML parse error escape as exit 1, which upgrade.sh reads as "handlers change" (Confidence 75%)

**Location:**

- `src/claude_code_hooks_daemon/daemon/cli.py:4263-4297`
- `install/config_cli.py:_load_yaml` (`yaml.safe_load` is not wrapped)
- `scripts/upgrade.sh:1159-1172`

**Problem:** Only `(FileNotFoundError, ValueError)` are mapped to exit 2. `yaml.YAMLError` is not a `ValueError`, so a malformed config produces a traceback and Python exit 1. upgrade.sh treats `rc == 1` as "HANDLERS THAT CHANGE STATE WITH THIS UPGRADE" and prints the traceback under that heading. There is also no test of the CLI wrapper's 0/1/2 exit contract that upgrade.sh depends on. `tests/unit/install/test_effective_handlers.py` tests the library function only.

**Fix:** Catch `yaml.YAMLError` (in `_load_yaml`, converting it to `ValueError`, or in the command) and map it to 2. Add CLI tests for exit 0, 1 and 2.

### N4. The autonomy gate re-probes the container runtime on every event instead of using the startup-cached value (Confidence 70%)

**Location:**

- `src/claude_code_hooks_daemon/utils/autonomy.py:57-59, 119`
- Called from `core/chain.py:1123` for every `drives_autonomy` handler on every event, plus `auto_continue_stop`, `background_process_tracker` and `autonomy_notice`.

**Problem:** `current_environment()` calls `detect_container_runtime()`, which reads env, `/run/systemd/container`, marker files and `/proc/1/cgroup` every time. `ProjectContext.container_runtime()` already holds the value detected once at startup, and the status line uses that cached value ("never re-probed per render"). So the hot path does filesystem I/O per handler per event, and two sources of truth for the same fact can disagree.

**Fix:** Default `environment` in `autonomy_verdict` to `environment_label(ProjectContext.container_runtime())` when the context is initialised, and fall back to a live probe only without a context.

### N5. Magic string and duplicated pattern compilation in the CLI (Confidence 70%)

- `src/claude_code_hooks_daemon/daemon/cli.py:3925` compares `state.status != "completed"`, while `core/release_slate.py` already defines `_CI_COMPLETED`. Import or expose that constant.
- `src/claude_code_hooks_daemon/daemon/cli.py:7751-7756` (`_capture_value_swapper`) re-implements the sensitive-content public-pattern compilation (`re.compile(..., re.IGNORECASE)`). It also does `entry["name"]` / `entry.get` with no type check, so a non-dict entry or a bad regex raises an uncaught `TypeError`/`re.error` from the CLI. Reuse the handler's own compiled-pattern accessor so the swapper and the guard cannot drift, and turn a malformed entry into `_ContentGuardUnavailableError`.

### N6. A latent schema trap for a future PreModelSwitch wiring (Confidence 70%, suggestion)

`src/claude_code_hooks_daemon/core/response_schemas.py:451` makes the permissive auto-fill schema refuse any top-level `decision`. Today every wired event that legitimately uses top-level `decision` has a bespoke schema, so this is correct now. However, `PreModelSwitch` (`constants/events.py:528`, `wired=False`) is documented to accept `decision: "block"`. Flipping it to wired without a bespoke schema would silently reject its valid block. Add a test asserting that every wired event documented with top-level `decision` has a bespoke schema, or note it beside `PRE_MODEL_SWITCH`.

---

## Checked and found sound

- **Handler priorities:**
  - `quota_resume_recorder` 50, `limit_rebrief` 39, `autonomy_notice` 47 and `work_queue_rebrief` 48 are workflow handlers, all inside 36-55.
  - `host_command_guard` 10 and `root_recursion_guard` 13 are safety handlers, inside 10-20.
  - The constants match the init template.
- **`recovery_cron_advisor` (N23):** the per-call phase cache was removed from the singleton. This is correct; it was a real cross-thread race.
- **`server._probe_socket_liveness`:** an over-length AF_UNIX path is classified NOT_LIVE only when `errno is None` and an overflow is proven. EMFILE/EACCES stay INDETERMINATE, so it still fails safe.
- **`usage_snapshot`:** the temp file is now cleaned up on a failed write, and `unique_temp_path` cannot raise.
- **`_gh_ci_lookup`:** a newer failed matrix run is no longer hidden by an older green. Cancelled, skipped and tier-only runs never decide.
- **remote-docs:** a capture or refresh now refuses, instead of writing unscanned, when the content guard or fake-values registry is unavailable. This is a correct fail-closed change.
- **Autonomy inventory:** `test_autonomy_drivers.py` pins the exact set of `drives_autonomy` handlers, and guards are never gated.
- **`unsettable_option_reasons`:** this blocks options that would overwrite methods or underscore names. Slot descriptors and settable properties are correctly treated as settable.
- **Leftovers:** no TODO/FIXME/debug prints in the diff. The `nosec` removals are on lines that no longer need them (`usedforsecurity=False`, and logged handlers).
- **Tests:** every new module and handler has a matching test file. The gaps are the CLI wrapper for `check-effective-handlers` (N3) and the registry path for `stand_in_delay_hours` (B1).
