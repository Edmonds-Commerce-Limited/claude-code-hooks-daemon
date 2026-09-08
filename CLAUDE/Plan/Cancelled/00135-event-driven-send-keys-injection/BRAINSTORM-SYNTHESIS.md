# Brainstorm Synthesis — Plan 00135: Launcher-Controlled `send-keys` Injection

**Status:** Design proposal (consolidates six brainstorm angles + HOSTILE-REVIEW-1).
**Supersedes:** the daemon-handler injection design that HOSTILE-REVIEW-1 declared blocked.
**Core reframe:** stop routing injection through the shared, terminal-detached daemon.
Ship a **launcher** that owns the tmux session, captures pane identity at spawn, and
gives this session its **own dedicated daemon** (observe-only) plus a **single visible
injector** that types. This inverts the topology that made both FATAL flaws fatal.

---

## 1. Recommended architecture

**One launcher → one tmux session → one dedicated daemon → one Claude pane → one
observable injector.** The launcher (`scripts/claude-tmux.sh`, tracked in this repo,
deployed by the installer like `mkplan.bash`) is the new artifact. It does, in order:

1. **Build the observable layout.** `tmux new-session -d`, then split into two panes:
   `%CLAUDE` (the real Claude Code TUI the human types into) and `%WATCH` (the injector
   loop, visible, killable). Capture the Claude pane's stable id at spawn:
   `PANE=$(tmux new-window -P -F '#{pane_id}' ...)` → a `%N` id that survives layout
   changes/renames (never `session:window.pane`).

2. **Allocate per-session daemon runtime paths** under
   `untracked/tmux-sessions/<launch-token>/` and export the three documented override
   env vars: `CLAUDE_HOOKS_SOCKET_PATH`, `CLAUDE_HOOKS_PID_PATH`, `CLAUDE_HOOKS_LOG_PATH`.
   This gives the session its **own isolated daemon** that does not share the project's
   shared daemon socket. (CLAUDE.md documents exactly this isolation escape hatch.)

3. **Mint and export session identity as data:** `CLAUDE_HOOKS_TARGET_PANE=$PANE`,
   `CLAUDE_HOOKS_LAUNCH_TOKEN=$(uuidgen)`, `CLAUDE_HOOKS_LAUNCH_EPOCH=$EPOCHSECONDS`,
   `CLAUDE_HOOKS_DEDICATED=1`. These land in the env that the dedicated daemon, the
   Claude process, and the injector all inherit.

4. **Start the dedicated daemon explicitly** (not lazily via a hook) with single-daemon
   enforcement disabled for this instance (see §4), so its frozen `os.environ` legitimately
   carries the correct `CLAUDE_HOOKS_TARGET_PANE` for the one session it serves.

5. **Launch Claude in `%CLAUDE`** with the same env (`env CLAUDE_HOOKS_...=... claude`),
   so every `.claude/hooks/*` wrapper auto-routes to the session socket with **zero
   wrapper changes** (the wrappers already resolve `${CLAUDE_HOOKS_SOCKET_PATH:-default}`).

6. **Run the injector in `%WATCH`** (disarmed by default). It is the **only** caller of
   `send-keys`. It reads the daemon's observe-only sidecar (`pct`, `last_status_ts`,
   busy/idle latch), evaluates the composite safe-to-inject predicate (§3), and on
   threshold→idle→under-cap→cooldown prints a visible countdown then injects one
   allowlisted slash command.

**Division of responsibility (the rails are non-bypassable because no one component can
type alone):**

- **Launcher** owns identity-minting (token/pane/epoch), daemon-path isolation, the
  deadman wall-clock timer, and an abort keybinding.
- **Dedicated daemon** stays **observe-only**. It writes a per-session sidecar (`pct` from
  the Status payload it already receives, plus a busy/idle latch derived from the clean
  single-session event stream — `UserPromptSubmit`/`PreToolUse`→busy, `Stop`→candidate
  idle). **It never calls `send-keys`.** This preserves the library's guardrail brand.
- **Injector (`tmux_inject` choke point)** owns every fail-closed gate: dedicated-daemon
  check, pane-alive check, allowlist content validation, idle composite, persisted cap,
  cooldown, injection ledger.

```
launcher ── creates ──► tmux session
   │                       ├─ %CLAUDE: claude (env: SOCKET/PID/LOG, TARGET_PANE, TOKEN)
   │                       │     └─ hooks auto-route ─► session socket
   │   starts (env)        │
   ├──────────────────────► dedicated daemon (observe-only)
   │                              └─ writes ─► untracked/tmux-sessions/<token>/sidecar
   │   runs                                            ▲ pct, idle-latch, last_status_ts
   └──► %WATCH: injector loop ── reads ─────────────────┘
              └─ predicate(§3) PASS ─► tmux send-keys -l "/compact" ; Enter  ──► %CLAUDE
```

---

## 2. How FATAL-1 is resolved (pane identity via controlled launch)

FATAL-1 was: `$TMUX_PANE` never crosses the AF_UNIX socket, the daemon is
terminal-detached with a frozen `os.environ`, and one shared daemon multiplexes N panes —
so a daemon handler can never write a correct `pane`.

**The launcher dissolves this by inverting the topology, not by smuggling env over the
socket.** Three plumbing facts (verified against this repo in the brainstorm):

- **Pane id is birth-time data, not per-event recovery.** The launcher created the pane,
  so it knows `#{pane_id}` by construction and passes it as `CLAUDE_HOOKS_TARGET_PANE`
  into the env the dedicated daemon forks from. The daemon's *frozen* environ — the very
  thing that made FATAL-1 fatal for a shared daemon — is now **correct and sufficient**,
  because a single-session daemon has exactly one right answer for its whole lifetime.
- **`session_id ⇄ pane` is 1:1, no correlation table.** The shared-daemon world needed a
  table because one daemon served N sessions; here each session has its own daemon, so the
  mapping is trivial. The injector reads `os.environ["CLAUDE_HOOKS_TARGET_PANE"]`.
- **Hooks auto-route with zero wrapper edits.** Because `init.sh` resolves the socket from
  `${CLAUDE_HOOKS_SOCKET_PATH:-...}`, exporting that var into the Claude process transparently
  redirects all of that session's hooks to the dedicated daemon — the linchpin that makes
  the launcher approach work without touching deployed wrappers.

**New mandatory rail (the one thing the launcher adds):** the injector must verify the
pane *still hosts this session* before every send — `tmux display-message -t $PANE -p '#{pane_dead} #{pane_pid}'` and compare `#{pane_pid}` against the launch-recorded value.
A human can kill/reattach/swap the pane; on mismatch or dead pane → fail-closed no-op.
The injector also asserts `CLAUDE_HOOKS_DEDICATED==1` and a valid `CLAUDE_HOOKS_LAUNCH_TOKEN`,
so the same code on a shared daemon **never types** — the FATAL-1 containment guarantee.

**Status: RESOLVED by construction** (one cheap spike to confirm the env actually reaches
the dedicated daemon's `/proc/<pid>/environ` — S-PANE below).

---

## 3. How FATAL-2 is addressed (composite safe-to-inject predicate)

FATAL-2 was: the statusLine payload has no idle/busy field and `capture-pane` misreads
catastrophically (permission dialog, vim mode, half-typed prompt, spinner). This does **not**
fully dissolve — but the launcher, owning the pane, unlocks several real signals that a
socket-fed daemon never had. The answer is a **fail-closed composite**: inject only if ALL
signals positively confirm idle; if any is unavailable, stale, or ambiguous → do NOT inject.

### The "is the user currently typing?" answer (the user's literal question)

Two independent, complementary signals — neither alone is sufficient:

- **`#{client_activity}`** (epoch of last client input) gives "fingers on keys *right now*":
  require `now - client_activity >= human_idle_floor_seconds` (e.g. 3-4s). **This also IS
  the human override** — the human touching the keyboard always wins the race by deferring
  the next injection. *Caveat (spike S-ACT):* must confirm `client_activity` ticks on
  keypress only, not on Claude's output redraw/spinner — load-bearing.
- **Input-box content stable + empty** (`capture-pane` of the bottom region, sampled twice
  ~250-700ms apart): catches a *typed-but-paused* prompt sitting in the box that
  `client_activity` would let through after the idle floor. Empty AND unchanged across two
  samples = not mid-composition.

### Composite predicate (cheap-first evaluation; expensive `capture-pane` last)

| #   | Signal                                                                                                                         | Source command                                            | Catches                                                            | Reliability                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------ |
| 1   | `#{pane_in_mode} == 0`                                                                                                         | `tmux display-message -p '#{pane_in_mode}'`               | copy/scroll/menu mode                                              | **VERIFIED (docs), HIGH**                        |
| 2   | `#{pane_current_command}` ∈ {claude/node}                                                                                      | `tmux display-message -p '#{pane_current_command}'`       | user/Claude shelled out (vim/less/git/ssh)                         | HIGH negative / **spike** positive (S-CMD)       |
| 3   | `now - #{client_activity} >= floor`                                                                                            | `tmux display-message -p '#{client_activity}'`            | fingers-on-keys now; **human override**                            | **spike** keypress-vs-redraw (S-ACT)             |
| 4   | daemon idle-latch = idle                                                                                                       | sidecar (Stop seen, no later UserPromptSubmit/PreToolUse) | mid-turn (assistant working)                                       | MEDIUM-HIGH (clean 1:1 event stream)             |
| 5   | `vim.mode != insert`                                                                                                           | statusLine payload field (daemon sidecar)                 | app-level vim mode                                                 | **VERIFIED field, HIGH**                         |
| 6   | `transcript_path` size/mtime unchanged ≥ N s                                                                                   | `stat -c '%s %Y' <transcript>`                            | assistant streaming, version-stable                                | MEDIUM-HIGH; **spike** incremental-append (S-TX) |
| 7   | input-box empty + stable; NO negative match (permission dialog, spinner/"esc to interrupt", `/compact` progress, error prompt) | `capture-pane -p -e` bottom region                        | **permission dialog** (no other signal sees it), half-typed prompt | MEDIUM, signature-driven, **spike** (S-SIG)      |
| 8   | `pct` freshness ≤ `idle_freshness_seconds`                                                                                     | sidecar timestamp                                         | stale-% blind spot                                                 | derived                                          |

**Why each tier is load-bearing (drop one and a specific mis-inject reopens):** 3 catches
live keystrokes; 7 catches paused-but-typed text *and* permission dialogs; 6 catches
streaming independent of fragile scraping; 1+2 catch copy-mode and shelled-out programs;
4+5 catch mid-turn and vim. The whole AND is **fail-closed** on any unknown.

**The strongest launcher-unlocked insight on the dialog problem:** because the dedicated
daemon receives this session's `PermissionRequest`/`Notification` events, it can set an
authoritative **"dialog open" flag** in the sidecar — replacing the most-fragile scraped
signal (signal 7's permission-dialog negative match) with an event-driven flag. Elevate
this: it turns the scariest FATAL-2 case into a hook-event fact.

**Status: ADDRESSED but spike-gated.** Idle becomes "several independent signals AND-ed,
fail-closed" — good enough to ship `/compact` safely, which it was not in the daemon-handler
design. The exact prompt-box signatures and the `client_activity` semantics are the genuine
make-or-break uncertainties and MUST pass Phase-0 spikes (S-ACT, S-SIG) before the injector
is built. tmux is not installed in the dev container — all six spikes run on a real host.

---

## 4. Safety model (minimum mandatory rails + where enforced)

| Rail                                                                                                                                                                                                         | Enforced at                                           | Why there                                                                                      |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Dedicated-daemon gate** (`CLAUDE_HOOKS_DEDICATED==1` + valid token, else no-op)                                                                                                                            | injector choke point                                  | shared daemon must NEVER type — FATAL-1 containment                                            |
| **Pane-alive + hosts-this-session** (`#{pane_dead}`/`#{pane_pid}` match)                                                                                                                                     | injector choke point                                  | wrong-pane after kill/reattach                                                                 |
| **Allowlist: slash-only regex** `^/[a-z][a-z0-9_:-]*( [^\n\r\x00-\x1f]*)?$`, no control chars, no `paste-buffer`/`load-buffer`/`set-buffer`, no event-data interpolation, `-l` always + literal `Enter` only | injector choke point + config-load schema validation  | RCE-via-PR-mutable-config defence; `-l` invariant RED-tested                                   |
| **Idle composite (§3), fail-closed on any unknown**                                                                                                                                                          | injector reads sidecar + tmux                         | mid-turn / mid-typing / dialog                                                                 |
| **Persisted per-session cap**, keyed by **launch token** (not pane id — reusable; not Claude `session_id` — churns on `/clear`), flock'd, `os.replace` atomic, epoch-based, survives daemon/injector restart | injector choke point (FIRST check, under flock)       | the restart-resets-cap BLOCKER; RED test: "inject to cap → restart → still refused"            |
| **Cooldown + post-compact re-arm latch** (re-arm only when a fresh statusLine `pct` below threshold, timestamped after the injection, arrives)                                                               | injector choke point                                  | self-retrigger; `compact→re-orient→grow→compact` cycle                                         |
| **Out-of-band injection ledger** (`injections.jsonl`, written BEFORE the send)                                                                                                                               | injector choke point                                  | loop-guard for `/compact`, which may not surface a sentinel-checkable `UserPromptSubmit`       |
| **Global unattended budget** (wall-clock + total-injections + optional `cost.total_cost_usd` ceiling) + **deadman kill** of the tmux session                                                                 | launcher (deadman) + injector (ceiling)               | `auto_continue_stop` × injector perpetual-motion — only a terminator OUTSIDE the loop is sound |
| **ABORT sentinel file + client-activity defer**                                                                                                                                                              | launcher (keybinding writes file) + injector (checks) | instant human override                                                                         |
| **subprocess arg-lists only; TIOCSTI ban**                                                                                                                                                                   | injector choke point                                  | security QA gate                                                                               |

**Single-daemon enforcement caveat (load-bearing correctness fact).** `enforce_single_daemon`
matches candidates on **project root only** (via `--project-root` or venv path) — **socket
path is NOT part of the match**. So a dedicated daemon launched with the *same* project root
would be reaped by the shared daemon, and vice-versa. The Plan 00127 spare logic only spares
the live owner of *its own* socket. **Therefore the dedicated daemon MUST be launched with
single-daemon enforcement disabled** (Option A: a new `start --no-enforce-single` flag or a
launch-time config overlay; Option B: a distinct synthetic `--project-root` child of the real
root so config discovery still walks up to `.claude/`). Option A is one well-named flag;
Option B is zero code but relies on path-walk semantics. **Recommend Option A** pending spike
S-ENF.

**`auto_continue_stop` interaction rail:** if both `auto_continue_stop` and the injector are
enabled in one session, the launcher MUST require an explicit `max_wall_clock_seconds` (no
default-infinite); missing budget → injector stays disabled.

---

## 5. Use cases & smallest valuable v1 + roadmap

**Catalogue ranking (value vs native-feature redundancy):**

- **#1 Custom-threshold `/compact` — FLAGSHIP, KEEP.** Native auto-compact has no threshold
  knob; the genuine gap is compacting *earlier/lower* (e.g. 50% of a 1M window) while keeping
  the visible TUI. Context % lives ONLY in the statusLine payload — the dedicated daemon
  already receives it. This single feature justifies the machine.
- **#2 PostCompact re-orientation prompt — KEEP (roadmap, opt-in).** After compaction Claude
  loses the thread; inject an allowlisted "re-read the active plan, state your next step."
  Not covered by anything native. Pairs with #1; needs the re-arm latch loop-guard.
- **#3 `/fix` on failing test — CUT from v1.** Claude already sees the failing output in the
  same turn; injecting duplicates the model's agency. The only clean home (a *stopped*
  session) belongs to `auto_continue_stop`.
- **#4 Session bootstrap prompt — CUT permanently.** Pure CLAUDE.md / `--append-system-prompt`
  reinvention, and more robust there.
- **#5 Scheduled slash-command injection — CUT.** `/loop` covers periodic prompts; the only
  slash-command anyone schedules is `/compact`, already #1.
- **#6 Notification stall-nudge — CUT.** Lands squarely in the permission-dialog danger zone.

**Smallest valuable v1 — "watch-along custom-threshold `/compact`, dry-run-first":**

1. The **launcher** (FATAL-1 killer): two-pane layout, capture `%CLAUDE` pane id, start the
   isolated dedicated daemon (enforcement off) with `CLAUDE_HOOKS_TARGET_PANE`, start Claude,
   start the injector **disarmed**.
2. A single **`tmux_inject`** utility = the ONLY `send-keys` call site, enforcing every §4 rail
   (allowlist hard-defaulted to just `/compact`, persisted token-keyed cap, fail-closed).
3. The **injector pane**: polls the daemon sidecar (`pct` only — daemon observes, never types),
   runs the composite idle gate (§3), prints a **visible countdown** before every injection
   ("THRESHOLD HIT — injecting /compact in 3… 2… 1 — Ctrl-C to abort").
4. **`--dry-run` is the default first experience** ("WOULD inject /compact", never types).
5. The daemon does ONE new passive thing: a status-line observer handler writes
   `pct`+`session_id`+`last_status_ts`+idle-latch to the sidecar. **The daemon never types.**

**Delightful vs scary line:** DELIGHTFUL = visible armed/off indicator in the `%CLAUDE` status
segment, countdown before every action, the injector logs *why it didn't act* as loudly as why
it did, one keypress to disarm (`prefix+I`), nothing types while you type. SCARY (avoid) =
silent injection, no armed indicator, free-form prompts, typing into a dialog, a cap that
resets on restart.

**Roadmap after v1 (ordered):** (1) PostCompact re-orientation (#2) with re-arm latch;
(2) status-segment + `prefix+I` arm/disarm polish; (3) generalised slash-command allowlist;
(4) `/fix`-on-failure ONLY if field demand, drain-when-idle, never on Stop; (5) daemon-managed
controller (no separate pane) — **DEFER hard / possibly never** (trades away the watchability
that is the whole point).

---

## 6. Residual gap vs native features (honest)

Strip everything native covers and **precisely one capability remains**: *issuing a slash
command (above all `/compact`) into a live, attached, human-watchable Claude Code TUI at a
moment and threshold of your choosing.* Every native programmatic path drops the attached TUI
(headless `-p`, the Agent SDK, API `context_management`/`compaction` beta), and the one native
path that keeps the TUI (`/loop`) can only re-prompt — it cannot issue slash commands or
compact. That intersection — **visible TUI ∧ slash-command/compaction control** — is genuinely
empty natively.

**But the gap is narrow and carries a roadmap risk.** It is essentially "custom-threshold
`/compact` in a watched session" plus a thin "inject an allowlisted slash command on demand"
primitive. The brand-inversion worry (a *safety* daemon that *types* is the literal inverse of
its identity) is mitigated by keeping the **daemon strictly observe-only** and putting all
typing in the launcher-spawned injector that the user explicitly started. **Roadmap risk:** if
the API compaction beta (`compact-2026-01-12`) lands in the CLI as a configurable threshold,
the flagship's entire reason to exist evaporates — track this and be willing to shelve.

**Recommendation: lean native** for native auto-compact (default threshold), `/loop` (all
periodic/bootstrap/re-engage prompting), headless/SDK (any non-watched automation), API
compaction (server-side threshold). **Build only** the launcher + observe-only sidecar handler

- single `/compact`-only injector.

---

## 7. Open spikes that MUST pass before build (the de-risking gate)

tmux is absent in the dev container — every tmux spike runs on a real host with a real Claude
Code session. **Build nothing until these pass; fail-closed where unproven.**

| ID          | Spike                                                                                                                                                                                   | Decides                                                                                                                             | Priority                              |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| **S-ACT**   | Does `#{client_activity}` tick on keypress only, or also on Claude's output/spinner redraw?                                                                                             | Whether the "is the user typing" gate (signal 3) is viable; if redraw bumps it, demote to necessary-not-sufficient and lean on S-TX | **MUST — make-or-break for FATAL-2**  |
| **S-SIG**   | Capture real bottom-region signatures for: empty box, typed text, spinner/"esc to interrupt", permission dialog, `/compact` progress, error prompt — store as **config**, not hardcoded | The fail-closed negative-match list (signal 7); main long-term maintenance liability (UI-version-fragile)                           | **MUST**                              |
| **S-ENF**   | Confirm `enforce_single_daemon` keys on project root only (socket excluded); pick `--no-enforce-single` flag vs synthetic root                                                          | Whether the dedicated daemon co-exists without reaping/being reaped                                                                 | **MUST**                              |
| **S-PANE**  | Confirm the dedicated daemon's frozen `os.environ` carries `CLAUDE_HOOKS_TARGET_PANE` (`grep TMUX /proc/<pid>/environ`); confirm `#{pane_id}` survives detach/reattach                  | Closes FATAL-1 empirically                                                                                                          | MUST (cheap)                          |
| **S-TX**    | Does `transcript_path` grow incrementally mid-response or only at turn end?                                                                                                             | Whether signal 6 is Tier-1-grade (clean, version-stable) or just corroboration                                                      | SHOULD (could upgrade idle detection) |
| **S-CACHE** | `/compact` produces a guardable `PreCompact`/`PostCompact` event for an *injected* compact? Confirm `cli stop`/`status` honour `CLAUDE_HOOKS_PID_PATH` for clean teardown               | Re-arm latch boundary; launcher teardown                                                                                            | SHOULD                                |
| **S-ENTER** | `send-keys -l` then `Enter` timing under load vs bracketed-paste vs capture-pane-confirm-then-Enter (closed loop)                                                                       | Replaces fragile `sleep 0.3`; partial-submit defence                                                                                | SHOULD                                |

**Phase-0 gate:** S-ACT + S-SIG + S-ENF + S-PANE must pass before the `tmux_inject` injector is
written. If S-SIG/S-CACHE fail, the honest fallback is **cap+cooldown-only, fail-closed on any
non-empty prompt** — blunter but still shippable for `/compact`.

---

## 8. Alternative architectures considered (wildcard angle) + why the recommended one wins

The wildcard lens proposed five places to put the typist. Ranked by how completely they dissolve
the FATALs:

- **ARCH-A — launcher writes a control file; pane-resident drainer types (recommended baseline).**
  Launcher sources the pane via `display-message`, dedicated daemon observes, injector in a
  visible pane types. FATAL-1 dissolved; FATAL-2 still heuristic. **This is the recommended
  architecture** — the conservative, proven-shape baseline, hardened with the §3 composite and
  §4 rails.
- **ARCH-B — launcher owns a thin PTY supervisor (`pty.fork`/`script`); tmux is a viewer.**
  Highest upside: idle detection becomes a *first-class fact* (the supervisor sees every byte the
  user types on the PTY master) and injection is a master-side write — both FATALs dissolve by
  construction. **Rejected for v1** because it reimplements terminal input plumbing and Claude's
  raw-mode/bracketed-paste/cursor-query TUI can be mangled by a naive passthrough. **Worth a
  dedicated spike post-v1** — it is the only design where "is the user typing" needs no heuristic.
- **ARCH-C — named-pipe command bus (`mkfifo`); many safe producers, one typist.** Clean
  decoupling, composes on top of A or B. **Rejected as the spine** (a FIFO with no reader blocks
  the writer → a hook `echo`ing into a dead FIFO hangs the hook and stalls Claude; needs
  `O_NONBLOCK`+drop-on-full). Note as a later producer-decoupling layer.
- **ARCH-D — tmux pane flags as the idle oracle + a key-table human-keystroke flag.** Not an
  injection mechanism — it is the FATAL-2 *signal source*, already folded into §3 (signals 1-3).
- **ARCH-E — abandon keystrokes; drive the SDK/`stream-json` headless mux with a TUI-shaped
  viewer.** Safety-maximal (turn boundaries are explicit stream events → perfect idle), but it is
  **not the same product** — you lose the real TUI, and slash commands may not work over
  stream-json stdin. **Rejected** (changes the product the user asked for); keep documented as the
  "if injection proves unsafe, here is the safe-but-different fallback."

**Why the recommended (A + §3 composite + §4 rails) wins:** it is the smallest change that
dissolves FATAL-1 cleanly (pane-as-birth-data), turns FATAL-2 from "no signal" into "several
independent signals AND-ed fail-closed," keeps the daemon observe-only (preserving the brand),
and is buildable with verified tmux primitives plus a bounded spike set. ARCH-B is the strictly
better long-term answer to FATAL-2 and should be the first post-v1 spike; ARCH-E is the escape
hatch if injection is ever judged unsafe.
