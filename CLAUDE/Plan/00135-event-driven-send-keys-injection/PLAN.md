# Plan 00135: Event-Driven `send-keys` Injection

**Status**: In Progress — architecture decided: ARCH-B (PTY supervisor), CCY-first for dogfooding. See `plan-audit-fable-1.md` and Decision G.
**Created**: 2026-06-22
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Teams

> 🔁 **Iterated twice. See `BRAINSTORM-SYNTHESIS.md` (launcher-controlled
> redesign) and `HOSTILE-REVIEW-2.md` (NO-GO on that redesign as written).**
>
> - **Review #1** blocked the daemon-handler design: `$TMUX_PANE` lost at the
>   socket boundary; no idle signal.
> - **Brainstorm redesign** (launcher + dedicated 1:1 observe-only daemon +
>   single injector) **dissolved the pane-identity sub-problem by construction.**
> - **Review #2** returned **NO-GO as written**, but most blockers are *fixable
>   technical* issues, and the brand objection is **down-weighted by user
>   decision** (see `context.md` follow-up). The two that matter:
>   - **SB-1 (coexistence):** shared daemon reaps the dedicated daemon on restart
>     (`enforce_single_daemon` matches project-root, not socket). The user made
>     concurrent coexistence a **hard requirement** → must be solved properly
>     (socket-aware enforcement / distinct root / do-not-reap registry), not the
>     one-directional `--no-enforce-single` hack.
>   - **SB-2 (FATAL-2):** "is the user typing?" has **no reliable tmux signal**
>     (`client_activity` likely measures redraw). The only design that answers it
>     *by construction* is **ARCH-B (a launcher-owned PTY supervisor)** that sees
>     raw input bytes — at the cost of TUI-fidelity risk.
> - **RESOLVED (2026-07-09):** third audit (`plan-audit-fable-1.md`, Fable) is the
>   first to examine the REAL launchers (`ccy`) and finds the ARCH-A tmux world does
>   not exist in either launch environment — decision is **ARCH-B (PTY supervisor)**,
>   **CCY-first** for dogfooding. The ARCH-A tmux design (this document's Phases 1–4,
>   `tmux_inject`, `send-keys`, dedicated daemon, SB-1 enforcement fix) is **shelved
>   as the documented fallback**; the live plan of record is the slice plan in
>   `plan-audit-fable-1.md` §5, re-ordered CCY-first. See Decision G.

> Source research: `research-note.md` (do not edit). Scene-setting + the user's
> framing: `context.md`. **This plan is written to survive a hostile multi-lens
> review — see "Review Focus" at the end.**

## Overview

This plan adds a **safe, opt-in capability for the daemon to inject a whitelisted
slash command (or prompt) into the live, watchable Claude Code tmux session** in
response to a daemon hook event or a context-threshold watchdog. The flagship is
**auto-`/compact` at a custom (lower) context threshold**; secondary cases are a
re-orientation prompt after `PostCompact`, `/fix` on a failing test run, and a
session-bootstrap prompt.

The mechanism is `tmux send-keys -t "$TMUX_PANE"` (the note's §1/§2 conclusion;
`screen`, `expect`, custom PTY, and especially `TIOCSTI` are rejected). The
delivery is deliberately **incremental**: a minimal, fully-guarded slash-command
injector ships first with its complete safety model and acceptance tests; the
ambitious self-driving automations come later behind the *same* rails.

The single most important architectural finding (verified, not assumed): **the
daemon already receives the statusLine JSON** — `model_context.py` reads
`context_window.used_percentage` directly off the Status event input (lines
144–146). So the context-% sidecar is written by a daemon status-line handler
inside the existing pipeline, **not** by a bolt-on `~/.claude/statusline.sh`.

## Goals

- Provide an **opt-in** (`get_default_enabled()` → `False`) capability to inject
  an **allowlisted** slash command/prompt into the current tmux pane in response
  to a daemon event or a context-threshold watchdog.
- Ship the **flagship auto-`/compact`-at-custom-threshold** safely: daemon
  status-line handler writes a `pct`/`idle`/`timestamp` sidecar; a watchdog
  injects `/compact` only when over-threshold, idle, and within cooldown/cap.
- Make every guardrail a **first-class, enforced** requirement: opt-in +
  allowlist, loop-guard sentinel, idle-gating, cooldown, max-injections cap,
  tmux-presence detection (graceful no-op when `$TMUX_PANE` unset), and zero
  collision with the existing Stop auto-continue.
- Use only **`subprocess` argument-list** invocations of `tmux` (never
  `shell=True`); never interpolate untrusted event data into a send-keys payload.
- Keep the whole system **observable** (watchdog runs in its own tmux pane).

## Non-Goals

- **NOT** a competing Stop continue-injector. `auto_continue_stop.py` owns the
  Stop-continuation contract (5 branches) — we explicitly do not inject on Stop.
- **NOT** screen/`expect`/PTY/`TIOCSTI` — `send-keys` only (note §2, §7). The
  TIOCSTI ban is restated as a hard rule (Technical Decision E).
- **NOT** a replacement for native auto-compact when the built-in threshold is
  acceptable — this exists only to set a *custom, lower* threshold.
- **NOT** arbitrary/free-form command injection. Only entries on the configured
  allowlist may ever be sent. No interpolation of event data into payloads.
- **NOT** headless/`-p` mode — the entire point is to keep the visible TUI.
- **NOT** a big-bang. The self-driving multi-event automations are later phases.

## Context & Background

See `context.md` for the user's framing and the danger analysis. Key verified
facts that shape the design:

- **Daemon already has the statusLine payload.** `model_context.py:144–146`.
  Sidecar is written from a daemon status-line handler.
- **`HookResult` has no injection field today** — `decision/reason/context/`
  `guidance/handlers_matched` only (`core/hook_result.py:54–58`). The dispatch
  pipeline returns a *result*; it performs no side effects like keystrokes.
- **Stop is already owned** — `auto_continue_stop.py` (priority 10, terminal).
- **Secure subprocess pattern exists** — fixed argument lists + `# nosec B404`
  (e.g. `git_hooks_executable_fixer.py:18`). Detachment via `os.fork`/`os.setsid`
  (`daemon/cli.py:392–431`).
- **Safe runtime-file location** — `ProjectContext.daemon_untracked_dir()`
  (never `/tmp`, per CLAUDE.md security standards).
- **Opt-in mechanism** — override `get_default_enabled()` → `False`
  (`core/handler.py:228`).

## Technical Decisions

### Decision A: Architecture — hybrid (sidecar handler + watchdog + thin injector library)

**Context**: The note offers (a) inject-capability on `HookResult`, (b) a family
of handlers, (c) a daemon-managed watchdog, (d) hybrid.

**Options considered**:

1. **HookResult gains an `inject_keys` field** — handler returns "type this".
   Rejected as the *primary* shape: it couples a pure, synchronous, side-effect-
   free dispatch result to a side effect (typing into a TTY). It also runs the
   injection *inside the synchronous hook*, risking the deadlock/mis-order
   against the TUI redraw the note warns about (§3). Worst of all, the flagship
   (context %) is **not hook-driven at all** — it is statusLine-only — so a
   HookResult field cannot deliver the flagship.
2. **A dedicated handler family that injects directly** — same synchronous-hook
   hazard; couples matching logic to TTY side effects.
3. **A daemon-managed watchdog only** — handles the flagship but not the
   event-driven cases (PostCompact re-orientation, `/fix`).
4. **Hybrid (RECOMMENDED)**: three cleanly separated pieces:
   - a **status-line handler** (`tmux_context_sidecar`) that writes
     `pct`/`idle`/`timestamp`/`session_id`/`pane` to a sidecar in
     `daemon_untracked_dir()` — *no injection*, just observation;
   - a small **`tmux_inject` utility module** (the only place that ever calls
     `tmux send-keys`) enforcing the allowlist + tmux-presence + loop-guard;
   - a **standalone, user-launched watchdog script** (its own tmux pane) that
     reads the sidecar and calls the inject utility when over-threshold + idle +
     cooldown-ok + under-cap. Event-driven cases (PostCompact, PostToolUse `/fix`)
     are later opt-in handlers that **enqueue an intent** to a sidecar queue
     which the same watchdog drains — handlers never type directly.

**Decision**: **Option 4 (hybrid)**, because it (i) separates pure dispatch from
TTY side effects (SOLID/SRP), (ii) delivers the statusLine-only flagship that no
HookResult field can, (iii) keeps the only `send-keys` call site in one auditable
utility (single enforcement point for the allowlist), and (iv) keeps the
controller observable in its own pane. Reuse of the existing status-line pipeline
for the sidecar is justified by `model_context.py:144–146` — the data is already
in hand; a separate `statusline.sh` would duplicate it and risk drift.

**Why standalone watchdog, not daemon-spawned (initial phases)**: a daemon-forked
background loop that types into a user TTY is the highest-blast-radius design and
the hardest to make observable. A documented script the user launches in a
visible pane is observable by construction, trivially killable, and cannot type
unless the user started it. Daemon-managed spawning is deferred (later phase,
gated behind explicit config) until the safety rails are proven in the field.

### Decision B: Safety model (NON-NEGOTIABLE, make-or-break)

All six are **first-class plan requirements**, each with its own RED test:

1. **Opt-in + allowlist.** The sidecar handler and any injector handler override
   `get_default_enabled()` → `False`. The injector utility refuses to send
   anything not on a config `allowlist` of exact slash commands/prompts. **Never
   interpolate untrusted event data into a payload** — only verbatim allowlist
   entries are ever sent (fail-closed if a requested payload is not an exact
   allowlist member).
2. **Loop-guard sentinel.** Every injection is tagged (e.g. a trailing
   zero-width-free marker comment / a sidecar "last-injected" record keyed by
   session). `UserPromptSubmit`/intent-enqueue logic skips events whose origin is
   our own injection, so an injected prompt can never re-trigger its own
   injection. Cap-and-cooldown back this up as defence-in-depth.
3. **Idle-gating.** Inject only when the sidecar `state == idle` AND the
   timestamp is fresh; never mid-stream (note §3). Crude `capture-pane` fallback
   only if the sidecar is stale.
4. **Cooldown + max-injections-per-session cap.** Both configurable; both
   enforced in the injector utility (single choke point), not just the watchdog.
5. **tmux-presence detection.** If `$TMUX_PANE` is unset, the utility is a
   **graceful no-op** (logged at debug, **not** an error/abort) — the daemon must
   work identically outside tmux.
6. **No Stop collision.** We do not register on Stop. Acceptance + integration
   tests assert `auto_continue_stop` behaviour is unchanged.

### Decision C: Timing/decoupling — build Pattern B (queue + drain-when-idle) first

**Context**: Note §3 — Pattern A (fire-and-forget detached helper) vs Pattern B
(enqueue intent, watchdog drains when idle). Synchronous hooks can deadlock if
they block then type.

**Decision**: **Pattern B first.** The flagship (watchdog) is already a drain
loop, so Pattern B is the natural spine and is the *safe* one — it never types
mid-stream and decouples entirely from the synchronous hook lifecycle. Pattern A
(detached `os.setsid` helper from a handler) is **deferred**; if ever added it
must still route through the same allowlist/cap/idle utility. Handlers in this
plan **enqueue intents**; they never spawn a typing subprocess synchronously.

### Decision D: Compaction flagship + PostCompact re-orientation

- **Sidecar**: `TmuxContextSidecarHandler` (status_line) writes
  `{pct, state, ts, session_id, pane}` to `daemon_untracked_dir()/tmux-inject/`.
  Confirmed feasible — context % is in the Status payload (`model_context.py`).
  It is **NOT** in any hook payload (note §5/§6), so this handler is the only
  viable source.
- **Watchdog**: standalone script in its own pane: every N seconds, if
  `pct ≥ threshold` AND idle AND `cooldown` elapsed AND under cap → inject the
  allowlisted `/compact`. Custom (lower) threshold is the entire reason to exist.
- **PostCompact re-orientation**: an opt-in `PostCompact` handler **enqueues** a
  re-orientation prompt (allowlisted) for the watchdog to drain once idle after
  compaction — it does not type directly.

### Decision E: Cross-platform / portability & security

- **tmux only.** `screen`/`expect`/PTY rejected (note §2). **TIOCSTI is banned
  outright** — deprecated/disabled on modern Linux, a privesc vector (note §7).
  No code path may attempt kernel keystroke injection.
- **subprocess argument-list only**, never `shell=True` (CLAUDE.md security).
  All `tmux` calls use fixed lists: `["tmux", "send-keys", "-t", pane, "-l", payload]` then a separate `["tmux", "send-keys", "-t", pane, "Enter"]`, with
  `# nosec B404` documentation per the existing pattern.
- **Single enforcement point**: the `tmux_inject` utility is the *only* call site
  for `send-keys`; allowlist, presence, cap, cooldown, and loop-guard are all
  enforced there. QA `run_security_check.sh` must pass with zero issues.

### Decision F: Incremental delivery (no big-bang)

Phase 1 ships the minimal safe slash-command injector + full safety model +
acceptance tests. Phase 2 ships the flagship sidecar + watchdog (`/compact`).
Phase 3 adds opt-in event-driven enqueue handlers (PostCompact, `/fix`, bootstrap)
— all reusing Phase 1's utility and rails. Phase 4 (optional, deferred) considers
daemon-managed watchdog spawning only after field-proving the rails.

### Decision G: Pivot to ARCH-B (PTY supervisor), CCY-first — SUPERSEDES Decisions A–F for delivery

**Context**: The third audit (`plan-audit-fable-1.md`, Fable) is the first review to
inspect the actual launchers the user runs (`ccy`). Findings that force the pivot:

- **Neither real launch environment runs Claude inside tmux**, and neither ships
  tmux in tracked IaC (audit N-1, claims #10–#11). Full `ccy` runs
  `podman run … claude`; the thin LXC alias runs `claude` directly. ARCH-A's tmux
  session, `$TMUX_PANE`, dedicated daemon, key-table hook and `send-keys` target an
  environment that would have to be **built** (cross-repo) before one injection fires.
- **Both launchers give a PTY supervisor a one-line insertion point** and raw input
  bytes — so "is the user typing?" (SB-2) and "is it still Claude?" (SB-3, via
  `waitpid`) are answered **by construction**, and the dedicated daemon + SB-1
  enforcement change fall out of scope entirely.

**Decision**: Adopt **ARCH-B — a thin, TDD'd PTY supervisor (`claude-supervise`)**
that wraps the `claude` process in its own namespace; the daemon stays strictly
**observe-only** (a status-line context sidecar). The delivery plan of record is the
staged slice plan in `plan-audit-fable-1.md` §5.

**Ordering override — CCY-first (not the audit's LXC-first)**: this repo is developed
using `ccy` (podman), so the supervisor must run under `ccy` for dogfooding to be
real. **Key dogfooding lever**: no fedora-desktop image change is needed to begin —
this session already runs inside the podman container, so `claude-supervise -- claude …`
can be exercised in-place. The `entrypoint.sh` wrap + `ccy --supervise` opt-in flag +
CCY version bump (a fedora-desktop change, named as a cross-repo dependency) is only
required later to make supervision the seamless default. LXC integration follows CCY.

**Assumed defaults (from the audit; correct me if wrong)**: supervisor lives in
`src/claude_code_hooks_daemon/supervise/` (installer-shipped, full QA/95% bar,
`pty.openpty`-testable in CI); `--dry-run` is the default and `--arm` refuses without
`--max-cost`; the allowlist is frozen to `{'/compact'}`; observability is a status-line
armed/dry-run segment + a decision log (the tmux "watch pane" idea dies with tmux).

**Date**: 2026-07-09

### Decision H: The flagship is a compact-AND-RESUME sequence, not a single `/compact`

**Context (user correction, 2026-07-09)**: injecting `/compact` alone **kills
execution** — after compaction the agent sits idle waiting for input and the
autonomous run dies. The real flagship is a short **sequence**: inject `/compact`,
wait until compaction is **definitely under way**, then inject a `continue` nudge.
Per the user, a `continue` injected once compaction has started **buffers into the
post-compact session** and the agent resumes — so we do NOT need to wait for
compaction to finish. The whole point is unattended continuity across
context-window pressure.

**Detection signals (verified in daemon source)**: Claude Code fires `PreCompact`
when compaction **starts** (already consumed by `transcript_archiver`) — that is
the "definitely under way" signal gating the `continue` injection. (A
`SessionStart` with `source="compact"` fires when compaction **finishes**; there is
no `PostCompact` event. The finish edge is now only optional — for
observability/cooldown — not required to trigger `continue`.)

**Decision — daemon-as-sensor, supervisor-as-actuator**: the daemon writes state
transitions to the sidecar; the PTY supervisor reads them and runs a two-state
machine (no screen-scraping for the compaction edges):

| Phase            | Trigger (sidecar, daemon-written)          | Supervisor action                                                                                        |
| ---------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| MONITOR          | `pct ≥ threshold` AND idle AND cooldown ok | inject `/compact`; → AWAIT_COMPACTING                                                                    |
| AWAIT_COMPACTING | `compacting=true` (from `PreCompact`)      | inject `continue` (buffers into the post-compact session, which resumes the agent); → MONITOR (cooldown) |

Safety rails (allowlist, cooldown, per-session cap, loop-guard, idle-gate,
tmux-free) all still apply at the single injection choke point. The allowlist is
now the closed set `{'/compact', 'continue'}`. A wall-clock deadman aborts
the AWAIT_COMPACTING phase if the expected transition never arrives (so a failed
compact cannot wedge the machine).

**Date**: 2026-07-09

### Decision I: Launcher-agnostic artifact + per-launcher contract (podman + LXC)

**Context**: the user runs Claude via two launchers — full podman `ccy` and a thin
`ccy()` alias inside LXC — and both must be supported going forward. Coupling the
supervisor to the daemon package/venv (original v0) would have blocked LXC and
risked breaking on daemon upgrades.

**Decision**: factor the system into three pieces so any launcher is a small add-on:

1. **Launcher-agnostic artifact** — `.claude/ccy/claude-supervise.py`: tracked in the
   project, **stdlib-only**, runs under any container's system `python3` (no venv, no
   `claude_code_hooks_daemon` import). Decoupled from daemon upgrades (lives outside
   `.claude/hooks-daemon/`).
2. **Per-project config** — `.claude/ccy/ccy.env` (tracked): exports
   `CCY_CLAUDE_WRAPPER` via `${VAR:-...}`.
3. **Per-launcher contract** (~5 lines): *source `.claude/ccy/ccy.env`, then apply
   `$CCY_CLAUDE_WRAPPER` to the `claude` invocation.*
   - **podman `ccy`**: DONE — `entrypoint.sh` sources ccy.env + wraps (fedora-desktop
     `e9ed32c`). Sourced in-container (sandbox), never on the host.
   - **LXC thin alias**: TODO — the `ccy()` function must implement the same contract.
     It already runs **inside** the LXC container (the sandbox), so sourcing ccy.env
     there is the same in-sandbox security model. Requires: python3 present in the LXC
     image (verify), and editing wherever the alias is defined (lxc tooling — OPEN
     QUESTION: exact location, e.g. lxc-bash).

**Why this is right**: adding a launcher = implementing the 5-line contract; the
artifact and config are shared, tracked, and upgrade-safe. The standalone-file
refactor is what unlocks LXC (system `python3`, no venv).

### Decision J: "Red" is defined ONCE — the status-line classifier is the SSoT

**Context (user, 2026-07-10)**: the compact trigger is "status line is red", and red
changes per model / context-window size / config (200k red = 76%, 1M red = 40%, all
overridable). v1 must NOT carry its own `compact_at_pct` threshold — that would
duplicate the boundary and drift from the status line.

**Decision**: extract the red/tier determination currently inline in
`model_context.py` (`_resolve_tier_thresholds` + the `used_pct >= red_pct` check) into
ONE shared, tested classifier (e.g. `classify_context(used_pct, window_size, cfg)` →
tier enum, and `is_red(...)`). BOTH consumers use it:

- `ModelContextHandler` — for the status-line icon/colour (behaviour unchanged).
- The v1 sidecar writer — to record `red: true|false` (NOT a raw pct the supervisor
  re-thresholds).

The supervisor reads `red` from the sidecar and triggers on it (+ idle) — zero
threshold logic in the supervisor. Change a tier/model/config once and both the
status line and the compact trigger follow automatically. This is the concrete
definition of Decision H's "MONITOR: pct ≥ threshold" row.

**Date**: 2026-07-10

## Tasks

> **⚠️ Tasks below (Phases 0–4) are the SHELVED ARCH-A design, retained only as the
> documented fallback if the ARCH-B PTY spike (S-PTY) fails in a real environment.**
> They reference files that intentionally do NOT exist yet
> (tests/unit/utils/test_tmux_inject.py (shelved ARCH-A, never created),
> tests/unit/handlers/status_line/test_tmux_context_sidecar.py (shelved ARCH-A, never created)) and will not be
> created under ARCH-B. **The live, CCY-first task plan is
> `plan-audit-fable-1.md` §5 (Slices 0–3).**

### Phase 0: Verification & design lock-in

- [ ] ⬜ **Task 0.1**: Confirm `$TMUX`/`$TMUX_PANE` are present in a real hook
  subprocess (`./scripts/debug_hooks.sh start` then `env | grep TMUX` from a
  hook) and that they are **absent** outside tmux — drives the no-op path.
- [ ] ⬜ **Task 0.2**: Confirm the live Status payload contains
  `context_window.used_percentage` and `context_window_size` (re-verify against
  `model_context.py` and a captured event). Document the exact sidecar schema.
- [ ] ⬜ **Task 0.3**: Lock the config schema: `allowlist` (list of exact
  payloads), `threshold_pct`, `cooldown_seconds`, `max_injections_per_session`,
  `idle_freshness_seconds`, `poll_seconds`. Document defaults (conservative).

### Phase 1: Minimal safe injector utility (TDD) — the foundation

- [ ] ⬜ **Task 1.1**: RED — create tests/unit/utils/test_tmux_inject.py (shelved ARCH-A, never created)
  covering: allowlist enforcement (reject non-member, fail-closed), tmux-presence
  no-op when `$TMUX_PANE` unset, argument-list-only invocation (no `shell=True`),
  cooldown enforcement, per-session cap enforcement, loop-guard sentinel write.
- [ ] ⬜ **Task 1.2**: GREEN — implement `utils/tmux_inject.py` (the ONLY
  `send-keys` call site). Use `subprocess` with fixed argument lists; `-l`
  literal payload then separate `Enter`; sidecar-backed cooldown/cap/loop-guard
  state in `daemon_untracked_dir()`.
- [ ] ⬜ **Task 1.3**: RED/GREEN — a minimal opt-in
  `SessionStart`-or-manual-trigger demonstration handler (or CLI subcommand)
  that requests an allowlisted injection through the utility, proving the
  end-to-end path with `get_default_enabled()` → `False`.
- [ ] ⬜ **Task 1.4**: REFACTOR; verify 95%+ coverage on the new module.
- [ ] ⬜ **Task 1.5**: Add `get_claude_md()` + `get_acceptance_tests()` for any
  new handler (opt-in, idle-gated positive/negative cases, no-op-without-tmux).
- [ ] ⬜ **Task 1.6**: QA — `./scripts/qa/run_all.sh` (security check MUST be 0).
- [ ] ⬜ **Task 1.7**: Daemon restart verification — restart + `status` = RUNNING;
  logs clean. **Do not proceed until RUNNING.**

### Phase 2: Flagship — context sidecar + `/compact` watchdog (TDD)

- [ ] ⬜ **Task 2.1**: RED —
  tests/unit/handlers/status_line/test_tmux_context_sidecar.py (shelved ARCH-A, never created): writes
  `{pct,state,ts,session_id,pane}`; handles missing fields; `get_default_enabled`
  → `False`; never injects.
- [ ] ⬜ **Task 2.2**: GREEN — `handlers/status_line/tmux_context_sidecar.py`
  reading the Status payload exactly as `model_context.py` does; writes sidecar
  to `daemon_untracked_dir()/tmux-inject/`.
- [ ] ⬜ **Task 2.3**: RED/GREEN — the standalone watchdog script (in `scripts/`
  or `examples/`) with tests for: threshold gate, idle gate, cooldown, cap. The
  watchdog calls the Phase 1 utility — it does not re-implement `send-keys`.
- [ ] ⬜ **Task 2.4**: Document running the watchdog in its **own visible tmux
  pane**; reinforce the "custom lower threshold only" rationale.
- [ ] ⬜ **Task 2.5**: QA + daemon restart verification (as 1.6/1.7).

### Phase 3: Event-driven enqueue handlers (opt-in, TDD)

- [ ] ⬜ **Task 3.1**: RED/GREEN — opt-in `PostCompact` handler that **enqueues**
  an allowlisted re-orientation prompt (watchdog drains when idle). Loop-guard
  asserted.
- [ ] ⬜ **Task 3.2**: RED/GREEN — opt-in `PostToolUse` handler that, on a failing
  test-runner result, enqueues an allowlisted `/fix`-style prompt. Strictly
  pattern-matched; **no event data interpolated** into the payload.
- [ ] ⬜ **Task 3.3**: RED/GREEN — opt-in `SessionStart` bootstrap-prompt enqueue.
- [ ] ⬜ **Task 3.4**: Integration test asserting **no Stop collision** — these
  handlers never register on Stop; `auto_continue_stop` behaviour unchanged.
- [ ] ⬜ **Task 3.5**: QA + daemon restart verification.

### Phase 4 (DEFERRED, optional): daemon-managed watchdog

- [ ] ⬜ **Task 4.1**: Only after field-proving Phases 1–3, design (separate
  plan) a daemon-spawned watchdog gated behind explicit config, preserving
  observability. **Out of scope for initial delivery.**

## Dependencies

- Depends on: existing status-line pipeline (`model_context.py`), `ProjectContext`
  `daemon_untracked_dir()`, Handler base `get_default_enabled()`.
- Must not regress: `auto_continue_stop.py` (Stop), security QA gate.
- Related: research-note.md (source), `context.md` (framing).

## Success Criteria

- [ ] Capability is **opt-in** — every new handler `get_default_enabled()` →
  `False`; default config behaviour is completely unchanged.
- [ ] `tmux_inject` is the **only** `send-keys` call site; it enforces allowlist,
  presence-no-op, cooldown, per-session cap, and loop-guard.
- [ ] Non-allowlisted payloads are **rejected fail-closed**; no event data is ever
  interpolated into a payload.
- [ ] With `$TMUX_PANE` unset, the daemon behaves identically to today (graceful
  no-op, no error).
- [ ] Flagship works: over custom threshold + idle + cooldown → exactly one
  `/compact` injection, observable in a watched pane.
- [ ] `auto_continue_stop` behaviour verified unchanged (no Stop registration).
- [ ] `subprocess` argument-list only; `run_security_check.sh` = 0 issues.
- [ ] All QA checks pass; daemon restarts to RUNNING after each phase.
- [ ] 95%+ coverage maintained; acceptance tests pass in a real session.

## Risks & Mitigations

| Risk                                         | Impact | Probability | Mitigation                                                                                               |
| -------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------------------------------- |
| Feedback loop (injection re-triggers itself) | High   | Medium      | Loop-guard sentinel + cooldown + per-session cap, all in the single utility choke point                  |
| Mid-turn injection submits a half-typed line | High   | Medium      | Idle-gating on fresh sidecar `state==idle`; never type while busy; `-l` then separate `Enter` with delay |
| Command injection via event data             | High   | Low         | Allowlist of exact payloads only; fail-closed; NEVER interpolate event data into send-keys               |
| Wrong-pane targeting after layout change     | Medium | Medium      | Prefer `$TMUX_PANE` self-target; sidecar records the pane; no hard-coded `session:window` in handlers    |
| Runaway token/cost with no human             | High   | Medium      | max-injections-per-session cap + cooldown; watchdog observable + killable in its own pane                |
| Collision with Stop auto-continue            | Medium | Low         | Do not register on Stop; integration test asserts unchanged behaviour                                    |
| `shell=True` / injection regression          | High   | Low         | argument-list only; single call site; security QA gate at 0                                              |
| Daemon-spawned typing loop blast radius      | High   | Low         | Deferred to Phase 4 behind explicit config after field-proving                                           |
| Whole feature too dangerous to ship          | High   | —           | Incremental, opt-in, allowlisted; hostile review gate before merge                                       |

## Notes & Updates

### 2026-07-10 — Armed live-fire post-mortem: two real bugs fixed

First real armed `/compact` fired live (decision.log 12:02:42:
`would-compact: red at 60% + idle -> injected '/compact'`). It exposed two
defects that the dry-run dogfood could not:

1. **Compact had no bot chrome** — the armed payload was a bare `/compact`,
   indistinguishable from a human `/compact`. Fix: `/compact` accepts freeform
   custom instructions as its argument, so the bot chrome now rides along there:
   `/compact 🤖 [ccy-supervisor] automated compaction — NOT human-initiated. After compacting, immediately resume and continue...`. The slash command
   stays the first token (recognised normally); the compaction summary is now
   visibly supervisor-initiated and the instruction reinforces the resume.
2. **`continue` never fired** — the daemon wrote `<session>.compacting` at
   compaction START (12:02:42), but a large-context compaction kept the session
   busy far past the 120s signal TTL; by the first post-compaction idle poll the
   signal was already stale (measured 485s old) so `load_compaction_signal`
   returned nothing and the resume was dropped, leaving the session idle.
   Fixes: (a) TTL 120s → 600s (comfortably outlasts a big compaction);
   (b) `load_compaction_signal` returns the signal Path and `_poll_once`
   CONSUMES (unlinks) it on a successful resume — so a generous TTL can never
   re-fire or wedge a later compaction; (c) the continue is now idle-gated in
   the state machine (never typed into a busy TUI; defers without latching so it
   retries on the next idle poll).

90 supervise tests; QA 13/13 (9739 tests, 95.5% cov); daemon RUNNING. The
running supervisor is the process the session launched under, so this fix takes
effect on the next `ccy` relaunch.

### 2026-07-10 — ARMED for real + bot-marked supervisor messages

- Live dry-run dogfood succeeded first: the real supervisor wrapping a live ccy
  session injected the marker at "red at 55% + idle" (decision.log 11:44:29) — it
  arrived as a submitted prompt, proving the whole pipeline in production.
- Then armed it: `ccy.env` now runs `claude-supervise.py --arm --`, so a real
  `/compact` is injected when red+idle, and `continue` on any compaction.
- User asked for visibly-bot messages: all supervisor-injected PROMPTS now carry
  the `🤖 [ccy-supervisor]` prefix (dry-run marker and `continue`), so they can
  never be confused with human typing. The armed `/compact` stays a bare slash
  command (decorating it would break command recognition; a slash command already
  reads as non-human).
- 87 supervise tests; QA 13/13; armed CLI smoke passes under system python3.
  Takes effect on the next `ccy` relaunch.

### 2026-07-10 — Compaction-detected auto-continue COMPLETE (daemon side)

- Added the DAEMON sensor: `handlers/pre_compact/compaction_signal.py` — an
  opt-in PreCompact handler that atomically writes
  `untracked/context-sidecar/<session>.compacting` (`{ts, session_id}`) whenever
  a compaction starts (supervisor-triggered OR a manual `/compact`). Blocks
  nothing; fail-open.
- Enabled in this repo's config (dogfood). Full integration: HandlerID/Priority,
  `__init__` export, config template + example + drift-guard opt-in set, docs.
- **End-to-end proven live**: a real PreCompact event through `.claude/hooks/pre-compact`
  wrote the `<session>.compacting` marker; the supervisor's live probe reads that
  exact marker and injects a real `continue`. Daemon RUNNING; QA 13/13; 9735 tests.
- The compact-AND-resume loop is now closed: red → `/compact` (armed) or marker
  (dry-run); compaction (any source) → real `continue`. Remaining: arm `/compact`
  in a real ccy session; LXC launcher wiring (`LXC-SUPPORT.md`).

### 2026-07-10 — Compaction-detected auto-continue (supervisor side)

- User insight: `continue` is harmless (it only resumes the agent), so inject it
  FOR REAL even in dry-run; and the supervisor should fire it whenever a
  compaction is DETECTED — including a MANUAL `/compact` the human typed.
- State machine: added top-level compaction detection that fires WOULD_CONTINUE
  exactly once per episode (a latch prevents repeats; it resets when compaction
  ends) from ANY state, even when the context sidecar is stale/absent (a
  compaction stops status renders). `_resolve_payload` now returns the real
  `continue` for WOULD_CONTINUE in both modes.
- Signal transport: the supervisor reads `context-sidecar/<session>.compacting`
  (JSON `{ts}`, deliberately NOT `*.json` so it is never read as a sidecar),
  fresh within `compaction_signal_ttl_seconds` (default 120s).
- Live-proven: with only a `.compacting` signal (no red sidecar), the dry-run
  supervisor injected a real `continue` into the child PTY. 86 supervise tests;
  QA 13/13.
- Next: the DAEMON side — a PreCompact handler that writes the `<session>.compacting`
  signal so a real/manual compaction actually drives this end-to-end.

### 2026-07-10 — Slice 2 live injection wired (dry-run types a real marker)

- The supervisor now WIRES the decision layer into the live `supervise()` PTY
  loop: `_forward_io` polls on a `select` timeout (`poll_seconds`), and on each
  idle tick `_poll_once` reads the sidecar, runs the state machine, and — for a
  non-NOOP decision — INJECTS keystrokes into the child PTY.
- Per user steering: dry-run (default) injects a harmless VISIBLE MARKER
  (`compact suggestion fired from supervisor (dry run mode)` + CR) so the whole
  path is provable without a real compaction; `--arm` injects the real
  `/compact`. Renamed the confusing `--arm` help accordingly (it was "no-op").
- Idle gate (`_is_idle`): never inject within `idle_floor_seconds` of a
  forwarded keystroke, so an injection never corrupts what the human is typing.
- Robustness fix found via the live probe: an EOF stdin is always "readable", so
  `_forward_io` now DROPS stdin from the watch set on EOF — otherwise the loop
  spins and the poll timeout never fires.
- **Live end-to-end proof**: ran the real supervisor (dry-run) over a child PTY
  with a crafted red sidecar; the marker was injected AND appeared in the child's
  terminal output. 74 supervise tests; QA 13/13.
- Next (user idea): even in dry-run, inject a REAL `continue` when a compaction
  is DETECTED (e.g. a manual `/compact`) — `continue` is harmless. Needs a daemon
  PreCompact handler to set `compacting: true` on the sidecar, plus a MONITOR
  transition that fires continue on externally-detected compaction.

### 2026-07-10 — Slice 2 (dry-run) core: sidecar reader + Decision H state machine

- Added to the standalone `.claude/ccy/claude-supervise.py` (still stdlib-only,
  runs under system python3): `load_freshest_sidecar()` (reads the freshest
  valid sidecar by `ts`, marks `stale` past a freshness window, skips malformed
  files), and `CompactStateMachine` — the Decision H MONITOR → AWAIT_COMPACTING
  machine as PURE decision logic returning `WOULD_COMPACT` / `WOULD_CONTINUE` /
  `NOOP` with a reason. Guards: red + idle + fresh + cooldown + per-session cap
  in MONITOR; `compacting`-signal (or await-timeout give-up) in AWAIT_COMPACTING.

- **Injects NOTHING** — this is the decision layer only. `--arm` and the actual
  PTY keystroke writes remain a separate later step (deliberately, so the
  consequential typist behaviour is reviewed before it goes live).

- 25 unit tests (via the importlib `_load` harness); QA 13/13; standalone smoke
  under system python3 3.11.2 passes (usage + exit 2), confirming no daemon
  import crept in.

- Next: wire the state machine into the live `supervise()` PTY loop (poll the
  sidecar on a select timeout, compute idle from `InputActivity`, log decisions)
  — still dry-run — then arm behind `--arm` + `--max-cost`.

- Shipped the SENSOR half of the observe-only boundary (Decision A / ARCH-B):
  `handlers/status_line/context_sidecar.py` — a `get_default_enabled() -> False`
  status handler that renders nothing, injects nothing, and atomically writes
  `{schema_version, red, tier, pct, window_size, cost_usd, session_id, model_id, ts, seq, writer_pid}` to `daemon_untracked_dir()/context-sidecar/<session>.json`
  on every status render.

- `red` is computed via the shared `context_tiers` classifier (Decision J), so the
  sidecar's `red` and the status-line colour are ONE source of truth. It
  `shares_options_with` `model_context`, so any per-project threshold override
  applies to both. The supervisor will read `red` (+ idle) and never re-threshold.

- Dogfooded live: enabled in this repo's `.claude/hooks-daemon.yaml`. Live probes
  confirmed 85% → status line RED + sidecar `red:true`, and 12% → green +
  `red:false`; `writer_pid` matches the running daemon. QA 13/13, daemon RUNNING.

- Next: Slice 2 — arm `claude-supervise` to READ this sidecar and run the
  MONITOR → `/compact` → AWAIT_COMPACTING → `continue` loop (dry-run first).

### 2026-07-09

- v1 TRIGGER defined (user): inject `/compact` when the **status line goes RED** —
  reuse the existing `model_context` red context-% tier as the threshold (not a
  separate configurable one). The daemon status-line handler already computes the
  colour tier; the sidecar records it and the supervisor fires the compact-and-resume
  sequence (Decision H) on red. LXC handoff spec written to `LXC-SUPPORT.md`.
- Supervisor DECOUPLED (user concern: daemon-upgrade fragility + LXC support):
  rewritten as standalone stdlib-only `.claude/ccy/claude-supervise.py` — runs under
  the container's system `python3`, NO venv, NO `claude_code_hooks_daemon` import.
  Old `src/…/supervise/` package + `scripts/claude-supervise` shim removed; startup
  log line added (observability); 33 tests, 100% file coverage; coverage measured via
  `--cov=.claude/ccy` (dir, not file — importlib-loaded). Confirmed running under
  `/usr/bin/python3`. Live proof: THIS session ran under the supervisor (PID 2). See
  Decision I (launcher-agnostic artifact + per-launcher contract; LXC = TODO).
- v0 `claude-supervise` built + committed (`bd40c35`): standalone transparent PTY
  supervisor (dry-run, NO injection), 28 tests, 99.42% cov. Launch shim
  `scripts/claude-supervise` resolves the daemon venv. (Superseded by the decoupled
  standalone file above.)
- Neat per-project config (replaces ad-hoc host exports): tracked
  `.claude/ccy/ccy.env` exports `CCY_CLAUDE_WRAPPER` via `${VAR:-...}`, sourced
  **in-container** by the ccy entrypoint (fedora-desktop `e9ed32c`; CCY_VERSION
  3.26.0, REQUIRED_CONTAINER_VERSION 2.20 forces the rebuild). In-container
  sourcing keeps project code out of the host. Ships dry-run supervision enabled
  for this repo; host env / `ccy --supervise` still override.
- Next: v1 — daemon sensors (context% + idle status-line sidecar; `compacting`
  flag on PreCompact) + supervisor state machine (Decision H) with injection.
- Third audit `plan-audit-fable-1.md` (Fable) added — first review to examine the
  real `ccy` launchers (cloned to `untracked/repos/fedora-desktop`). Verdict
  GO-WITH-CHANGES: pivot to **ARCH-B (PTY supervisor)**, daemon stays observe-only.
- **User decision**: **CCY-first** (overriding the audit's LXC-first ordering) so we
  dogfood on this repo, which is developed using `ccy`. Recorded as Decision G.
- ARCH-A tmux design (Phases 0–4 below) shelved as documented fallback. Live plan of
  record is `plan-audit-fable-1.md` §5, re-ordered CCY-first.
- Slice 0 S-PTY spike run in-container (podman/ccy): a minimal `pty.fork` supervisor
  passed all mechanical rails — output passthrough on a real PTY, exit-code
  propagation (0/42), signalled-child → 128+signo, `waitpid` liveness, termios
  restore on every exit path — and cleanly wrapped the real `claude` binary
  (`claude-supervise-style -- claude --version` → 2.1.205, exit 0). ARCH-B mechanics
  confirmed viable in the real launch environment.
- CCY integration seam raised as fedora-desktop issue #31
  (https://github.com/LongTermSupport/fedora-desktop/issues/31): optional,
  default-off `CCY_CLAUDE_WRAPPER` wrap at `entrypoint.sh` `exec "$@"` + a
  `ccy --supervise` flag. Held pending the supervisor's existence (their YAGNI) —
  seam lands with, or just before, Slice 2.
- Seam IMPLEMENTED in the fedora-desktop clone (user directive to land it now):
  commit `3221101` on `F44` (`entrypoint.sh` `CCY_CLAUDE_WRAPPER` wrap +
  `--supervise` flag + env forward + CCY_VERSION 3.24.0→3.25.0). Default-off
  verified byte-for-byte; bash `-n` + shellcheck clean (0 errors, 0 new findings).
  Committed, NOT pushed (user pushes, then rebuilds ccy on desktop). Full
  `qa-all.bash` deferred to host (ruff absent in this container; change is
  bash-only). `ccy --supervise` is inert/fails-loud until `claude-supervise` is
  vendored (Slice 2).
- Next: Slice 1 (observe-only `context_sidecar` status-line handler, pure `src/`,
  dogfoodable in this ccy session), then Slice 2 (`claude-supervise` TDD'd,
  `--dry-run` default).

### 2026-06-22

- Plan authored from `research-note.md`. Architecture recommendation: **hybrid**
  (status-line sidecar handler + single `tmux_inject` utility + standalone
  observable watchdog), reusing the daemon's existing statusLine payload
  (verified `model_context.py:144–146`). Pattern B (queue + drain-when-idle)
  first. Opt-in + allowlist + loop-guard + idle-gate + cooldown + cap +
  tmux-no-op are first-class requirements. Stop is left untouched.

## Review Focus (for the upcoming hostile multi-lens review)

A hostile reviewer should attack, in priority order:

1. **Feedback-loop safety** — can ANY path cause an injection to re-trigger its
   own injection? Are loop-guard + cooldown + cap genuinely sufficient, and are
   they enforced at the single utility choke point (not bypassable)?
2. **Mid-turn injection** — is idle-gating sound against stale/lying sidecar
   state? What happens if the statusLine handler stops firing (state goes stale)?
3. **Command injection via event data** — prove that no event-derived string can
   reach a send-keys payload; is the allowlist truly the only source?
4. **Runaway cost** — is the per-session cap per *Claude Code session* or per
   *daemon lifetime*? Can a watchdog restart reset the cap and loop?
5. **Wrong-pane targeting** — `$TMUX_PANE` reliability across panes/windows/
   detach-reattach; multi-session containers sharing a daemon.
6. **Is the feature even appropriate to ship?** Weigh the game-changer upside
   against reputational downside. Should Phase 1 ship alone? Should the
   event-driven enqueue handlers (Phase 3) ship at all, or only the
   user-launched watchdog (Phase 2)? Is daemon-spawned typing ever acceptable?
