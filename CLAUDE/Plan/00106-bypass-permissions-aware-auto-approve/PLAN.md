# Plan 00106: Bypass-Permissions-Aware Auto-Approve

**Status**: Not Started (QUEUED behind Plan 00105)
**Created**: 2026-05-08
**Owner**: Claude
**Priority**: High (security)
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

> **Queued behind Plan 00105**: v3.11.0 stability hardening is currently
> in-flight on the main thread. Do NOT begin execution of this plan until
> 00105 ships and is moved to `Completed/`. This plan is research + planning
> only at this point.

## Overview

The hooks daemon currently ships `auto_approve_reads` (PermissionRequest,
priority 10, TERMINAL) which approves every Read/Glob/Grep permission request
regardless of which Claude Code permission mode the user is running in. In
`bypassPermissions` (YOLO / `--dangerously-skip-permissions`) mode that is
intentional and helpful — the user has opted out of the per-tool approval
flow. In `default` mode, however, the user has NOT opted out: they want the
per-tool approval prompts. Auto-approving on their behalf in that environment
silently converts a non-YOLO session into YOLO behaviour without consent.

This plan gates auto-approve on `hook_input["permission_mode"]` so the daemon
only approves when Claude Code itself reports the session is already in a
bypass-permissions mode. Otherwise the daemon defers (returns no decision)
and lets Claude Code's normal approval flow run.

## Context & Background

**User concern (verbatim):**

> This daemon ships handlers that auto-approve things — for example
> `auto_approve_reads` (priority 10, TERMINAL, in PermissionRequest)
> auto-approves read-only tool permission requests. That is fine and
> intentional **in YOLO / `--dangerously-skip-permissions` mode**, where the
> user has explicitly opted out of the normal approval flow.
>
> But when the user is running Claude Code in NORMAL mode (no
> `--dangerously-skip-permissions`), they actively want the per-tool approval
> prompts. If the hooks daemon is auto-approving things in that environment,
> it is *silently turning a non-YOLO session into YOLO behaviour without
> consent*. That is dangerous.
>
> The user's question: **can the hooks daemon detect whether Claude Code is
> currently running in bypass-permissions / YOLO mode, and only auto-approve
> when it is? Otherwise, the daemon should defer to Claude Code's normal
> approval flow.**

The answer is yes — see Research Findings below.

## Goals

- `auto_approve_reads` only returns `Decision.ALLOW` when
  `permission_mode == "bypassPermissions"`. In every other mode it returns
  no decision (defers to Claude Code's normal approval flow).
- Mode-gating logic is shared and reusable: extract a small utility
  (`utils/permission_mode.py`) so any future auto-approving handler can
  call `is_bypass_mode(hook_input)` rather than hand-rolling the check.
- Existing test suite for `auto_approve_reads` still passes after being
  updated for the new gating contract; new tests prove that `default`,
  `plan`, `acceptEdits`, and `dontAsk` modes are NOT auto-approved.
- Daemon restart verification — handler loads, `status: RUNNING`.
- `get_claude_md()` returns guidance documenting the new gating behaviour
  (currently it returns `None`).

## Non-Goals

- Fixing Claude Code's YOLO mode behaviour itself (upstream).
- Changing `yolo_container_detection` — that is a separate orthogonal
  signal (container vs bare-metal) and a user can run YOLO outside a
  container or `default` mode inside one.
- Adding new auto-approving handlers. This plan only retrofits the one
  that exists today.
- Changing the hook input schema — `permission_mode` is already a
  documented common base field across every event.

## Research Findings

### 1. Claude Code permission modes (confirmed)

From `/workspace/CLAUDE/Code/HooksSystem.md:222` (the daemon's own
documentation of the Claude Code hook contract):

> `permission_mode` | string | Current mode: `"default"`, `"plan"`,
> `"acceptEdits"`, `"dontAsk"`, `"bypassPermissions"`

Five values total. `bypassPermissions` is the YOLO /
`--dangerously-skip-permissions` mode. The other four are interactive in
the sense that the user expects per-tool prompting (or, for `plan`,
explicit non-execution).

### 2. How a hook can know which mode the user is in

**Claude Code exposes the mode directly in every hook input.** Evidence:

| Source                                                                                  | Line        | Finding                                                                                                                                                              |
| --------------------------------------------------------------------------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/claude_code_hooks_daemon/core/input_schemas.py`                                    | 24-30       | `_BASE_PROPERTIES` includes `"permission_mode": {"type": "string"}` — present on EVERY event schema (PreToolUse, PostToolUse, PermissionRequest, SessionStart, etc.) |
| `src/claude_code_hooks_daemon/constants/protocol.py`                                    | 48          | `HookInputField.PERMISSION_MODE = "permission_mode"` — already a first-class constant                                                                                |
| `CLAUDE/Code/HooksSystem.md`                                                            | 212, 222    | Documents `permission_mode` as a common field on every event with the five-value enum                                                                                |
| `tests/unit/core/test_input_schemas.py`                                                 | 65          | Real test fixture confirms `"permission_mode": "default"` shape                                                                                                      |
| `CLAUDE/Plan/Completed/001-test-fixture-validation/POSTTOOLUSE_FIXTURE_VERIFICATION.md` | 24          | Captured real event fixture: `"permission_mode": "acceptEdits"`                                                                                                      |
| `CLAUDE/Plan/00032-.../RESEARCH-2026-02-23.md`                                          | 96-100, 148 | Prior daemon research already confirmed the field exists and lists all five values                                                                                   |

**Conclusion**: We do NOT need environment variables, container heuristics,
or settings.json introspection. `hook_input["permission_mode"]` is the
authoritative signal Claude Code itself supplies.

### 3. Auto-approving handlers currently shipping

Searched `src/claude_code_hooks_daemon/handlers/` for handlers that return
`Decision.ALLOW` in PermissionRequest event handling. Result: **exactly
one** — `auto_approve_reads`.

| Handler              | Event             | Priority | Terminal | Approves         |
| -------------------- | ----------------- | -------- | -------- | ---------------- |
| `auto_approve_reads` | PermissionRequest | 10       | TERMINAL | Read, Glob, Grep |

Other PermissionRequest handlers (`hello_world`) do not approve. The
`Decision.ALLOW` returns scattered through other event handlers
(SessionStart, PreToolUse, etc.) are not "auto-approving permission
requests" — they're context-injection for non-PermissionRequest events.
The blast radius for this plan is therefore narrow: one handler, one test
file.

### 4. YOLO container detection vs bypass-permissions mode

`session_start/yolo_container_detection.py` uses container signals
(`CLAUDECODE=1`, `DEVCONTAINER=true`, `container=podman|docker`,
`/workspace` + `.claude/` present, `os.getuid() == 0`). This detects
**container environment**, not **permission mode**:

- A user can run `claude --dangerously-skip-permissions` on bare metal —
  `bypassPermissions` mode, no container signals.
- A user can run normal Claude Code inside a Podman container —
  container signals fire, but `permission_mode == "default"`.

These two signals are orthogonal. Container detection is therefore
**not safe** to gate auto-approve on; `permission_mode` is.

### 5. Prior plan history

`CLAUDE/Plan/00089-fix-auto-approve-reads-and-askuserquestion-bypass/` (In
Progress per `README.md`) addressed a different bug in `auto_approve_reads`
(schema mismatch on `permission_type` vs `permission_suggestions`) and
landed a fix that uses `tool_name` to detect read-only tools. It did NOT
add permission-mode gating. The current handler still approves in every
mode. This plan completes the security hardening that 00089 left open.

## Decision

**A — Claude Code exposes mode to hooks via `hook_input["permission_mode"]`.
Gate `auto_approve_reads` (and any future auto-approve handler) on
`permission_mode == "bypassPermissions"`. In any other mode the handler
returns no decision and defers to Claude Code's normal approval flow.**

**Rationale**: The signal is authoritative (Claude Code itself reports
it), already plumbed through the daemon (constants + schemas exist),
already proven by captured real-event fixtures, and orthogonal to the
container-detection signal which would be unsafe to overload. No new
infrastructure is required — only handler logic changes plus a small
shared helper.

### Decision details

- **Default**: gate on `permission_mode == "bypassPermissions"`. In any
  other mode (including missing/empty), defer.
- **Defer mechanism**: handler's `matches()` returns `False` when not in
  bypass mode, so the dispatch chain skips it entirely and Claude Code's
  normal approval flow handles the request. This is preferable to
  returning `Decision.ALLOW` with conditions or `Decision.DENY` (which
  would visibly block the request the user wanted to be prompted for).
- **Defensive default**: missing/null/unrecognised `permission_mode` is
  treated as NOT bypass — fail safe toward the user's normal approval
  flow.
- **No config opt-out**: explicitly rejected. A config flag that lets a
  user say "auto-approve always, even in default mode" would re-introduce
  the exact silent-YOLO behaviour this plan is closing. If users want
  bypass behaviour they have one supported way to get it: run Claude Code
  in `bypassPermissions` mode.

## Tasks

### Phase 1: Shared utility (TDD)

- [ ] ⬜ **Task 1.1**: Create `tests/unit/utils/test_permission_mode.py`
  with failing tests for `is_bypass_mode(hook_input)`:
  - returns True when `permission_mode == "bypassPermissions"`
  - returns False for `default`, `plan`, `acceptEdits`, `dontAsk`
  - returns False when key missing, value None, value empty string
  - returns False when hook_input is `None` or non-dict
- [ ] ⬜ **Task 1.2**: Implement `src/claude_code_hooks_daemon/utils/permission_mode.py`
  with `is_bypass_mode()` and module-level constant
  `BYPASS_PERMISSIONS_MODE = "bypassPermissions"`. Tests turn green.

### Phase 2: Retrofit `auto_approve_reads` (TDD)

- [ ] ⬜ **Task 2.1**: Add failing tests to
  `tests/unit/handlers/permission_request/test_auto_approve_reads.py`:
  - `matches()` returns False when `permission_mode == "default"` even
    for Read/Glob/Grep
  - `matches()` returns False when `permission_mode` missing
  - `matches()` returns False for `plan`, `acceptEdits`, `dontAsk`
  - `matches()` returns True only when tool is read-only AND
    `permission_mode == "bypassPermissions"`
- [ ] ⬜ **Task 2.2**: Update `auto_approve_reads.py`:
  - Import `is_bypass_mode` from the new utility
  - `matches()` short-circuits: `if not is_bypass_mode(hook_input): return False`
  - `handle()` keeps existing ALLOW logic (defensive — only reachable in bypass mode)
- [ ] ⬜ **Task 2.3**: Update existing positive-case tests to include
  `"permission_mode": "bypassPermissions"` in their hook_input fixtures so
  they continue to exercise the approval path. **Do not weaken any
  assertions.**
- [ ] ⬜ **Task 2.4**: Implement `get_claude_md()` to return guidance
  explaining: handler is gated on bypass mode; in default mode the user
  will see the normal approval prompt; this is intentional.

### Phase 3: Acceptance test

- [ ] ⬜ **Task 3.1**: Update the handler's `get_acceptance_tests()` to
  include both a positive case (bypass mode → ALLOW) and a negative case
  (default mode → handler does not match, prompt would surface).

### Phase 4: Daemon verification + QA

- [ ] ⬜ **Task 4.1**: Run `./scripts/qa/run_all.sh` — must pass all 12
  gates with zero failures
- [ ] ⬜ **Task 4.2**: Restart daemon and verify RUNNING:
  ```
  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
  $PYTHON -m claude_code_hooks_daemon.daemon.cli status
  ```
- [ ] ⬜ **Task 4.3**: Probe the live daemon directly with synthetic
  PermissionRequest events at both `permission_mode == "default"` (must
  return no decision) and `"bypassPermissions"` (must ALLOW) using `nc`.

### Phase 5: Documentation

- [ ] ⬜ **Task 5.1**: Add a brief note to `CLAUDE/Code/HooksSystem.md`
  near the `permission_mode` table cross-referencing this plan as the
  rationale for why the daemon gates auto-approve on it.
- [ ] ⬜ **Task 5.2**: Add a post-upgrade-task note in
  `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` explaining the
  behavioural change so the next release notes pick it up: users running
  in `default` mode will start seeing their normal approval prompts for
  Read/Glob/Grep again. This is the correct, intended behaviour but it
  WILL feel like a regression for users who had silently relied on the
  bug.

### Phase 6: Plan closure

- [ ] ⬜ **Task 6.1**: Mark all tasks complete, set status to Complete,
  `git mv` plan folder to `Completed/`, update `CLAUDE/Plan/README.md`.

## Dependencies

- **Blocked by**: Plan 00105 (v3.11.0 stability hardening) — do not
  begin execution while 00105 is in flight on main.
- **Related**: Plan 00089 (auto_approve_reads schema fix) — touches the
  same handler. If 00089 is still in progress when this plan starts,
  rebase on top of it. The two plans are non-overlapping in surface area
  (00089 changes the read-only tool detection; 00106 wraps that detection
  in a permission-mode gate).
- **Blocks**: any future plan that introduces additional auto-approving
  handlers — those should call `is_bypass_mode()` from day one.

## Technical Decisions

### Decision 1: Defer via `matches() = False` rather than

`Decision.NO_DECISION` or similar

**Context**: There are three plausible ways to "defer" when not in bypass
mode: (a) `matches()` returns False so the chain skips, (b) `handle()`
returns `Decision.ALLOW` only when in bypass and some other decision
otherwise, (c) introduce a new "defer" decision type.

**Decision**: (a) — `matches()` returns False. Reasons:

1. The dispatch system already treats a non-matching handler as
   "deferred" — Claude Code's normal flow runs.
2. (b) requires defining what "no auto-approve" looks like. `Decision.DENY`
   would show the user a denial; `Decision.ALLOW` is what we're trying to
   gate. There is no clean third option.
3. (c) introduces a new core-protocol concept for one handler — YAGNI.

**Date**: 2026-05-08

### Decision 2: No config flag to override the gate

**Context**: A `force_auto_approve: true` config option would let users
preserve the current behaviour.

**Decision**: Reject. The whole point of the security gap is that silent
auto-approval in `default` mode is dangerous. A config flag would just
re-enable the bug for anyone who turned it on, and produces a worse
failure mode than the original (the user now thinks they have approval
prompts, but the config silently disables them). If users want bypass
behaviour, the supported path is `claude --dangerously-skip-permissions`.

**Date**: 2026-05-08

## Success Criteria

- [ ] All existing `test_auto_approve_reads.py` tests pass after fixture
  updates that add `"permission_mode": "bypassPermissions"` to positive
  cases — **no test assertions weakened**.
- [ ] New tests prove auto-approve does NOT fire in `default`, `plan`,
  `acceptEdits`, or `dontAsk` mode.
- [ ] New tests prove auto-approve DOES fire in `bypassPermissions`
  mode for Read/Glob/Grep.
- [ ] `is_bypass_mode()` utility has its own unit tests at 100%
  coverage.
- [ ] `./scripts/qa/run_all.sh` passes all 12 gates.
- [ ] Daemon restarts successfully — `status: RUNNING`.
- [ ] Live `nc` probe in default mode does NOT auto-approve.
- [ ] Live `nc` probe in bypassPermissions mode DOES auto-approve.
- [ ] `get_claude_md()` returns non-None guidance documenting the gate.

## Risks & Mitigations

| Risk                                                                             | Impact | Probability | Mitigation                                                                                                                                                                                             |
| -------------------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Users in `default` mode currently relying on silent bypass perceive a regression | Med    | Med         | Post-upgrade-task note in release notes explains the behavioural change as a security fix; prompts re-appearing is the *intended* outcome                                                              |
| `permission_mode` field shape changes upstream in a future Claude Code release   | Med    | Low         | Defensive default — unrecognised values fail safe to NOT bypass; daemon already reads the field via the typed schema in `input_schemas.py`, so a shape change would surface in schema-validation tests |
| Plan 00089 still in flight at execution time                                     | Low    | Med         | Rebase strategy: 00089 changes tool-detection, 00106 wraps it; no merge conflict expected                                                                                                              |

## Notes & Updates

### 2026-05-08

- Plan created. Research complete. QUEUED behind Plan 00105.
- Decision A confirmed: `permission_mode` field is authoritative and
  already plumbed through the daemon end-to-end.
- Blast radius: 1 handler (`auto_approve_reads`), 1 new utility module,
  1 utility test file, additions to 1 existing handler test file, 1
  doc cross-reference, 1 post-upgrade-task note. No core-protocol
  changes.
