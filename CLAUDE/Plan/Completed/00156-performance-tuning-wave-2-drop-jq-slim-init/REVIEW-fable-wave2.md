# Wave 2 Code Review (Fable) — Plan 00156

> Independent code review of the Wave 2 changes (drop `jq` from the hook
> transport + slim `init.sh`) performed by a Fable-model `code-reviewer` agent
> against `feature/performance-tuning` (10 commits ahead of `main`). Captured
> verbatim below. The follow-up fix commits that resolve findings 1–7 are
> recorded in this plan's `PLAN.md` Notes & Updates.

---

# Code Review: Wave 2 Performance Tuning (`feature/performance-tuning`, Plan 00156)

## Verdict

**APPROVE WITH NITS** — the safety-critical transport rewrite is correct on every high-stakes axis (payload fidelity, Stop contract, injection surface, bash-3.2 portability), and I verified the important claims empirically rather than trusting the diff. The findings below are real but none is a safety regression on the hot path. Findings 1–3 are worth fixing before merge; none blocks.

Reviewed: `init.sh` (T2+T3), `install.py`, 9 regenerated `.claude/hooks/*` wrappers, both new test suites (43 tests, all pass locally including the dogfooding byte-parity test), plus a skim of the Wave 1 commits.

## Findings

### 1. MINOR — Misleading error payload for `invalid_hook_input` (Confidence: 95%)

**Location:** `/workspace/init.sh:817-832` (`context_lines` in `emit_error_json`) reached via `fail('invalid_hook_input', ...)` at `init.sh:882`

**Failure scenario (empirically verified):** `printf 'not json {' | .claude/hooks/pre-tool-use` (with a live daemon PID) produces:

```
"additionalContext": "HOOKS DAEMON: Not currently running\n\nError: invalid_hook_input - ...\n...restart the daemon..."
```

The daemon IS running — the payload was malformed. The parse failure never touches the socket, yet the agent is told the daemon is down and instructed to restart it, which will "fix" nothing and burn a restart cycle. The `context_lines` template is hardcoded for the daemon-down scenario; `invalid_hook_input` is the first caller for which that framing is false.

**Also note the exit-code semantics changed here** — and this is the ONE transport behaviour that is not parity, contradicting the plan's "error contract byte-for-byte" claim. I verified the old path: `jq -c '{event...}'` on malformed stdin exits **4** under `set -euo pipefail`, so the old wrapper exited 4 (Claude Code: non-blocking error, stderr shown, operation proceeds). The new path exits **0** with structured context. Both fail open, so this is NOT a block→allow regression — but it is an undocumented, untested behaviour change on the safety transport (see Finding 5).

**Fix:** add a distinct context template for `invalid_hook_input` ("hook payload was not valid JSON — daemon state unknown/likely fine; do NOT restart") or pass a flag into `emit_error_json`. Document the exit-4→exit-0 change in the plan/commit.

### 2. MINOR — CI-passthrough override ignores status mode; status line renders a raw JSON blob (Confidence: 85%)

**Location:** `/workspace/init.sh:753-759` (CI-passthrough `send_request_stdin` override) vs `.claude/hooks/status-line:25` (`send_request_stdin "Status" "status"`)

**Failure scenario:** CI environment, daemon not installed, passthrough mode active, status line invoked. The override takes `$1` only and unconditionally prints the `hookSpecificOutput` JSON. Old path post-processed through `jq -r 'if .error ... else "⚠️ NO STATUS DATA"'`, so the status line showed `⚠️ NO STATUS DATA`; new path has no post-processing (status extraction lives only in the main definition), so the status line displays the full one-line JSON advisory blob. A parity regression, low blast radius (status line in a daemonless CI container).

**Fix:** in the override, `[[ "${2:-}" == "status" ]] && { cat > /dev/null; echo "⚠️ NO STATUS DATA"; return 0; }`.

### 3. MINOR — Status-mode transport failure silently drops the stderr diagnostic (Confidence: 80%)

**Location:** `/workspace/init.sh:856-857` (`fail()` status branch)

The old status path still ran `emit_error_json`, which printed `HOOKS DAEMON ERROR [socket_timeout]: ...` to stderr before the `jq -r` fallback rendered `⚠️ NO STATUS DATA`. The new `fail()` skips `emit_error_json` entirely for status mode, so a mid-render socket failure leaves no diagnostic anywhere — the only symptom is the fallback text. Given this project's "no silent error suppression" standard, keep the stderr line:

```python
print(f'HOOKS DAEMON ERROR [{error_type}]: {error_details}', file=sys.stderr)
print('⚠️ NO STATUS DATA')
```

### 4. MINOR — `test_untracked_dir_exists_after_source` does not test what its docstring claims (Confidence: 90%)

**Location:** `/workspace/tests/integration/test_init_hot_path.py:86-99`

The docstring says the test "proves the guard still guarantees the directory is present" — but the repo's untracked dir always exists, so only the dir-already-exists branch is ever exercised. Replace the guard with `[[ -d "$_untracked_dir" ]] || true` and this test still passes. The T3 change's actual risk (breaking creation-when-absent) is unpinned. Fix: source a copy of init.sh with `HOOKS_DAEMON_ROOT_DIR` pointing at a tmp dir that lacks `untracked/` (bypass the `.env` pin, e.g. by exporting after a stub env file), and assert the dir gets created.

### 5. MINOR — No test for the malformed-payload path, the one behaviour that changed (Confidence: 85%)

**Location:** `/workspace/tests/integration/test_forwarder_jq_free.py` (absent case)

The suite pins envelope shape, control-char fidelity, Status injection, and the Stop exit-2 contract — genuinely, not theatrically (I checked: the broken-jq shim exits 127 under `set -euo pipefail`, so any residual jq call would fail the run). But the newly added explicit `json.loads` failure branch (`fail('invalid_hook_input', ...)`) has zero coverage, and it is the only branch whose behaviour diverges from the jq path (Finding 1). Add: malformed stdin → PreToolUse wrapper exits 0 with `invalid_hook_input` context; malformed stdin → stop wrapper exits **2** (I confirmed by reading that Stop correctly fails closed here via `emit_error_json`'s `decision: block` — worth pinning, it's a load-bearing safety property).

### 6. NIT — Tautological test (Confidence: 95%)

**Location:** `/workspace/tests/integration/test_forwarder_jq_free.py:380-383`

`test_precondition_jq_is_installed` skips when jq is absent and asserts `which("jq") is not None` when present — the assertion can never fail. As a visibility marker for the `with-jq` parametrisations it's defensible, but as written it's an assertion that tests nothing. A comment-only skip marker or a module-level `pytest.mark` note would be honest.

### 7. NIT — Stale documentation contradicting the code (Confidence: 100%)

- `/workspace/init.sh:953`: `forward_stop_event` header still says "Pipe stdin JSON → jq wrap → send_request_stdin" — the jq wrap is gone.
- `/workspace/init.sh:105`: "using jq (already a dependency)" — jq is now used only in `emit_hook_error`; "already a dependency" no longer describes the hot path. Also note the jq-less fallback at `init.sh:142-146` interpolates `$error_details` into JSON unescaped and is fail-open even for Stop/CI-enforced — pre-existing, but jq's demotion from hot-path dependency makes jq-less hosts more plausible; worth a follow-up ticket, not a Wave 2 blocker.
- `/workspace/tests/integration/test_init_hot_path.py:69`: `env.pop("HOSTNAME", None)` is dead — the dict comprehension on line 68 already removed it.
- `/workspace/init.sh:799-800` + python lines 806-807: event name/response mode are defaulted twice (bash `${1:-Unknown}` and python `len(sys.argv)` guard). Harmless belt-and-braces, but one of the two is dead logic.

## What's solid (actually checked, not assumed)

- **Payload fidelity**: hook_input stays on stdin end-to-end; `json.loads` → `json.dumps` re-serialisation is semantically lossless (jq re-serialised too, so this is parity). The whitespace/`ensure_ascii` byte differences vs `jq -c` are irrelevant — the daemon parses JSON. Control-char round-trip is pinned by a real test driving the deployed wrapper against a recording socket.
- **No injection surface**: `event_name`/`response_mode` originate from the hardcoded `daemon_hooks` dict in `install.py:520-531`, travel bash-arg → python `argv` → `json.dumps` escaping. Nothing is shell-interpolated into the python source except the pre-existing (unchanged) `$SOCKET_PATH` single-quote interpolation. No eval, no printf-into-code.
- **Stop contract**: `decision=block` → exit 2 + reason on stderr is pinned by tests for both wrappers, with and without jq; unparseable daemon response → allow matches the old `jq -r '.decision // ""'` exactly; transport failure on Stop fails closed via `emit_error_json`'s block payload — correct and preserved.
- **bash-3.2 portability**: `${var// /-}` (bash 2.0+), `<<<` herestrings (2.05b+), `[[ -d ]]` — all safe; lowercase correctly left on `tr` (no `${var,,}`). Sanitisation output parity with `daemon/paths.py:107` (`.lower().replace(" ", "-")`) holds; the operation-order swap is commutative. The `[[ -d ]] || mkdir -p` guard is TOCTOU-benign (`-p` is idempotent).
- **Deployed/installer sync**: `test_dogfooding_hook_scripts.py` passes; spot-checked `pre-tool-use` and `status-line` against the `install.py` templates — identical.
- **jq-free assertion is genuine**: the broken-jq PATH shim would hard-fail any wrapper that still invoked jq; the source-scan test's comment-stripping is a reasonable second tripwire (gameable via `$(jq ...)`, but the shim test covers execution).
- **Wave 1 skim**: the `is_hooks_daemon_repo` memoisation and git-branch render TTL cache are clean (unbounded dicts keyed by directory/cwd — bounded in practice); removing the `[project.scripts]` entry pointing at the deleted `hooks.pre_tool_use` package was correctly caught.
