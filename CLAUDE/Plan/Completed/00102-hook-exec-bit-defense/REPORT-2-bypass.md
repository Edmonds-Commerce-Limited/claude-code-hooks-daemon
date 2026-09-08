# Report 2 — Bypass: make the exec bit irrelevant

## Summary

The hook wrappers in `/workspace/.claude/hooks/{event}` are 24-line bash scripts that just `source ../init.sh` and pipe stdin into `send_request_stdin`. Today `/workspace/install.py` (lines 525–565) and `/workspace/.claude/settings.json` invoke them as bare absolute paths (`"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop`), which forces the kernel to honour the exec bit. Every idea below changes how `settings.json` launches the wrapper so the file is *read*, not *executed* — making `chmod -x`, `core.fileMode=false`, network-FS exec stripping, and IDE-save mode loss into non-events. The `hook_registration_checker` SessionStart handler at `/workspace/src/claude_code_hooks_daemon/handlers/session_start/hook_registration_checker.py` already audits every `command:` field on every new session — that's the natural seam for auto-migrating client repos in place.

## Ideas

### 1. `bash <abs-path>` (the seed idea)

- **Mechanism**: change `install.py` ~lines 528–565 and `.claude/settings.json` so each entry becomes `"command": "bash \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop"` (etc.). The `#!/bin/bash` shebang inside the wrapper is now decorative — bash reads the file as data.
- **Pros**: one-line installer change. Wrapper code unchanged. Survives any filesystem that loses exec bit. Bash is on PATH on every box that runs Claude Code today (the daemon already requires bash for `init.sh`).
- **Cons**:
  - Windows: Claude Code on native Windows uses `cmd`/PowerShell, but the *current* design already invokes a bash wrapper as a bare command, so this is no worse. Git Bash / WSL users keep working unchanged.
  - If a user has `bash` aliased to something exotic, behaviour shifts — vanishingly rare.
  - `set -euo pipefail` still works (interpreter reads it).
- **Blast radius**: existing client repos need their `settings.json` rewritten. The SessionStart `hook_registration_checker` handler can detect the legacy form and rewrite in place + back up to `settings.json.bak` — zero user action.
- **Cost**: **S**.

### 2. `sh <abs-path>` (POSIX portable)

- **Mechanism**: `"command": "sh \"$CLAUDE_PROJECT_DIR\"/.claude/hooks/stop"`.
- **Pros**: `sh` is even more universally on PATH than bash; no PATH surprises.
- **Cons**: the wrappers use bash-isms (`[[ ]]`, `BASH_SOURCE`, `pipefail`, `source`). `sh` on Debian = `dash`, which would crash. We'd have to rewrite wrappers as POSIX shell (loses readability and `init.sh` is 800+ lines of bash) or break `sh` users.
- **Blast radius**: same as #1 plus a full wrapper rewrite.
- **Cost**: **L** (rewrite + reverify every wrapper and `init.sh`).

### 3. `python -m claude_code_hooks_daemon.hooks.<event>` — skip the shell

- **Mechanism**: `"command": "$HOOKS_DAEMON_VENV/bin/python -m claude_code_hooks_daemon.hooks.stop"`. Move bash wrapper logic (daemon-startup, socket fallback, CI passthrough, error JSON) into a Python module per event.
- **Pros**: no shell needed, works identically on Windows. Removes ~800 lines of bash. Python module is read by interpreter — exec bit irrelevant. Better testability.
- **Cons**: hot path now pays Python-startup cost (~30–80ms) on *every* hook event, not just cold start. The whole point of the bash hot path was to avoid that — major regression in the project's headline 20× perf claim. Venv resolution on the hot path requires Python to run, chicken/egg with the fingerprint helper.
- **Blast radius**: large rewrite; settings.json migration.
- **Cost**: **L**.

### 4. Single launcher binary on PATH (`claude-hook <event>`)

- **Mechanism**: ship a tiny statically-linked launcher (Go/Rust) installed to `~/.local/bin/claude-hook`. `settings.json` becomes `"command": "claude-hook stop"`. The launcher walks up to find `.claude/`, talks to the socket directly.
- **Pros**: lives outside the project, never loses exec bit per-repo. One binary protects every repo. Clean cross-platform story.
- **Cons**: requires per-user install step. New build toolchain. Doesn't help users who haven't installed it. Distribution problem (PyPI? Homebrew? `curl|sh` — blocked by our own `curl_pipe_shell` handler).
- **Blast radius**: clients need a new install step; settings.json migrated.
- **Cost**: **L**.

### 5. Inline the hook command in `settings.json` (no wrapper file)

- **Mechanism**: `"command": "bash -c 'source \"$CLAUDE_PROJECT_DIR\"/.claude/init.sh && ensure_daemon && jq -c '\"'\"'{event:\"Stop\",hook_input:.}'\"'\"' | send_request_stdin'"`.
- **Pros**: zero wrapper files on disk → zero exec-bit surface.
- **Cons**: `settings.json` becomes a nightmare of nested quoting per event. Every wrapper logic change forces a settings.json migration on every client. JSON-in-shell quoting bugs become silent runtime failures. Loses wrappers as an inspection target.
- **Blast radius**: every wrapper edit is now a settings-json migration.
- **Cost**: **M** with permanent maintenance tax.

### 6. Auto-migrate `settings.json` on every SessionStart

- **Mechanism**: extend `hook_registration_checker.py` (priority 51, already reads both settings files on session start) to also *rewrite* legacy bare-path commands to the new `bash <path>` form, with a one-shot backup and an `additionalContext` message describing the change.
- **Pros**: turns idea #1 into a zero-touch upgrade for every client repo. Self-healing.
- **Cons**: writing to `settings.json` from a handler is a privilege/policy escalation — needs explicit opt-out (`auto_migrate_settings: false` config flag). Risk of clobbering hand-edited entries; mitigated by only rewriting `command:` strings that match the daemon's known wrapper-path regex (`.*\.claude/hooks/{event-name}$`).
- **Blast radius**: all existing client repos auto-upgrade on next session.
- **Cost**: **S** when paired with #1.

## Top pick

**#1 (`bash <abs-path>`) + #6 (SessionStart auto-migration).**

Rationale: smallest possible change that completely eliminates the failure mode, with built-in zero-touch rollout for the install base. The wrapper files keep their `#!/bin/bash` shebang as documentation, but the kernel never needs to honour it. Implementation is a ~5-line edit to the dict literal at `/workspace/install.py` lines 528–565, a matching change to `/workspace/.claude/settings.json`, and ~30 lines added to `/workspace/src/claude_code_hooks_daemon/handlers/session_start/hook_registration_checker.py` to detect the legacy bare-path form, back up to `settings.json.bak`, and rewrite. Windows behaviour is unchanged (Claude Code already shells out to a bash wrapper via Git Bash/WSL there — replacing the direct invocation with `bash <path>` is strictly more permissive, not less). The hot-path performance story is preserved because we keep the bash wrapper — we just stop demanding `+x` on it. Pairing with idea #6 means existing client repos heal themselves on first session after upgrade with zero user action.
