# Hostile Multi-Lens Review #2 — Plan 00135 (Launcher-Controlled `send-keys` Injection)

Six independent hostile reviewers attacked the revised launcher-controlled design
(BRAINSTORM-SYNTHESIS.md) from distinct lenses: **FATAL-1 pane identity**, **FATAL-2
idle predicate**, **Safety / loop / cost**, **Security / allowlist**, **Architecture /
complexity / maintenance**, and **Product / scope / kill-shot**. This document
consolidates their verdicts honestly — de-duplicated, disagreements reconciled, strongest
objections surfaced unsoftened.

---

## 1. Consolidated verdict

**NO-GO for building this design in `src/` as written.**

The revised design is a genuine engineering advance over the version HOSTILE-REVIEW-1
blocked: the FATAL-1 pane-identity sub-problem is dissolved cleanly, and the cap is now
persisted (closing review #1's in-memory restart blocker). Every lens credits the
observe-only daemon separation, the single choke point, the persisted token-keyed cap,
the event-driven "dialog open" flag, and the dry-run-first posture as sound.

But four lenses independently land SHIP-BLOCKER, and the two non-FATAL lenses still find
unbounded-cost and mis-injection holes. Critically, the **new design re-opens a different
guaranteed-fatal interaction (mutual daemon reaping under the project's own default
container config)** while declaring the pane problem solved — so FATAL-1 is only *half*
closed. The product lens's question from review #1 — *should this exist in this library?*
— was deferred, not answered, and the answer on the technical merits is the same: not here.

### Per-lens verdict table

| Lens                              | Verdict                           | Core objection                                                                                    |
| --------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------------- |
| FATAL-1 — pane identity           | **SHIP-BLOCKER**                  | Pane sub-claim closed; but shared daemon reaps dedicated daemon (same root)                       |
| FATAL-2 — idle predicate          | **SHIP-BLOCKER**                  | "Is the user typing" rests on `client_activity` (likely redraw); negative-match scrape fails OPEN |
| Safety / loop / cost              | **MAJOR** (2 blocker-grade holes) | Relaunch mints fresh cap; cost ceiling optional + lagging under clock-only deadman                |
| Security / allowlist              | **MAJOR** (2 blocker-grade holes) | Regex gates syntax not destructiveness; sidecar writer unauthenticated                            |
| Architecture / complexity / maint | **SHIP-BLOCKER**                  | Second daemon launch mode forks the lifecycle matrix; injector untested by own gates              |
| Product / scope / kill-shot       | **DO-NOT-BUILD**                  | First-party-obsolescence risk vs sole surviving capability; brand inversion                       |

Reconciled overall: **NO-GO in this repository**, with a **CONDITIONAL path to a different
shape** (companion script + observe-only sidecar; see §6).

---

## 2. Did the new design fix HOSTILE-REVIEW-1's two FATAL flaws?

### FATAL-1 (`$TMUX_PANE` lost at the daemon boundary) — **PARTIAL. Not truly closed.**

- **The pane-identity sub-claim IS closed by construction.** All lenses agree: passing
  `#{pane_id}` as *birth-time data* into the dedicated daemon's frozen `os.environ` inverts
  the frozen-environ problem from a defect into an advantage, because a 1:1 session⇄daemon
  mapping has exactly one correct answer for its whole lifetime. Spike S-PANE will pass.
- **But FATAL-1's full resolution depends on §4's enforcement-coexistence claim, and that
  is broken.** (FATAL-1 lens, Finding 1; corroborated by Architecture Finding 1, Security
  "load-bearing caveat correct," Product "did its homework.") `enforce_single_daemon` matches
  peers on **project root only** (via `--project-root` flag OR venv-interpreter path), never
  socket path; the Plan 00127 spare logic only spares the live owner of *the restarting
  start's own socket*. The dedicated daemon shares `/workspace` root but owns a *different*
  socket, so it is **not spared**.
- **Condition under which FATAL-1 reopens (essentially the default case):** (1) the user also
  runs the normal shared daemon for the same project root — the documented default for
  *everyone* — AND (2) any shared-daemon **restart** occurs while a dedicated session is live
  (constant in this repo's own dogfooding workflow), (3) in a container where
  `enforce_single_daemon_process` is auto-enabled. On the shared daemon's restart, its
  liveness reuse gate falls through (its own socket is NOT_LIVE during a restart) to
  enforcement, which finds the dedicated daemon by root and **SIGTERM/SIGKILLs it mid-session**.
- **Why the stated mitigation fails:** §4's `--no-enforce-single` flag is *one-directional* —
  it stops the *dedicated* daemon from killing others; it does nothing to stop the
  enforcement-enabled *shared* daemon from killing the dedicated one. Option B (synthetic
  `--project-root`) is worse: the venv-interpreter fallback (`_root_from_interpreter`) still
  resolves `/workspace`, so the synthetic flag does not even reliably change the matched root.
- **Spike trap:** S-ENF as written ("confirm enforcement keys on project root only") will
  *pass* — and its success *confirms the design is broken*. The spike's green is the design's red.

### FATAL-2 (idle detection has no reliable signal) — **PARTIAL → effectively NO for "is the user typing".**

- **Improved, genuinely.** The composite (copy-mode, vim insert, shelled-out command, idle
  latch from a clean 1:1 event stream) is real progress, and signals 1, 2, 5 are VERIFIED and
  sound. The event-driven "dialog open" flag is the single best idea in the design.
- **But the user's literal question — "is the user typing right now?" — has no reliable
  answer.** (FATAL-2 Findings 1–4; Product Finding 4; Architecture Finding 4.)
  - Signal 3 (`#{client_activity}`) is assessed >70% likely to measure *terminal redraw
    traffic*, not keystrokes — tmux bumps client activity on server→client output flushes, and
    Claude's streaming TUI redraws continuously. If S-ACT fails, signal 3 collapses and there is
    **no residual positive human-keystroke signal** (S-TX detects *Claude*, not the human).
  - Signal 7's negative-match scrape **fails OPEN, not closed**, on an unrecognised modal: a new
    TUI element rendered *above* an empty input box matches the positive "empty box" signature
    and is absent from the negative list, so the predicate reports IDLE and injects into a live
    modal. You cannot fail-closed on "unknown busy-state" with a *negative* match list.
  - The `PermissionRequest` event flag does not cover the dialog's full on-screen lifetime
    (teardown/redraw race) and does not cover non-permission modals (MCP approval, trust-folder,
    resume picker, theme) that emit no hook event.
- **Condition under which FATAL-2 reopens:** S-ACT fails (likely) → "don't type while the
  human types" guarantee is gone; OR Claude Code ships any new modal/TUI element not in the
  signature list → fail-open mis-inject. The composite is a probabilistic risk-reducer dressed
  as a fail-closed gate.

**Net:** Neither FATAL is *truly* closed. FATAL-1 is structurally reopened by enforcement;
FATAL-2 is downgraded to "less likely" but not "prevented."

---

## 3. Remaining SHIP-BLOCKERS (concrete, with required fix/spike)

**SB-1 — Mutual daemon reaping (FATAL-1 Finding 1; Architecture Finding 1).**
The shared daemon reaps the dedicated daemon on its next restart under the default container
config. *Required fix:* not closable by a flag on the dedicated daemon. Either (a) run the
dedicated daemon under a *genuinely distinct project root* that BOTH enforcement resolution
paths (flag AND venv-interpreter) attribute differently — i.e. a separate venv/interpreter, a
real cost; or (b) teach `enforce_single_daemon` / `find_all_daemon_processes` socket-aware
identity (a Plan 00127-invariant change needing its own hostile review); or (c) a daemon-honoured
"do-not-reap" registration. *Spike:* S-ENF must be re-scoped to prove the dedicated daemon
*survives a shared-daemon restart in a container*, not merely to confirm root-only matching.

**SB-2 — "Is the user typing" has no reliable signal (FATAL-2 Findings 1–2).**
`client_activity` likely measures redraw; the negative-match scrape fails open. *Required fix:*
run S-ACT *first*; pre-commit in writing to the failure branch. If `client_activity` bumps on
redraw, the only sound answers are ARCH-B (PTY supervisor sees raw input bytes) or dropping the
human-typing guarantee and gating on Claude-idle + *positive whole-screen idle template* +
cap. Redesign signal 7 as a positive whole-screen idle assertion (entire captured region
matches a known-idle template modulo cursor), not a bottom-region empty-box + blocklist.

**SB-3 — Pane-pid match proves the wrong thing (FATAL-1 Finding 3).**
`#{pane_pid}` is the pane's *shell* pid; it is UNCHANGED when Claude exits to a shell, so the
hosts-this-session rail produces false MATCHES and types into a bare shell (or a different
reclaimed program). *Required fix:* the rail must verify the *foreground process is Claude* —
require `#{pane_current_command}` ∈ {claude,node} as a hard precondition of the rail (not a soft
idle signal), and record/verify Claude's actual child PID at launch. Spike against Claude
exit-to-shell explicitly.

**SB-4 — Relaunch mints a fresh cap → unbounded across relaunches (Safety Finding 1).**
The cap is keyed by per-launch UUID; N relaunches = N×cap, defeatable by any re-exec wrapper
(`/loop`, a crashy supervisor). HOSTILE-REVIEW-1's "restart re-arms the loop" blocker was moved
one layer up, not closed. *Required fix:* key the persisted ledger by a **durable, relaunch-stable
identity with a rolling wall-clock window** (e.g. `(project_root, git_branch)` or
`transcript_path`, "max N injections per rolling window regardless of launches"); the launcher
must READ and respect the existing ledger on startup. Launch token may tag rows for forensics
but must NOT be the cap key. RED test: "inject to cap → kill launcher → relaunch → still refused."

**SB-5 — No mandatory cost ceiling; the mandatory terminator bounds the wrong axis (Safety Finding 3).**
The wall-clock deadman is mandatory but axis-blind; the `cost.total_cost_usd` ceiling is
*optional* and *lagging* (statusLine is debounced ~300ms, stalest during the heaviest turn, and
`current_usage` goes null post-compact). A doc-compliant armed session can burn arbitrary dollars
under a bounded clock. *Required fix:* make a `max_total_cost_usd` ceiling **mandatory** whenever
armed, enforced at the injector choke point AND the launcher deadman; document it as a *lagging*
ceiling to be set conservatively; keep wall-clock as a backstop, not the primary.

**SB-6 — Allowlist regex gates syntax, not destructiveness (Security Finding 1).**
The regex `^/[a-z][a-z0-9_:-]*( [^\n\r\x00-\x1f]*)?$` admits `/clear`, `/quit`, `/exit`,
`/deploy-prod --force`, and arbitrary custom project slash commands (which can shell out). The
"RCE-via-PR-mutable-config" defence collapses to "trust whoever edits the config." *Required fix:*
config-load validator must enforce a **closed semantic allowlist** (v1: literally `{"/compact"}`),
not an open regex; keep the regex only as a secondary shape check; reject custom/project slash
commands by default. **Forbid the argument group entirely for v1** (bare commands only) — the
`( [^\n\r\x00-\x1f]*)?` group smuggles attacker-influenced text into a future arg-taking command.

**SB-7 — Sidecar writer is unauthenticated (Security Finding 2).**
The injector trusts `pct`, idle-latch, and the dialog-open flag from a sidecar at a token-derived
path under world-traversable `untracked/`. The token is in `os.environ`, readable by any same-uid
process via `/proc/<pid>/environ` (exactly how S-PANE reads it) — so the path is not a secret. Any
same-uid writer forges `pct=99, idle, dialog_open=false` → predicate passes → types `/compact`.
*Required fix:* sidecar dir `0700`, created `O_EXCL`/no-symlink; injector verifies sidecar
ownership/inode and that the writer PID == recorded dedicated-daemon PID (cross-check
`CLAUDE_HOOKS_PID_PATH`); treat the sidecar as integrity-sensitive (daemon-PID + monotonic
sequence stamp, fail-closed on mismatch). *Spike:* amend S-PANE — its success proves the token is
NOT a secret, so token-as-authenticator must be abandoned.

**SB-8 — The injector ships untested by the project's own gates (Architecture Finding 2).**
The only component that types — with RCE/wrong-pane blast radius — depends entirely on tmux
primitives absent from the dev container, so the 95%/13-check/H-1 machinery cannot exercise it.
A one-time host spike is not a regression test. *Required fix:* a CI-runnable tmux harness (tmux
*is* installable in CI; the design never tests this) that RED-tests the allowlist, the `-l`
invariant, fail-closed-on-unknown, and pane-pid-mismatch against a *real* CI-spawned tmux session.
If tmux cannot be made CI-available, the injector cannot meet the project bar and belongs outside
`src/` (companion repo / `examples/`).

**SB-9 — Second daemon launch mode forks the lifecycle matrix (Architecture Finding 1).**
`start --no-enforce-single` is not "one flag" — it creates a second daemon identity that every
CLI command (`status`/`stop`/`restart`/`check`/`logs`), the install/upgrade path, startup_cleanup,
and the dogfooding "restart after every change" workflow must now disambiguate by socket, not
root. The dogfooding stale-code failure mode becomes structurally guaranteed (a developer
restarts the *shared* daemon; the dedicated one runs stale). *Required fix:* expand S-ENF to prove
CLI commands disambiguate dedicated vs shared by socket path, that upgrades don't break the
dedicated daemon, and document the "which daemon" answer for dogfooding restarts.

---

## 4. The Phase-0 spike gate — make-or-break and fallbacks

| Spike       | Make-or-break?                                          | If it FAILS, design must fall back to…                                                                                                                                                                                                                                                                                                                           |
| ----------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **S-ACT**   | **YES — architecture-selection event, not a demotion.** | If `client_activity` bumps on redraw: the human-typing guarantee cannot be met by ARCH-A. Fall back to **ARCH-B** (PTY supervisor) **or drop the "don't type while you type" guarantee** and gate on Claude-idle + positive whole-screen template + cap. Do NOT "lean on S-TX" — S-TX detects Claude, not the human. >70% assessed to fail.                      |
| **S-SIG**   | **YES.**                                                | Redesign signal 7 as a **positive whole-screen idle template**, not negative-match-blocklist (the blocklist fails OPEN). If even that is too version-fragile, fall back to **cap+cooldown-only, fail-closed on any non-empty prompt** — and accept the dialog-safety load shifts entirely to the event flag (which has lifetime/coverage holes, SB-2/Finding 3). |
| **S-ENF**   | **YES — but re-scoped.**                                | Must prove the dedicated daemon SURVIVES a shared-daemon restart in a container (SB-1), not merely that matching is root-only (that confirms breakage). If it cannot survive: separate venv/root, or socket-aware enforcement (own review), or do-not-reap registry. No survival → no build.                                                                     |
| **S-PANE**  | YES (cheap), but DOUBLE-EDGED.                          | Will pass (env reaches `/proc/<pid>/environ`). Its success PROVES the launch token is readable by any same-uid process → derive the requirement that the token is an *identifier, never a secret/authenticator* (SB-7).                                                                                                                                          |
| **S-CACHE** | Promote SHOULD→**MUST** (Safety Finding 2).             | If `/compact` produces no guardable `PostCompact` for an *injected* compact, the re-arm latch has only the fragile `pct`-drop heuristic; the failure branch (SB below) becomes the primary control path.                                                                                                                                                         |
| **S-TX**    | SHOULD.                                                 | Corroboration only; cannot substitute for a human-keystroke signal.                                                                                                                                                                                                                                                                                              |
| **S-ENTER** | SHOULD.                                                 | Replace `sleep 0.3` with capture-pane-confirm-then-Enter closed loop; re-validate predicate in the same critical section as the final Enter (Safety Finding 4).                                                                                                                                                                                                  |

**Additional mandatory spike (new):** instrument `PermissionRequest`/`Notification` timing vs
real dialog render/teardown, AND enumerate which interrupting modals emit NO event (FATAL-2
Finding 3). If a meaningful class of modals is event-invisible and not positively
screen-distinguishable, the dialog-safety guarantee fails.

**Phase-0 must be a go/no-go on the FULL architecture, not just the injector (Architecture
Finding 4).** Explicit decision rule: *if S-ACT fails AND S-TX is not Tier-1, the
dedicated-daemon + sidecar edifice is not justified over the standalone-script floor — fall back
to the companion-script shape.* Otherwise the full complexity is committed against an unproven payoff.

---

## 5. Weakest rail / biggest residual risk

**Two rails permit genuinely UNBOUNDED outcomes; both are on the spend/mis-injection axis.**

1. **Cost ceiling (SB-5) — weakest rail, permits unbounded SPEND.** It is the only rail tracking
   the actual harm axis (money), and it is optional, lagging, and stale precisely during a
   runaway, while the mandatory terminator (wall-clock) is axis-blind. The deadman + cap give an
   *illusion* of a bound; neither bounds dollars. Compounded by SB-4 (per-launch cap × relaunch).

2. **The "is the user typing" / dialog gate (SB-2, FATAL-2) — permits MIS-INJECTION into a
   human's input or a live modal.** The guarantee rests on a signal that likely measures redraw
   and a negative-match scrape that fails open on any unrecognised modal. Combined with SB-3
   (types into a bare shell after Claude exits) and SB-7 (a forged sidecar reads as a positive
   all-clear, not "unknown"), the fail-closed framing is not actually fail-closed at the points
   that matter.

Ranked weakest→strongest: (1) cost ceiling, (2) per-launch cap, (3) re-arm latch (wedges or
busy-loops-to-cap when `/compact` is declined/fails/doesn't drop pct — Safety Finding 2; needs an
explicit, loudly-surfaced failure branch), (4) idle/dialog predicate, (5) abort latency (Safety
Finding 4: sentinel poll interval unspecified and likely longer than the ~3s countdown; re-check
sentinel + `client_activity` in the same critical section immediately before the final Enter),
(6) ledger loop-guard (Safety Finding 5: written but no *reader* specified — inert for v1, but the
PostCompact-reorient roadmap item must be gated on a defined ledger reader).

---

## 6. Product recommendation

**Reconciling the product kill-shot with the technical lenses: DO-NOT-BUILD in this repository;
the only defensible path is BUILD-DIFFERENT-SHAPE outside `src/`.**

The product lens (DO-NOT-BUILD) and the architecture lens (recommend the standalone-script shape)
converge with the FATAL lenses' structural blockers. The decisive product facts, uncontested by
the technical lenses:

- **First-party obsolescence vs sole surviving capability (Product Finding 1).** The design's only
  residual justification is custom-threshold `/compact` in a watched TUI. Anthropic has already
  shipped the server-side compaction primitive (`compact-2026-01-12` beta) and ships the CLI; a
  configurable CLI threshold is the obvious next step. "Be willing to shelve" is not a cheap,
  reversible bet against the eight new long-lived surfaces (Architecture Finding 6) this design
  adds.
- **Brand inversion is made worse, not better, by `src/` placement (Product Finding 2).** "The
  daemon is observe-only" is invisible to a user: the *installer* and the *repo* are the brand,
  and they would ship a typist. A single "the safety daemon typed into my terminal" story costs
  more adoption than the niche wins. Review #1's explicit recommendation to keep the injector OUT
  of `src/` was reversed by assertion, not argument.
- **Activation cost shrinks the audience to a rounding error (Product Finding 3):** install tmux,
  abandon the normal launch path, accept a two-pane layout, *watch* the second pane, and run
  host-only-untested fragility in production — all to compact at 50% instead of the native default.
- **The catalogue collapsed to one capability + one roadmap item (Product Finding 5)** — itself the
  signal that the general mechanism isn't needed, only a special case that is the most likely to be
  obsoleted.

**Recommended shape (the minimal salvage, endorsed by Architecture's "radically simpler" and
Product's fork (b)):**

- Ship **nothing that types in `src/`** and **nothing deployed by the daemon installer**.
- Salvage the two genuinely daemon-appropriate, brand-consistent pieces as a normal observe-only
  handler writing a sidecar (NO new launch mode, NO `--no-enforce-single`, NO env-minting): the
  **observe-only `pct` observation** and the **event-driven dialog-open flag**.
- Ship the typist as the research-note `watch-compact.sh` (~20 lines) in a **separate companion
  repo or `examples/`**, user-cloned and user-launched in its own visible pane, allowlist
  hard-coded to `/compact`, with the durable-keyed persisted cap (SB-4 fix) and dry-run default.
- Build the full launcher+dedicated-daemon edifice **only if** Phase-0 proves S-ACT *positively
  viable* (making "is the user typing" a real positive signal the standalone floor cannot achieve)
  AND a demand spike + market-timing spike (Product Findings 1, 3) both clear. Absent that proof,
  prefer **ARCH-B** (PTY supervisor) in the companion repo — it is the only design where both
  FATALs dissolve by construction (Product Finding 4: choosing the fragile ARCH-A for the one
  feature whose entire risk is mis-injection is the wrong trade).

---

## 7. Required changes to BRAINSTORM-SYNTHESIS.md before it is a buildable PLAN

01. **§4 enforcement caveat is wrong, not merely "load-bearing."** Rewrite to state the dedicated
    daemon is reaped by the shared daemon on restart (SB-1). Replace the `--no-enforce-single`
    "one flag" mitigation with one of: distinct venv/root, socket-aware enforcement (flagged as a
    Plan 00127-invariant change requiring its own review), or a do-not-reap registry. Re-scope
    S-ENF to "dedicated daemon survives shared-daemon restart in a container."
02. **§3 must pre-commit to the S-ACT failure branch in writing** (SB-2): name ARCH-B-or-drop-the-
    guarantee as the consequence, and stop framing redraw-failure as a "demotion."
03. **Redesign signal 7** from negative-match-blocklist to a **positive whole-screen idle template**
    (it currently fails OPEN); state explicitly that the dialog event flag has lifetime/coverage holes.
04. **§2/§4 hosts-this-session rail** must require `#{pane_current_command}` ∈ {claude,node} as a
    *hard* precondition and verify Claude's child PID — `#{pane_pid}` alone is insufficient (SB-3).
05. **§4 cap key** must change from per-launch token to a durable relaunch-stable identity with a
    rolling window; launcher reads existing ledger on startup (SB-4). Add the RED test.
06. **§4 cost ceiling** must become **mandatory** (not optional) when armed, documented as lagging;
    wall-clock demoted to backstop (SB-5).
07. **§4 allowlist** must become a closed semantic set (`{"/compact"}`), regex secondary only;
    forbid the argument group for v1; reject custom slash commands (SB-6).
08. **§1/§3/§4 sidecar** must specify writer authentication (`0700`/`O_EXCL`/no-symlink, PID +
    sequence stamp, fail-closed on mismatch); add the requirement that the launch token is an
    identifier, never a secret (SB-7).
09. **§4 re-arm latch** must specify an explicit failure branch (compact declined/failed/doesn't
    drop pct → distinct, loudly-surfaced disabled state; never silent wedge or busy-loop-to-cap).
    Promote S-CACHE to MUST.
10. **§4 abort** must specify a sentinel poll interval shorter than the countdown and re-validate
    the full predicate (sentinel + `client_activity`) in the same critical section as the final Enter.
11. **§4 ledger** must define the *reader* and its predicate (global cross-command budget over a
    window; alternation detection) before the PostCompact-reorient roadmap item; state plainly the
    ledger is forensic-only for v1.
12. **§5/§7** must add: a launcher precondition for nested tmux (`$TMUX` already set → refuse or use
    a dedicated `tmux -L <private-socket>` server — FATAL-1 Finding 4); a CSPRNG token source with a
    dependency check (`uuidgen` is absent in-container — Security Finding 4); session-dir creation
    with `mkdir 0700`/fail-if-exists/no-symlink; a startup-cleanup janitor for orphaned
    `untracked/tmux-sessions/<token>/` (re-introduces the orphan path Plan 00127 deliberately
    removed — Architecture Finding 5); and a CI invariant test that exactly one `tmux send-keys`
    site exists, always with `-l`, and that `paste-buffer`/`load-buffer`/`set-buffer`/`TIOCSTI`/
    `shell=True` appear nowhere in the package (Security Finding 5; Architecture Finding 2).
13. **§5/§6 placement** must move the typist OUT of `src/` and OUT of the installer (Product
    Findings 2, 5), and add a market-timing spike + demand spike as Phase-0 go/no-go gates
    (Product Findings 1, 3).
14. **§7 Phase-0** must become a go/no-go on the FULL architecture with the explicit fallback rule:
    if S-ACT fails and S-TX is not Tier-1, fall back to the companion-script shape rather than
    building the launcher+dedicated-daemon (Architecture Finding 4).

---

## What the reviewers agreed is GENUINELY SOUND (keep)

Pane id as birth-time data via 1:1 frozen environ (the FATAL-1 sub-claim — elegant, correct);
daemon stays strictly observe-only and is never the `send-keys` caller (right architectural seam,
preserves the brand boundary); routing hooks via `CLAUDE_HOOKS_SOCKET_PATH` with zero wrapper
edits; the event-driven dialog-open flag (best idea in §3 — salvage it); persisted token-keyed cap
with flock + `os.replace` (closes review #1's in-memory blocker — the flaw is the *key*, not the
persistence); ledger written BEFORE the send (correct crash-ordering); deadman OUTSIDE the loop
(right *location* — wrong *trigger axis*); dry-run-first default + visible countdown + `/compact`-
only allowlist; cutting four of six use cases; ARCH-E documented as the safe-but-different escape
hatch.
