# Hostile Multi-Lens Review #1 — Plan 00135 (Event-Driven `send-keys` Injection)

Five independent Opus reviewers attacked the plan from distinct adversarial
lenses: **Safety/feedback-loop**, **Security/injection**, **Architecture/
reliability**, **Product/appropriateness**, **Mechanics/correctness**. This
document synthesises their verdicts. The reviewers agreed far more than they
disagreed.

## Consolidated verdict

**DO NOT BUILD THE FLAGSHIP AS PLANNED.** The plan's *safety rails* (opt-in,
allowlist, no event-data interpolation, TIOCSTI ban, subprocess arg-lists,
single choke point, Pattern B) are genuinely well-designed and praised by
multiple lenses. But the plan rests on **two independently fatal architectural
assumptions that are provably false**, plus a product-identity problem, plus
several injection/safety gaps. Net: **re-architect around a pane-resident
producer and ship only a narrow, observe-only-in-daemon + user-launched-script
subset — or reconsider shipping in this library at all.**

| Lens                       | Verdict                                                                 |
| -------------------------- | ----------------------------------------------------------------------- |
| Architecture / reliability | **SHIP-BLOCKER** ($TMUX_PANE lost at daemon boundary)                   |
| Mechanics / correctness    | **SHIP-BLOCKER for Phase 2** (idle signal does not exist)               |
| Safety / feedback-loop     | **SHIP-BLOCKER** (cap defeated by restart; flagship not loop-guardable) |
| Security / injection       | **MAJOR** (allowlist gates membership, not content — fixable)           |
| Product / appropriateness  | **SHIP-NARROW-SUBSET** (brand inversion; cut P1-in-src, P3, P4)         |

## The two fatal architectural flaws (must resolve before any build)

### FATAL-1 — `$TMUX_PANE` is LOST at the daemon boundary (Architecture lens, definitive, evidenced)

The plan's spine — "the daemon already gets the statusLine payload, so a daemon
*handler* writes the sidecar including the target `pane`" — is **impossible**:

- The bash hook wrapper (`.claude/hooks/status-line`) forwards **JSON only** over
  an `AF_UNIX` socket (`send_request_stdin` in `init.sh`). **Environment
  variables do not cross a socket.** `$TMUX_PANE` never reaches the daemon.
- The daemon is a **long-lived, terminal-detached process** forked once
  (`os.fork`/`os.setsid`/`chdir("/")`, `cli.py:392–446`). Its `os.environ` is
  frozen at first-start, belonging to whatever shell first launched it — not the
  pane sending the current event.
- There is **exactly one daemon shared across all panes/sessions** for the
  project (CLAUDE.md "Parallel sessions share one daemon", Plan 00127; verified
  live: a single daemon PID). Even reading the daemon's own `$TMUX_PANE` would
  give one stale value, wrong for N−1 of N sessions.
- The Status payload (and documented statusLine schema, research-note §5) carries
  **no pane/tty field** (verified: no `TMUX`/`pane`/`tty` in any status fixture).

**Consequence:** `TmuxContextSidecarHandler` cannot write a correct `pane`, so the
watchdog cannot self-target. The research note's *original* `~/.claude/ statusline.sh` did NOT have this bug — it runs as a direct child of Claude Code
in the live pane and inherits `$TMUX_PANE`. The plan's "improvement" of moving
sidecar-writing into a daemon handler **discarded the one process that had pane
identity.** Phase 0 Task 0.1 ("confirm `$TMUX_PANE` in a hook subprocess") would
pass in the *wrapper* and then mislead — the var is gone by the time the *handler*
runs.

**Required:** pane discovery + the authoritative idle/pane state MUST live in a
**pane-resident process keyed by `session_id`** (a thin shim that injects
`$TMUX_PANE` into the JSON as *data*, or the watchdog itself launched in the
session's context). The daemon may write `pct` as a passive observation; it
cannot own `pane`.

### FATAL-2 — Idle detection has no reliable signal (Mechanics lens, SHIP-BLOCKER for Phase 2)

Idle-gating is the linchpin preventing mid-turn mis-injection — and **the signal
it depends on does not exist**:

- The statusLine payload has **no idle/busy field**. It fires only at message
  boundaries, debounced ~300ms, **cancelled if superseded** (§5). So a daemon
  handler cannot synthesise a trustworthy `busy` flag.
- That leaves the "crude `capture-pane` fallback" as the *only* signal — which
  **misreads catastrophically**: a permission prompt (inject `/compact` → selects
  a garbled menu answer), vim mode, a user's half-typed multi-line prompt
  (inject appends + submits Frankenstein line), a spinner gap, `/compact`'s own
  progress UI, a running subagent.
- Cooldown/cap limit blast radius but **none of them prevent a single mid-turn or
  into-a-dialog mis-injection** — exactly the "opposite effect" the user feared.

**Required (mandatory Phase 0 spike before Phase 2):** empirically determine the
most reliable idle signal — tmux pane flags (`#{pane_in_mode}`,
`#{pane_current_command}`, `#{client_activity}`), a prompt-box signature with an
explicit **negative** match list for permission/vim/streaming states — and
**fail-closed: if idle cannot be positively confirmed, do not inject.**

## Safety blockers (Feedback-loop lens)

- **BLOCKER: per-session cap defeated by restart.** "Session" is undefined; the
  only in-repo counter precedent (`critical_thinking_advisory._last_fired_count`)
  is **in-memory and resets on every daemon restart** — and this project restarts
  the daemon constantly. A watchdog/daemon restart re-arms the loop → unbounded
  unattended token spend. Cap MUST be **persisted, keyed by Claude `session_id`,
  epoch-based**, surviving daemon/watchdog restart and pane reuse, with a RED test
  ("inject to cap → restart → still refused").
- **BLOCKER: the flagship `/compact` may not be loop-guardable.** The loop-guard
  sentinel rides on `UserPromptSubmit` carrying prompt text — but `/compact` is a
  slash command intercepted by Claude Code and may never surface a
  sentinel-checkable event. The `compact → PostCompact re-orient → context grows → compact` cross-injection cycle is not broken by a per-payload sentinel. Verify
  the flagship produces a guardable event; otherwise cap+cooldown are the ONLY
  protection (so FATAL/cap hardening is doubly load-bearing).
- **MAJOR: `auto_continue_stop` × watchdog compose into perpetual motion.** Stop
  is suppressed (keep working) AND context auto-compacts (never blocked) → no
  natural termination. Needs a global unattended-session budget (turns/wall-clock)
  independent of the compact cap.
- **MAJOR: multi-session shared daemon corrupts the sidecar / wrong pane.**
  Sidecar must be per-`session_id`, atomic-write (`os.replace`), flock'd
  cap/cooldown record; watchdog evaluates per session_id and verifies the target
  pane still hosts that live session before each injection.

## Security gaps (Injection lens — all fixable, but mandatory before Phase 1)

The exact-payload allowlist + no-interpolation is the right spine, BUT:

1. **Allowlist gates membership, not content** → a malicious/social-engineered
   `.claude/hooks-daemon.yaml` entry (team-shared, PR-mutable) is **RCE on
   checkout-and-run**. Constrain entries to **slash-commands only**
   (`^/[a-z][a-z0-9_-]*( .*)?$`), validated fail-closed at config load.
2. **Embedded newline/control char** in an entry smuggles a second submitted
   command. Reject any payload containing `\n`/`\r`/control chars.
3. **`paste-buffer`/`load-buffer`/`set-buffer` are an un-banned non-`-l`
   channel.** Explicitly forbid them (like TIOCSTI); the only permitted tmux verbs
   are `send-keys -l <payload>`, `send-keys Enter`, and read-only `capture-pane`.
4. **`-l` invariant is convention, not enforced.** Test that the payload is ALWAYS
   sent with `-l` and the only non-`-l` send is the literal token `Enter`.
5. **Schema-validate the new config block** at the boundary (CLAUDE.md standard).

## Mechanics gaps (Correctness lens)

- **`sleep 0.3` then Enter is fragile** (TUI input-debounce dependent, silent
  partial-submit under load). Use bracketed-paste-buffer + Enter, or
  capture-pane-confirm-then-Enter (closed loop). Spike the timing in Phase 0.
- **statusLine staleness blind spot:** debounce+cancel means `pct` is stalest
  *during the heavy turn that grows context fastest* — the custom threshold is
  only a *between-turn* approximation. Treat stale `pct` as **unknown, not safe.**
- **`used_percentage` is input-only and `null` post-compact** → coerce null→0
  (matches `model_context.py:145`), document "input-side %", never fire on null.
- **Post-compact re-fire:** arm a "expect pct to drop" latch (require a fresh
  statusLine sample below threshold before re-firing); cooldown floor must exceed
  worst-case compaction + statusLine-refresh latency.

## Product verdict (Appropriateness lens) — SHIP-NARROW-SUBSET

- **Brand inversion:** this library's identity is *blocking dangerous things*. A
  daemon component that *types commands into your session* is the literal inverse;
  context.md admits it "turns the daemon from a guardrail library into a
  self-driving-session platform." A single viral "the safety daemon took over my
  terminal" story costs more adoption than the feature wins.
- **~80% reinvents native features** (auto-compact, headless, `/loop`, API
  compaction). The ONLY genuine gap is "custom *lower* `/compact` threshold while
  keeping the visible TUI."
- **Asymmetric blast radius:** upside is mild/niche; downside is "it ran away /
  wrong pane / surprise compact," all attributed to "the hooks daemon."

**Recommended cut, endorsed by the synthesis:**

- **Daemon side (observe-only):** at most a passive context-`pct` observation. The
  daemon **never calls `send-keys`.**
- **The typing half:** a standalone `watch-compact.sh` the **user launches in its
  own visible tmux pane**, allowlist hard-coded to `/compact` for v1, carrying all
  rails, with the persisted session-keyed cap. Ship it in `examples/` or a
  companion repo — **not `src/`** (no keystroke primitive inside the safety
  daemon).
- **Cut `tmux_inject` from `src/`; cut P3 (event-driven enqueue handlers — each
  duplicates a native mechanism); cut P4 (daemon-spawned typing) permanently.**

But note FATAL-1 still bites the narrow subset: even the observe-only sidecar
cannot supply the `pane` from the daemon — the pane must come from a pane-resident
producer keyed by `session_id`.

## Recommended decision

1. **Do not proceed to build on the current PLAN.** It is blocked by FATAL-1 and
   FATAL-2 and carries a brand risk the user explicitly flagged.
2. **Decision required from the user** (these are genuine forks):
   - **(a) Re-architect** around a pane-resident producer + user-launched
     standalone watchdog, observe-only in the daemon, `/compact`-only v1 — then
     re-review; **or**
   - **(b) Ship as a separate companion repo/script**, keeping the daemon a pure
     guardrail (Product lens's preferred outcome); **or**
   - **(c) Shelve** — accept native auto-compact and drop the feature.
3. If proceeding (a/b): rewrite PLAN.md with a **Phase 0 spike gate** (idle
   signal + pane discovery + Enter timing) that MUST pass before any injector is
   built, and fold in every Security/Safety required-fix above as RED-tested
   invariants at the single choke point.

## What the reviewers agreed is GOOD (keep)

opt-in `get_default_enabled()→False`; exact-payload allowlist + no event-data
interpolation; TIOCSTI ban; subprocess argument-lists (no `shell=True`); single
choke point; `daemon_untracked_dir()` not `/tmp`; Pattern B over Pattern A; not
registering on Stop (leaving `auto_continue_stop` untouched).
