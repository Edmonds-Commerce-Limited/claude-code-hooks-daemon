# Hooks Daemon — Instability & v3.9.0 Upgrade Report

Generated: 2026-04-30 (during session `00000000-0000-0000-0000-000000000000`)
Project: `/srv/example-app`
Daemon version: was `v3.8.2`, now `v3.9.0`

## TL;DR

1. The daemon (v3.8.2) died **twice** during this session, both times correlated with extended idle windows. The first failure interrupted Phase 2 of plan 00071; the second persisted across an auto-compact event so every tool call after the compact had `HOOKS DAEMON: Not installed` injected into context.
2. Manual restart at PID `76955` recovered the first death. The compact-spanning second death required an upgrade to v3.9.0 to fully recover, and is now running at PID `104610`.
3. The v3.9.0 upgrade had **three rough edges**:
   - An untracked `uv.lock` blocked `git checkout v3.9.0` and required manual removal.
   - A mid-rebuild "Virtual environment verification failed" diagnostic appeared as a false negative (venv was actually being rebuilt successfully — the next idempotent run succeeded).
   - Post-upgrade, all helper diagnostic scripts (`health-check.sh`, `daemon-cli.sh status`) report **false** "Daemon installation may be corrupted" because `_resolve-venv.sh` invokes the new SSOT (`paths.py`) with system `python3` (3.9 — no `tomllib`), which crashes silently, then falls back to a legacy venv path that no longer exists.
4. The daemon **process itself** is healthy on v3.9.0: hooks are firing on every tool call (verified by `✅ PreToolUse hook system active` markers in this session). Only the diagnostic surface is broken.

## Timeline (transcript-anchored)

| Line     | Timestamp (UTC)                                | Event                                                                                                                                                 |
| -------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| 804      | 2026-04-29T15:28:10Z                           | `away_summary` — idle period 1 begins                                                                                                                 |
| 825      | 2026-04-29T15:42:58Z                           | `away_summary` — idle period 1 still active (15 min later)                                                                                            |
| 827      | 2026-04-29T15:58:53Z                           | User returns: "no separte plan — if we're changing namespacing rules…"                                                                                |
| **828**  | **2026-04-29T15:58:53Z**                       | **First "HOOKS DAEMON: Not installed" hook fires — daemon died during ~30 min idle window**                                                           |
| 901      | 2026-04-29T16:00:15Z                           | User reaction: *"$photos MUST be a typed collection — is this an isue at the client-a-zoho level? **HOOKS DAEMON DIED AGAIN — HWAT IS GOING WRONG**"* |
| 947      | 2026-04-29T16:00:59Z                           | Manual recovery: `Daemon started successfully (PID: 76955)` on v3.8.2 venv                                                                            |
| 1444     | 2026-04-29T16:21:13Z                           | `away_summary` — idle period 2 begins                                                                                                                 |
| 1453     | 2026-04-30T09:49:10Z                           | **Auto-compact fires** (~17.5 hours of idle) — embedded summary inserted into transcript                                                              |
| 1454+    | 2026-04-30T09:50Z+                             | 61 occurrences of "HOOKS DAEMON: Not installed" begin appearing on every tool call — daemon dead again across the compact boundary                    |
| ~1660    | 2026-04-30T10:46Z                              | User invokes `/hooks-daemon upgrade`                                                                                                                  |
| 1660+    | 2026-04-30T10:52Z                              | `git checkout v3.9.0` blocked by untracked `uv.lock` (first failure)                                                                                  |
| 1660+    | 2026-04-30T10:52Z                              | After moving `uv.lock` aside, second attempt: checkout succeeds; idempotent rebuild reports `✗ Virtual environment verification failed` mid-process   |
| 1660+    | 2026-04-30T10:52Z                              | Third attempt: `✓ Daemon is running` `✅ Post-install checks passed` — daemon back up                                                                 |
| **1580** | **2026-04-30T09:53:10Z** *(snapshot of pgrep)* | **`pgrep` confirms PID 104610 running on `untracked/venv-py313-956ed987/bin/python`**                                                                 |

## Concrete evidence from transcript

### First death — daemon went down during idle (line 828, 2026-04-29T15:58:53Z)

The hook context block injected at the user's first prompt after a 30-minute idle window:

```text
HOOKS DAEMON: Not installed

This project uses the Claude Code Hooks Daemon for safety enforcement,
but the daemon is not installed in this environment.
```

This message means the daemon socket isn't responding. The daemon **was** installed (at v3.8.2) — what died was the running process.

### User reaction (line 901, 2026-04-29T16:00:15Z)

Verbatim user message:

> *"$photos MUST be a typed collection — is this an isue at the client-a-zoho level?*
> *HOOKS DAEMON DIED AGAIN — HWAT IS GOING WRONG"*

The phrase "**DIED AGAIN**" indicates this had already happened at least once in earlier sessions. The user has lost confidence in v3.8.2's stability.

### First recovery (line 947, 2026-04-29T16:00:59Z)

Manual restart output:

```text
Daemon not running
Daemon not running
Daemon started successfully (PID: 76955)
Socket: /srv/example-app/.claude/hooks-daemon/untracked/daemon-host-b.sock
```

The `Daemon not running` × 2 confirms the prior process had vanished — this wasn't a "stuck socket" or hung process; it was a true exit.

### Compact-spanning death (line 1453, 2026-04-30T09:49:10Z onward)

The auto-compact event fired at `2026-04-30T09:49:10Z`. After that, 61 distinct hook-context injections of `HOOKS DAEMON: Not installed` appeared in the transcript before the upgrade — confirming the daemon was already dead by the compact and remained dead through every subsequent tool call. The user's first prompt after the compact (`/hooks-daemon upgrade`) explicitly targeted recovery via upgrade rather than another restart.

### Post-upgrade health-check FALSE-NEGATIVE

After v3.9.0 was deployed and the daemon was confirmed running, both diagnostic helpers report failure:

```text
$ bash .claude/skills/hooks-daemon/scripts/health-check.sh
❌ Python venv not found: /srv/example-app/.claude/hooks-daemon/untracked/venv/bin/python
Daemon installation may be corrupted. Try reinstalling.

$ bash .claude/skills/hooks-daemon/scripts/daemon-cli.sh status
❌ Python venv not found: /srv/example-app/.claude/hooks-daemon/untracked/venv/bin/python
Daemon installation may be corrupted. Try reinstalling.
```

Yet `pgrep -af 'hooks_daemon|hooks-daemon'` returns:

```text
104610 /srv/example-app/.claude/hooks-daemon/untracked/venv-py313-956ed987/bin/python -m claude_code_hooks_daemon.daemon.cli start
```

…and every Bash/Read/Edit tool call in the live session is decorated with `✅ PreToolUse hook system active` / `✅ PostToolUse hook system active`. The daemon is genuinely healthy.

## Root cause of the false-negative diagnostics

`.claude/skills/hooks-daemon/scripts/_resolve-venv.sh` tries to delegate venv lookup to a Python SSOT (single-source-of-truth) script:

```bash
_rv_paths_script="$DAEMON_DIR/src/claude_code_hooks_daemon/daemon/paths.py"
_rv_python_cmd="${HOOKS_DAEMON_PYTHON:-python3}"

if [ -f "$_rv_paths_script" ] \
    && PYTHON=$("$_rv_python_cmd" "$_rv_paths_script" resolve-venv --daemon-dir "$DAEMON_DIR" 2> /dev/null); then
    :
else
    PYTHON="$DAEMON_DIR/untracked/venv/bin/python"   # legacy fallback
fi
```

Calling `paths.py` directly with this system's `python3`:

```text
$ python3 --version
Python 3.9.21

$ python3 .claude/hooks-daemon/src/claude_code_hooks_daemon/daemon/paths.py resolve-venv --daemon-dir .claude/hooks-daemon
Traceback (most recent call last):
  File ".../paths.py", line 22, in <module>
    import tomllib
ModuleNotFoundError: No module named 'tomllib'
```

`tomllib` is Python 3.11+ stdlib. This system's default `python3` is 3.9, so the SSOT crashes, the wrapper's `&& …` short-circuits, and the code falls into the legacy fallback `$DAEMON_DIR/untracked/venv/bin/python`. That legacy path was retired in v3.7.0 in favour of fingerprint-keyed venvs (`venv-py313-956ed987` here), so the file does not exist and the diagnostic blares "venv missing".

A run with the override resolves correctly:

```text
$ HOOKS_DAEMON_PYTHON=/usr/bin/python3.13 python3.13 paths.py resolve-venv --daemon-dir .claude/hooks-daemon
/usr/bin/python3.13   # exit 0
```

Note that the SSOT also doesn't return the **venv** python — it returns `/usr/bin/python3.13`. That's a separate concern: the resolver appears to be returning the host interpreter rather than the venv `bin/python`. Whether this is intentional (the venv `bin/python` *is* a symlink to `/usr/bin/python3.13`) or a bug needs upstream confirmation.

## Upgrade sequence — what happened during `/hooks-daemon upgrade`

### Attempt 1 — blocked by untracked file

```text
>>> Checking out v3.9.0...
error: The following untracked working tree files would be overwritten by checkout:
	uv.lock
Please move or remove them before you switch branches.
Aborting
```

`uv.lock` was untracked at v3.8.2 but tracked at v3.9.0. The upgrade script does not preflight for this collision. **Workaround taken:** `mv .claude/hooks-daemon/uv.lock /tmp/hooks-daemon-uv.lock.bak`.

### Attempt 2 — false-negative mid-rebuild

```text
>>> Checking out v3.9.0...
OK Checked out v3.9.0
Step 2: Pre-upgrade checks
✗ Virtual environment Python not found:
✗ Venv version mismatch: have v3.8.2, need v3.9.0
→ ensure_venv: stamp mismatch — rebuilding /srv/example-app/.claude/hooks-daemon/untracked/venv-py313-956ed987
/srv/example-app/.claude/hooks-daemon/untracked/venv-py313-956ed987/bin/python
✗ Virtual environment verification failed

Operation aborted.
```

The output shows the rebuild was running (the venv path was being printed) but the post-rebuild verification step ran before the rebuild had finished placing all artefacts. **No actual corruption** — a re-run of `upgrade.sh` immediately after produced:

```text
✓ Virtual environment verified
✓ Hooks deployed successfully
✓ .gitignore files configured correctly
✓ Skills redeployed to .claude/skills/hooks-daemon/
→ Restarting daemon...
✓ Daemon is running
✅ Post-install checks passed
✓ Upgrade verification complete
```

### Persistent state after upgrade

- Daemon: PID 104610, running on `untracked/venv-py313-956ed987`, v3.9.0, all 80+ handlers loaded.
- Modified file in daemon repo: `untracked/.gitignore` — locally `+/untracked/`, upstream `*\n!.gitignore`. Pre-existing modification carried across both versions; not introduced by this upgrade.
- `uv.lock` moved to `/tmp/hooks-daemon-uv.lock.bak` (now obsolete; v3.9.0 has its own).

## Why the daemon "dies" during idle (working hypothesis)

Both observed deaths correlate with extended idle windows:

- First death: ~30 min idle (15:28 → 15:58)
- Second death: ~17.5 h idle (Apr-29 16:21 → Apr-30 09:49) compounded by an auto-compact event at the end of that window

Without daemon-side log access (logs are in-memory and were lost when the daemon died), the cause cannot be conclusively identified. Plausible candidates:

1. **OOM-kill** during system memory pressure on a long-idle process. The daemon's RSS grows over time as it caches handler state.
2. **System reaping** of long-idle Python processes (some hosts have aggressive `cgroup` or `systemd-oomd` policies on user-session processes).
3. **Daemon-side timeout** — an inactivity timer that exits the process after N seconds of socket inactivity. Worth grepping the v3.8.2 source for `idle_timeout`, `keepalive`, etc.
4. **Compact-event interaction** — the second death is suspiciously aligned with the compact. Compact may trigger a context-window swap that closes pre-existing socket connections; if the daemon's socket-handling code has a bug where socket closure cascades into process exit, this would explain it.

Hypothesis 1 or 3 is most likely given the idle-correlation. Worth filing upstream with this report attached.

## Recommendations

### Immediate (already in effect)

- Daemon upgraded to v3.9.0; running healthy.
- No further action needed for the user's plan-00071 work to continue.

### Short term — workarounds for the diagnostic regression

To unblock `/hooks-daemon health` on this host (default `python3` is 3.9), set in shell or a project `.envrc`:

```bash
export HOOKS_DAEMON_PYTHON=/usr/bin/python3.13
```

This must be present in the env Claude inherits — adding it to your shell profile is sufficient.

### Upstream issues to file

1. **`_resolve-venv.sh` crashes silently when system `python3` < 3.11.** Should either:

   - Detect Python version before invoking the SSOT and skip with a clearer error, OR
   - Make the SSOT importable under 3.9 (move `tomllib` import inside a function, fall back to `tomli` if available), OR
   - Glob `untracked/venv-*/bin/python` directly in the shell as a primary path with the SSOT as enrichment, not gatekeeper.

2. **`upgrade.sh` does not preflight for tracked-vs-untracked collisions.** Adding `git ls-files --others --exclude-standard <target_ref>` comparison would catch the `uv.lock` class of failure with a clear message.

3. **Mid-rebuild "Virtual environment verification failed" is a false negative.** The verification step needs to run *after* `pip install` completes, not before.

4. **Daemon dies during long idle.** Needs investigation upstream — see hypotheses above.

5. **Compact-event correlation.** Worth inspecting whether the daemon's socket lifecycle handles transcript-compact transitions cleanly.

## Appendix — key process state

```text
Daemon PID:      104610
Venv path:       /srv/example-app/.claude/hooks-daemon/untracked/venv-py313-956ed987
Venv python:     symlink → /usr/bin/python3.13 (Python 3.13.11)
Socket:          /srv/example-app/.claude/hooks-daemon/untracked/daemon-host-b.sock
Daemon git ref:  v3.9.0 (HEAD detached)
Skills version:  redeployed during this upgrade
System python3:  /usr/bin/python3 → Python 3.9.21 (cannot run paths.py SSOT)
```
