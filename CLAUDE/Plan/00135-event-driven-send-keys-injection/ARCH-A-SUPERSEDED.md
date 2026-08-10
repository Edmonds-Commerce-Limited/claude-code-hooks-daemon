<!-- ARCHIVED ARTEFACT — NOT THE CURRENT PLAN. See PLAN.md. -->

# ARCH-A (superseded) — archived from `feature/00135-tmux-send-keys-injection`

**This document is history, not current truth.** It is the ARCH-A rewrite of
Plan 00135 as it stood on 2026-06-23, recovered from the
`feature/00135-tmux-send-keys-injection` branch before that branch was removed.

**ARCH-A was not built.** Plan 00135 continued on `main` and settled on
**ARCH-B** (the PTY supervisor, CCY-first for dogfooding) — see `PLAN.md`
Decision G and `plan-audit-fable-1.md`. ARCH-B is what shipped:
`.claude/ccy/claude-supervise.py` and the `compaction_signal` PreCompact
handler. Any `**Status**` line, task list or path reference below describes the
ARCH-A branch as it was abandoned, and none of it should be actioned.

It is kept for the same reason `HOSTILE-REVIEW-1.md`, `HOSTILE-REVIEW-2.md` and
`SPIKES.md` are kept: the spike results and ship-blocker analysis that led to
rejecting ARCH-A are the reasoning behind choosing ARCH-B, and that reasoning is
worth more than the conclusion alone.

The branch also carried `PLAN-v1.md`, a pre-ARCH-A snapshot. It is deliberately
NOT archived here: it is an earlier revision of the document that `PLAN.md` on
`main` descends from, so git already holds it.

---
# Plan 00135: Event-Driven `send-keys` Injection (ARCH-A, buildable)

**Status**: In Progress — building on `feature/00135-tmux-send-keys-injection` (NOT main)
**Created**: 2026-06-22 (v2 rewrite: ARCH-A locked after spikes)
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Teams (per-phase TDD), hostile-review gate before any merge to main

> **This is the buildable v2.** The fork-pending v1 is archived as `PLAN-v1.md`.
> History: `BRAINSTORM-SYNTHESIS.md` (launcher redesign) → `HOSTILE-REVIEW-2.md`
> (NO-GO as written, 9 ship-blockers) → `SPIKES.md` (run 2026-06-23, **resolved
> the architecture fork**). Read `SPIKES.md` "Spike Results" first.

## Architecture decision — LOCKED to ARCH-A (spike-resolved)

The v1 fork (ARCH-A heuristic-idle vs ARCH-B PTY-supervisor) is **settled by the
2026-06-23 spikes**:

- **S-KEYTABLE → GREEN**: a tmux root-table binding can observe a keystroke AND
  forward it losslessly — a positive "human typing now" signal is achievable
  without a PTY supervisor.
- **S-SIG (core) → GREEN**: "does the input box contain text?" is robustly
  answerable by `capture-pane` anchored on the `❯ ` prompt glyph (empty vs typed
  trivially distinguishable).
- **S-ENF → SB-1 confirmed; fix shape settled** (the `--dedicated` marker, below).

Per the spike decision rule (`SPIKES.md` "After the spikes"): \*\*S-KEYTABLE GREEN

- S-SIG GREEN ⇒ ARCH-A is viable; ARCH-B is NOT needed\*\* and is demoted to a
  contingency only if Phase-0's remaining desktop captures (streaming/dialog
  signatures) prove the positive idle template insufficient. The brand-placement
  objection (HOSTILE-REVIEW-2 §6) is **down-weighted by user decision**: this ships
  in the project, with the typist's `tmux_inject` utility held to the project's own
  CI gates (SB-8) via a CI tmux harness (tmux is CI-installable — confirmed in the
  ccy Dockerfile during the spikes).

## Overview

Add a **safe, opt-in capability** for the daemon ecosystem to inject a
**whitelisted slash command** (v1: literally `/compact`) into the live, watchable
Claude Code tmux session, in response to a context-threshold watchdog. Flagship:
**auto-`/compact` at a custom (lower) threshold**. Secondary (later phases):
PostCompact re-orientation, `/fix` on failing tests, session bootstrap.

Mechanism: `tmux send-keys -t "$TMUX_PANE" -l <payload>` then a separate
`Enter` (note §1/§2; `screen`/`expect`/PTY/`TIOCSTI` rejected). Delivery is
**incremental and opt-in** (`get_default_enabled()` → False everywhere).

Three cleanly separated pieces (the hybrid seam HOSTILE-REVIEW-2 endorsed):

1. **Observe-only daemon side (brand-safe, in `src/`)** — a status-line
   `tmux_context_sidecar` handler writes a `{pct, idle, dialog_open, ts, session_id, pane, daemon_pid, seq}` sidecar; an event-driven dialog-open flag
   (PermissionRequest). **The daemon never types.**
2. **`tmux_inject` utility (in `src/`, the ONLY `send-keys` call site)** — enforces
   the closed allowlist, tmux-presence no-op, cooldown, durable cap, loop-guard,
   and the `#{pane_current_command} ∈ {claude,node}` precondition. CI-tmux-tested.
3. **Launcher + dedicated observe-only daemon + watchdog (user-launched, own
   pane)** — a 1:1 session⇄daemon mapping (pane id as birth-time frozen-environ
   data); the watchdog drains intents and calls `tmux_inject`. Observable by
   construction, trivially killable.

## Goals

- Opt-in capability to inject an **allowlisted** slash command into the current
  tmux pane on a context-threshold watchdog trigger; default behaviour unchanged.
- Ship flagship auto-`/compact`-at-custom-threshold safely behind every rail.
- Make each guardrail first-class & enforced at the single `tmux_inject` choke
  point: allowlist, loop-guard, idle-gate (positive template), cooldown, durable
  cap, mandatory cost ceiling, tmux-presence no-op, no Stop collision.
- `subprocess` argument-list only; never interpolate event data into a payload.
- Keep it observable (watchdog in its own pane) and CI-tested (tmux harness).

## Non-Goals

- NOT a Stop continue-injector (`auto_continue_stop.py` owns Stop — untouched).
- NOT screen/`expect`/PTY/`TIOCSTI`. ARCH-B (PTY supervisor) only as a documented
  contingency if Phase-0 desktop captures fail.
- NOT arbitrary injection — v1 allowlist is the closed set `{"/compact"}`, bare
  command only (no argument group).
- NOT daemon-spawned typing (deferred Phase 6, behind explicit config, after
  field-proving).
- NOT merged to main until the hostile-review gate passes (Phase 5).

## Ship-blocker register (HOSTILE-REVIEW-2 → resolution in this plan)

| SB   | Blocker                                               | Resolved by (phase)                                                                                                                               |
| ---- | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| SB-1 | Shared daemon reaps dedicated daemon on restart       | Phase 3 (`--dedicated` marker + enforcement exclude + dedicated runs `enforce_single_daemon=false`); S-ENF live survival test                     |
| SB-2 | "Is the user typing" / idle predicate fails open      | Phase 2 (positive whole-screen idle template, fail-closed + self-disable on no-match) + S-KEYTABLE per-key corroboration + dialog-open event flag |
| SB-3 | `#{pane_pid}` matches a bare shell after Claude exits | Phase 1/4 (`#{pane_current_command} ∈ {claude,node}` HARD precondition + verify Claude child PID)                                                 |
| SB-4 | Relaunch mints a fresh cap → unbounded                | Phase 4 (durable relaunch-stable cap key + rolling window; launcher reads ledger on startup; RED test)                                            |
| SB-5 | No mandatory cost ceiling                             | Phase 4 (`max_total_cost_usd` MANDATORY when armed, enforced at choke point + deadman; wall-clock = backstop)                                     |
| SB-6 | Allowlist regex gates syntax, not destructiveness     | Phase 1 (closed semantic allowlist `{"/compact"}`; regex secondary; no arg group; reject custom slash commands)                                   |
| SB-7 | Sidecar writer unauthenticated                        | Phase 2 (dir `0700`, `O_EXCL`/no-symlink, daemon-PID + monotonic seq stamp, fail-closed; launch token is identifier, never secret)                |
| SB-8 | Injector untested by project gates                    | Phase 1 (CI-runnable tmux harness; single-`send-keys`-site + `-l` + no `paste-buffer`/`TIOCSTI`/`shell=True` CI invariant)                        |
| SB-9 | Second daemon mode forks the lifecycle matrix         | Phase 3 (CLI disambiguates dedicated vs shared by socket; document dogfooding "which daemon" answer; upgrade path leaves dedicated alone)         |

## Technical Decisions

### A: Hybrid seam — observe-only daemon + single injector utility + user-launched watchdog

Unchanged from v1 Decision A and explicitly endorsed by HOSTILE-REVIEW-2 ("right
architectural seam, preserves the brand boundary"). The daemon is never the
`send-keys` caller; the only call site is the `tmux_inject` utility.

### B: Idle predicate — POSITIVE whole-screen template, fail-closed (SB-2)

The injector gates on a **positive** assertion that the entire captured region
matches a known-idle template (modulo cursor), NOT a bottom-region empty-box +
negative blocklist (which fails open on an unrecognised modal). Config-supplied,
version-fragile by nature → **self-disabling on no-match** (degrade to
never-inject, loudly surfaced). Corroborated by (a) the S-KEYTABLE per-key
"human typing now" signal and (b) the event-driven dialog-open flag. The
dedicated daemon's Stop-event idle-latch covers Claude-busy; the
PermissionRequest flag covers permission modals (with documented
lifetime/coverage holes — Phase-0 enumerates event-invisible modals).

### C: Cap — durable, relaunch-stable, rolling window (SB-4)

Persisted ledger keyed by a **durable identity** (`transcript_path`, or
`(project_root, git_branch)`), "max N injections per rolling wall-clock window
regardless of launches." Launcher READS and respects the existing ledger on
startup; the per-launch token tags rows for forensics but is NEVER the cap key.

### D: Cost ceiling — MANDATORY when armed (SB-5)

A `max_total_cost_usd` ceiling is required whenever the watchdog is armed,
enforced at the `tmux_inject` choke point AND the launcher deadman, documented as
a *lagging* ceiling (statusLine cost is debounced/nullable post-compact) to be
set conservatively. Wall-clock deadman is demoted to a backstop.

### E: Subprocess / security (single choke point)

`tmux` via fixed argument lists only, never `shell=True`; `["tmux","send-keys", "-t",pane,"-l",payload]` then `["tmux","send-keys","-t",pane,"Enter"]` with
`# nosec` documentation. A CI invariant test asserts exactly one `send-keys` site,
always `-l`, and that `paste-buffer`/`load-buffer`/`set-buffer`/`TIOCSTI`/
`shell=True` appear nowhere in the package (SB-8, security).

### F: Coexistence — `--dedicated` marker, not a one-directional flag (SB-1)

The dedicated daemon carries a `--dedicated` cmdline marker (and/or
`--socket-path`); `find_all_daemon_processes` and the enforcement kill-loop
**exclude any `--dedicated` candidate**; the dedicated daemon itself runs with
`enforce_single_daemon=false` (it is a guest; never reaps the shared daemon).
Preserves Plan 00127 exactly (same-socket stale daemons still reaped). This is a
**Plan 00127-invariant change** → gets its own focused hostile review + the
re-scoped S-ENF live survival test ("dedicated survives a shared-daemon restart
in a container") before build.

### G: Abort latency & atomic final check (Safety Finding 4)

Replace any fixed `sleep` before Enter with a capture-pane-confirm-then-Enter
closed loop; the sentinel poll interval MUST be shorter than the visible
countdown; the FULL predicate (idle template + dialog flag + loop-guard sentinel)
is re-validated in the SAME critical section immediately before the final Enter.

### H: Incremental, opt-in, hostile-review-gated

Phases ship behind opt-in flags; nothing merges to main until Phase 5's hostile
review passes. ARCH-B remains the documented escape hatch.

## Tasks

### Phase 0: Finish the live spike gates (go/no-go on the FULL architecture)

- [ ] ⬜ **0.1 (S-ENF live, SB-1)**: In a throwaway container with two throwaway
  daemons under a throwaway root, prove a `--dedicated` daemon SURVIVES a shared
  daemon restart, and the shared daemon survives the dedicated one's restart.
- [ ] ⬜ **0.2 (S-SIG desktop, SB-2)**: Capture streaming/busy, permission-dialog,
  copy-mode, and `/compact`-in-progress signatures on a real logged-in desktop;
  derive a POSITIVE whole-screen idle template + a fail-closed no-match rule.
- [ ] ⬜ **0.3 (modal enumeration, SB-2)**: Enumerate which interrupting modals
  emit NO hook event (MCP approval, trust-folder, resume picker, theme); decide
  coverage. If a meaningful class is event-invisible AND not screen-distinguishable
  → fall back to ARCH-B or shelve (explicit go/no-go).
- [ ] ⬜ **0.4 (S-CACHE, MUST)**: Confirm an injected `/compact` produces a guardable
  `PostCompact` (re-arm latch source); else define the explicit failure branch.
- [ ] ⬜ **0.5**: Lock config schema + conservative defaults (allowlist, threshold_pct,
  cooldown_seconds, max_per_window, window_seconds, max_total_cost_usd, poll_seconds,
  idle_template, idle_freshness_seconds).

### Phase 1: `tmux_inject` utility + CI tmux harness (TDD) — the foundation (SB-6, SB-8)

- [ ] ⬜ **1.1 RED** `tests/unit/utils/test_tmux_inject.py`: closed allowlist
  (reject non-member fail-closed; v1 = `{"/compact"}`; no arg group), tmux-presence
  no-op, argument-list-only (no `shell=True`), cooldown, durable cap, loop-guard
  write, `#{pane_current_command}` precondition (SB-3).
- [ ] ⬜ **1.2 GREEN** `utils/tmux_inject.py` — the ONLY `send-keys` site; `-l`
  then separate Enter; sidecar-backed state in `daemon_untracked_dir()`.
- [ ] ⬜ **1.3 CI tmux harness** `tests/integration/test_tmux_inject_harness.py`:
  spawn a real CI tmux session; RED-test allowlist, `-l` invariant,
  fail-closed-on-unknown, pane-command-mismatch. Ensure tmux is in the CI image.
- [ ] ⬜ **1.4 CI invariant test**: exactly one `send-keys` site, always `-l`; no
  `paste-buffer`/`load-buffer`/`set-buffer`/`TIOCSTI`/`shell=True` in the package.
- [ ] ⬜ **1.5** REFACTOR; 95%+ coverage on the new module.
- [ ] ⬜ **1.6** QA (`./scripts/qa/llm_qa.py all` — NOT run_all.sh); security 0.
- [ ] ⬜ **1.7** Daemon restart RUNNING; logs clean.

### Phase 2: observe-only context sidecar + positive idle template (TDD) (SB-2, SB-7)

- [ ] ⬜ **2.1 RED/GREEN** `handlers/status_line/tmux_context_sidecar.py` reading
  the Status payload as `model_context.py` does; writes `{pct,state,ts,session_id, pane,daemon_pid,seq}`; `get_default_enabled()` → False; never injects.
- [ ] ⬜ **2.2 (SB-7)** Sidecar writer authentication: dir `0700`, `O_EXCL`/no-symlink,
  daemon-PID + monotonic seq stamp; injector verifies ownership/inode + writer PID
  == recorded dedicated-daemon PID; fail-closed on mismatch. Launch token is an
  identifier, never a secret/authenticator.
- [ ] ⬜ **2.3 (SB-2)** Positive whole-screen idle template matcher (from 0.2):
  config-supplied; fail-closed; self-disabling on no-match (loudly surfaced).
- [ ] ⬜ **2.4** Event-driven dialog-open flag from PermissionRequest (the salvaged
  best idea); document lifetime/coverage holes from 0.3.
- [ ] ⬜ **2.5** QA + daemon restart verification.

### Phase 3: socket-aware coexistence — `--dedicated` (TDD) (SB-1, SB-9) — Plan 00127-invariant

- [ ] ⬜ **3.0** Focused hostile review of the enforcement change (its own doc).
- [ ] ⬜ **3.1 RED/GREEN** `--dedicated` marker on the dedicated daemon cmdline;
  `find_all_daemon_processes` + enforcement kill-loop exclude `--dedicated`
  candidates; Plan 00127 same-socket-stale reaping unchanged (regression tests).
- [ ] ⬜ **3.2** Dedicated daemon runs `enforce_single_daemon=false`.
- [ ] ⬜ **3.3 (SB-9)** CLI (`status`/`stop`/`restart`/`check`/`logs`) disambiguates
  dedicated vs shared by socket; upgrade path leaves the dedicated daemon alone;
  document the dogfooding "which daemon did I restart?" answer.
- [ ] ⬜ **3.4** S-ENF live container survival test (0.1) as an automated gate.
- [ ] ⬜ **3.5** QA + daemon restart verification.

### Phase 4: launcher + watchdog (the typist) with all rails (TDD) (SB-3,4,5 + Safety)

- [ ] ⬜ **4.1** Launcher: nested-tmux precondition (`$TMUX` set → refuse or dedicated
  `tmux -L <private-socket>`); CSPRNG token w/ dependency check (no `uuidgen`
  in-container); session dir `mkdir 0700`/fail-if-exists/no-symlink;
  startup-cleanup janitor for orphaned `untracked/tmux-sessions/<token>/`.
- [ ] ⬜ **4.2 (SB-3)** Pane-hosts-this-session rail: `#{pane_current_command} ∈ {claude,node}` HARD precondition + verify Claude's recorded child PID; RED test
  Claude-exit-to-shell → refuse.
- [ ] ⬜ **4.3 (SB-4)** Durable relaunch-stable cap key + rolling window; launcher
  reads ledger on startup. RED: inject-to-cap → kill → relaunch → still refused.
- [ ] ⬜ **4.4 (SB-5)** Mandatory `max_total_cost_usd` ceiling when armed (choke
  point + deadman); wall-clock = backstop; documented lagging.
- [ ] ⬜ **4.5 (Safety F4)** Abort: poll interval < countdown; re-validate full
  predicate in the same critical section immediately before the final Enter;
  capture-pane-confirm-then-Enter closed loop (no fixed sleep).
- [ ] ⬜ **4.6 (Safety F2)** Re-arm latch failure branch: `/compact`
  declined/failed/doesn't-drop-pct → distinct, loudly-surfaced disabled state;
  never silent wedge or busy-loop-to-cap.
- [ ] ⬜ **4.7** Watchdog runs in its OWN visible pane; dry-run default; visible
  countdown. Document the "custom lower threshold only" rationale.
- [ ] ⬜ **4.8** QA + daemon restart verification.

### Phase 5: acceptance, dogfood (feature branch), hostile-review GATE before merge

- [ ] ⬜ **5.1** Full acceptance on the feature branch; live flagship demo in a
  watched pane (over-threshold + idle + cooldown → exactly one `/compact`).
- [ ] ⬜ **5.2** Assert `auto_continue_stop` unchanged (no Stop registration).
- [ ] ⬜ **5.3** Final hostile multi-lens review of the BUILT code (not the plan).
  Merge to main ONLY on GO. NO-GO → iterate or keep on the feature/RC branch.

### Phase 6 (DEFERRED): daemon-managed watchdog spawning

- [ ] ⬜ Separate plan, behind explicit config, only after field-proving 1–5.

## Dependencies

- Builds on the status-line pipeline (`model_context.py:144–146`), `ProjectContext. daemon_untracked_dir()`, Handler `get_default_enabled()`, the daemon
  enforcement/process-verification code (Plan 00127 invariant).
- Must not regress: `auto_continue_stop.py`, the security QA gate, Plan 00127.

## Success Criteria

- [ ] Opt-in everywhere; default behaviour unchanged.
- [ ] `tmux_inject` is the ONLY `send-keys` site; CI-tmux-tested; allowlist is the
  closed set `{"/compact"}` (no arg group); fail-closed on non-members.
- [ ] No event data ever interpolated into a payload.
- [ ] `$TMUX_PANE` unset → graceful no-op (identical to today).
- [ ] Dedicated + shared daemon COEXIST (survive each other's restart) in a container.
- [ ] Idle predicate is positive + fail-closed + self-disabling; cost ceiling
  mandatory; cap durable across relaunches; abort re-validates atomically.
- [ ] `auto_continue_stop` unchanged; `run_security_check`/`llm_qa.py all` = 0/13 fail.
- [ ] 95%+ coverage; hostile-review GO before any merge to main.

## Risks & Mitigations

Carried from v1 (feedback-loop, mid-turn injection, command injection, wrong-pane,
runaway cost, Stop collision, `shell=True`, daemon-spawn blast radius) — each now
mapped to an SB resolution above. The dominant residual is SB-5 (lagging cost
ceiling) — mitigated by mandatory-when-armed + conservative default + durable cap.

## Notes & Updates

### 2026-06-23

- v2 rewrite. ARCH-A locked (spikes GREEN); ARCH-B demoted to contingency. All 9
  HOSTILE-REVIEW-2 ship-blockers mapped to concrete phases. Work proceeds on
  `feature/00135-tmux-send-keys-injection`; merge to main is gated on Phase 5's
  hostile review of the built code. v1 archived as `PLAN-v1.md`.
