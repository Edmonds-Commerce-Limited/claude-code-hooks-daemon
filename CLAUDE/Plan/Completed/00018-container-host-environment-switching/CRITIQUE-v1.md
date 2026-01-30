# Critique: Original Plan 00018 (socat + uv run)

**Date**: 2026-01-30
**Reviewer**: Claude Opus 4.5
**Original Plan**: See `PLAN-v1.md` and GitHub Issue #15

---

## Summary

The original plan proposes replacing ~140 lines of embedded Python in `init.sh` with `socat` for socket communication and `uv run` for daemon startup. The goal is to fix environment-switching failures (container vs host paths breaking the venv).

---

## What the Plan Gets Right

1. **The problem is real.** Hardcoded venv paths in `.pth` files and `PYTHON_CMD` pointing to `/workspace/untracked/venv/bin/python` will absolutely break when the same project is opened from a different path.

2. **Eliminating Python from the hot path is sound.** Every hook invocation currently spawns a Python process (~30ms). Replacing with something faster is a genuine improvement.

3. **Pure bash path computation is feasible.** The path scheme (`/tmp/claude-hooks-{name}-{hash}.sock`) can be replicated with `md5sum` and `basename` in bash. The Python `paths.py` module does nothing bash can't do.

4. **`uv run --project` does solve the portability problem.** It resolves dependencies at runtime relative to the project directory, bypassing stale `.pth` files entirely.

---

## Criticisms

### 1. socat is a new hard dependency with low default availability

`socat` is **not installed by default** on most Linux distributions (confirmed: not present in the project's own container). The issue handwaves this as "widely available" but:

- Fedora/RHEL: not in minimal installs
- Ubuntu/Debian: not in minimal installs
- macOS: requires `brew install socat`
- Alpine: requires `apk add socat`

**The current system has zero external dependencies beyond Python and jq.** Adding `socat` means every user must install an additional package. This is a regression in ease of deployment.

**Alternative**: Use **system Python** (`python3`) with a standalone inline socket script that has zero imports beyond stdlib (`socket`, `sys`, `json`). This eliminates the venv dependency from the hot path without adding a new binary dependency.

### 2. `uv run` is slow for daemon startup and has its own failure modes

`uv run --project` does dependency resolution on every invocation. While the plan says this "only happens once", daemon restarts after idle timeout (600s default) mean it happens regularly.

More critically, `uv run` introduces new failure modes:
- Network-dependent resolution on first run (or after cache eviction)
- `uv` version incompatibilities
- `uv` cache corruption
- `uv` not installed at runtime (confirmed: not installed in this container)

The plan trades one fragility (venv paths) for another (uv runtime resolution).

### 3. Pure bash JSON escaping is fragile

The proposed `emit_hook_error()` does manual JSON escaping:
```bash
error_details="${error_details//\\/\\\\}"
error_details="${error_details//\"/\\\"}"
```

This misses: newlines, tabs, control characters, Unicode sequences. The current Python-based approach handles all of these correctly via `json.dumps()`. Bash is not a JSON-safe language.

**Better**: Use `jq` (already a dependency) for JSON generation: `jq -n --arg event "$1" --arg type "$2" --arg details "$3" '{...}'`.

### 4. The plan removes granular error handling

The current Python socket client distinguishes 5 error types:
- `socket.timeout` — daemon hung
- `FileNotFoundError` — socket missing
- `ConnectionRefusedError` — daemon shutting down
- Generic exceptions — with type name
- subprocess failures — in error formatting

`socat` gives: it worked, or it didn't. You lose the ability to tell the agent *why* communication failed, which is critical for the self-healing design.

### 5. The "auto-restart on socket failure" pattern is risky

The proposed `send_request_stdin()` conflates "daemon not running" with "daemon crashed/hung". If the daemon is hung, this pattern will try to start a second instance, fail, and return a generic error. The current explicit `ensure_daemon()` before `send_request_stdin()` is cleaner — it separates liveness checking from communication.

### 6. md5sum output format differs across platforms

- Linux `md5sum`: outputs `hash  -`
- macOS `md5`: outputs `MD5 ("") = hash` (and `md5sum` may not exist)

The current Python `hashlib.md5` is cross-platform. The bash version needs platform detection.

---

## Risk Assessment

| Risk | Severity | Likelihood | Notes |
|------|----------|------------|-------|
| `socat` not installed on user systems | **High** | **High** | New dependency, not default on any major OS |
| `uv run` network dependency on first use | **Medium** | **Medium** | Cold cache requires internet access |
| `uv` not installed at runtime | **High** | **Medium** | Currently used only at install time |
| Loss of granular error diagnostics | **Medium** | **Certain** | `socat` doesn't distinguish error types |
| Bash JSON escaping bugs | **Medium** | **High** | Manual escaping always misses edge cases |
| md5sum cross-platform differences | **Low** | **Medium** | macOS vs Linux output format |
| Daemon auto-restart masking hung daemon | **Medium** | **Low** | Conflates "not running" with "broken" |
| Regression in self-install mode | **Medium** | **Medium** | `uv run --project` behaves differently for editable installs |

---

## Verdict

The plan correctly identifies the problem but proposes an **over-engineered solution** that introduces two new runtime dependencies (`socat`, `uv` at runtime), loses error granularity, and replaces working Python with fragile bash JSON handling. The simpler fix — use system `python3` instead of venv Python for the socket client — solves the core problem with minimal risk and zero new dependencies.

See `PLAN-v2.md` for the revised approach.
