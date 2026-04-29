# Report 3 — Detection & Self-Heal of Hook Exec-Bit Loss

## Summary

The exec-bit loss is silent until catastrophic: the first symptom is an unbounded retry loop of `Permission denied` Stop-hook errors. Plan 00091 already adds a `git_filemode_checker` SessionStart handler that warns about `core.fileMode=false` (the *cause*); this report proposes complementary detection-and-heal layers that catch the *effect* — a non-executable hook file — and remediate it. The chicken-and-egg problem (a SessionStart handler cannot run if its own wrapper is non-executable) is the dominant constraint and forces detection to live in **multiple, redundant layers**, not one place.

## Ideas

### 1. SessionStart handler `hook_exec_bit_self_healer` (auto-chmod + loud log)

- **Mechanism**: New handler in `src/claude_code_hooks_daemon/handlers/session_start/hook_exec_bit_self_healer.py`. Iterates `Path(project_root, ".claude/hooks").glob("*")`, filters regular files, and for any file missing `stat.S_IXUSR` calls `os.chmod(path, current_mode | 0o755)`. Emits a CONTEXT-injection warning listing every file repaired, with a pointer to Plan 00091's `core.fileMode=true` recommendation.
- **What it fixes**: chmod's the file AND warns. Self-heals silently per file, but loudly aggregates: one big warning so the user sees the pattern.
- **Pros**: Trivial — follows `optimal_config_checker.py` pattern exactly. Runs every new session. Logs make audit trail.
- **Cons**: Cannot run if the `session-start` wrapper itself is non-executable (chicken-and-egg). Resume-sessions are typically skipped (mirroring existing handlers), so a long-running session that loses bits mid-flight is uncovered.
- **Blast radius**: Daemon-side only.
- **Cost**: **S**.

### 2. Daemon-startup re-chmod assertion in `daemon/server.py`

- **Mechanism**: Before `socket.bind()` in `server.py` (near line 364 where `socket_path.chmod(0o660)` already runs), add `_assert_hook_exec_bits()` that walks the project's deployed hook wrappers (resolvable via the existing `ProjectContext` / `HOOKS_DAEMON_ROOT_DIR` env) and idempotently re-chmods them. Log at WARNING when a chmod was actually needed.
- **What it fixes**: chmod's. Fully idempotent.
- **Pros**: Fires on every daemon restart, including post-upgrade. Covers the case where SessionStart never reaches the handler because the wrapper is broken — the daemon itself owns the fix-up. Cross-cutting: catches **all** event types' wrappers in one pass.
- **Cons**: In multi-project setups the daemon only knows its own `PROJECT_DIR`. Other installs require their own daemon restart.
- **Blast radius**: Daemon-side only.
- **Cost**: **S–M** — one helper, hooked into the existing startup path that already chmod's the socket.

### 3. `hooks-daemon doctor` CLI subcommand

- **Mechanism**: New subcommand in `daemon/cli.py` (sibling to `status`, `restart`, `list-venvs`). Walks `.claude/hooks/*`, reports per file: present? executable? size? shebang valid? init.sh resolvable? Exit code 0=clean, 1=issues. `--fix` flag does the chmod. Wire into `scripts/debug_info.py` so bug reports auto-include the data.
- **What it fixes**: Reports by default; chmod's with `--fix`.
- **Pros**: User-runnable on demand and from CI. Pairs naturally with `daemon_restart_verifier`. Surfaces broader wrapper sanity, not just the bit.
- **Cons**: Manual — only helps users who know to run it. Not a defense, an audit.
- **Blast radius**: Daemon-side.
- **Cost**: **M**.

### 4. Status-line indicator `hook_health` (priority ~29)

- **Mechanism**: New status handler in `handlers/status/hook_health.py`. Each render, stat all `.claude/hooks/*` and emit a red glyph (e.g. `🔓 HOOKS-BROKEN`) if any is missing the bit. Cached per-second to avoid stat-storming.
- **What it fixes**: Surfaces only — status handlers must be side-effect-free. Pairs with #1.
- **Pros**: Always-on, persistent visual signal. Survives the chicken-and-egg because the statusline runs from the daemon socket, not from a hook wrapper.
- **Cons**: Still requires the daemon itself to be up (normally fine — only the wrapper-spawn path is broken).
- **Blast radius**: Daemon-side.
- **Cost**: **S**.

### 5. `init.sh` self-heal preamble (foothold via siblings)

- **Mechanism**: In `.claude/init.sh` (sourced by *every* hook wrapper), add a guarded block that runs `chmod u+x "$HOOKS_DIR"/*` for siblings missing the bit. Throttled by a fingerprint file (`.claude/hooks/.exec-bit-checked-$EPOCHHOUR`) so it runs at most once an hour.
- **What it fixes**: chmod's, by piggy-backing on whichever wrapper *does* still have its bit. PreToolUse fires constantly — if even one wrapper still works, all the others heal within seconds.
- **Pros**: Solves the chicken-and-egg as long as **any one** wrapper retains its bit — overwhelmingly the common failure mode (a single rebase touches one file, not all twelve).
- **Cons**: If **every** wrapper loses the bit simultaneously (mass `chmod -x`, IDE bug), nothing in `init.sh` ever runs. Adds latency to every hook invocation (mitigated by hourly throttle). Must be shellcheck-clean and pass the existing shell-script auditor.
- **Blast radius**: Per-client-repo (`.claude/init.sh` is deployed per project).
- **Cost**: **S** — ~10 lines of shell + tests.

### 6. Daemon-side anomaly detector for missing event types

- **Mechanism**: Server-side detector in `daemon/server.py`: if events of some types (e.g. PreToolUse) are arriving but Stop/SessionStart never do over an N-minute window, log CRITICAL and inject a CONTEXT message on the next successful UserPromptSubmit ("⚠️ Stop hook hasn't fired in 10 minutes — likely missing exec bit. Run `hooks-daemon doctor --fix`.").
- **What it fixes**: Detects from **inside the daemon** without needing the broken wrapper to run. Surfacing only — does not chmod.
- **Pros**: Catches the *partially-bricked* case where one event type's wrapper is dead and others still work. Pure observation channel; no foothold required.
- **Cons**: Heuristic — some hook types legitimately fire rarely. Needs per-event-type expected-interval baselines.
- **Blast radius**: Daemon-side.
- **Cost**: **M–L**.

## Top Pick

**Stack ideas #1 + #2 + #5 as a defense-in-depth bundle.**

- **#2 (daemon-startup chmod)** is the cheapest highest-leverage layer — every daemon restart asserts the bits. Catches the post-upgrade case.
- **#5 (`init.sh` self-heal)** handles steady-state — as long as one wrapper still works, siblings auto-recover within a single hook fire (typically \<1s in active sessions). This is the chicken-and-egg breaker.
- **#1 (SessionStart self-healer)** is the user-visible warning surface — the loudly-logged "this happened, here's why" message that drives users to fix `core.fileMode` upstream (closing the loop with Plan 00091).

Add **#3 (`doctor` CLI)** as the manual escape hatch and bug-report enrichment. **#4** and **#6** are lower-ROI follow-ups. Together #1+#2+#5 close the chicken-and-egg gap for every realistic failure mode short of "every wrapper bricked simultaneously" — and in that case no in-process detection can possibly help; the daemon-restart path (#2) is the only recovery anyway.
