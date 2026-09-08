# Independent Audit #3 (Fable) — Plan 00135 vs the REAL Launchers

**Scope:** Full re-audit of the blocked Plan 00135 design corpus (PLAN.md, research-note.md,
context.md, both brainstorm syntheses, both hostile reviews, SPIKES.md) against (a) the daemon
source and (b) — for the first time — the **actual launch paths the user runs Claude with**:
the full `ccy` launcher from `LongTermSupport/fedora-desktop` and the thin `ccy()` alias used
inside LXC containers. Neither prior hostile review examined the launchers; this audit does,
and it changes the answer to the ARCH-A vs ARCH-B fork.

---

## 1. Verdict

**GO-WITH-CHANGES — and the change is decisive: abandon the ARCH-A tmux-launcher spine and
build ARCH-B (a thin PTY supervisor) as the primary architecture, integrated per-environment.**
The plan's safety rails, choke-point design, durable cap, and observe-only-daemon separation
are sound and verified; the two known blockers are real (SB-1 re-confirmed against
`enforcement.py`/`process_verification.py`; SB-2 genuinely has no clean ARCH-A answer without
the key-table hook). But the launcher reality delivers a finding more fundamental than either:
**neither of the user's real launch environments runs Claude inside tmux, neither ships tmux
in tracked IaC, and neither invokes any artifact this repo's installer could deploy as "the
launcher."** The entire ARCH-A edifice — tmux session, `$TMUX_PANE`, dedicated daemon,
socket-aware enforcement, key-table hook, `send-keys` — targets an environment that does not
exist and would have to be *built* (cross-repo, in fedora-desktop and the LXC tooling) before
the first injection could happen. Meanwhile ARCH-B dissolves SB-1 and SB-2 by construction,
needs **no tmux, no dedicated daemon, no enforcement change**, and has a natural insertion
point in *both* real launchers. The plan should be unblocked by re-scoping v1 to: observe-only
daemon sidecar handler (in `src/`) + a TDD'd PTY supervisor + status-line observability, with
the ARCH-A tmux design shelved as the documented fallback.

---

## 2. Claim verification table

Every load-bearing technical claim, checked against source in this session. Line citations
below are what the file **actually** shows today; drift from the plan's citations is noted.

| #   | Claim (where made)                                                                                                                             | Verdict                                        | Evidence checked                                                                                                                                                                                                                                                                                                                                 |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Daemon already receives the statusLine payload; handler reads `context_window.used_percentage` (PLAN.md "verified `model_context.py:144–146`") | **CONFIRMED (content); line citation DRIFTED** | `src/claude_code_hooks_daemon/handlers/status_line/model_context.py:169–170` — `ctx_data = hook_input.get("context_window", {})`, `used_pct = ctx_data.get("used_percentage") or 0`. Lines 144–146 are now the tier-threshold init. The `or 0` null-coercion the review demanded is already the live behaviour.                                  |
| 2   | `HookResult` has no injection field — `decision/reason/context/guidance/handlers_matched` only (`core/hook_result.py:54–58`)                   | **CONFIRMED, exact**                           | `src/claude_code_hooks_daemon/core/hook_result.py:54–58` — precisely those five fields, nothing else. Dispatch returns a result; no side-effect channel exists.                                                                                                                                                                                  |
| 3   | SB-1: enforcement matches peers on **project root only**; socket path never consulted                                                          | **CONFIRMED**                                  | `daemon/process_verification.py:116–135` (`_extract_project_root`: `--project-root` flag → `_VENV_PATH_MARKERS` interpreter path; no socket anywhere); `daemon/enforcement.py:70` (`find_all_daemon_processes(project_root=...)`).                                                                                                               |
| 4   | The Plan 00127 spare protects **only the live owner of this start's own socket**                                                               | **CONFIRMED**                                  | `daemon/enforcement.py:79–83` — spare requires `_socket_is_live(socket_path)` of *this start's* socket and the PID-file PID. A same-root daemon on a different socket lands in the kill loop at `enforcement.py:88–97` (container branch).                                                                                                       |
| 5   | Enforcement auto-enabled in containers at config generation                                                                                    | **CONFIRMED**                                  | `daemon/init_config.py:19–21` — `enforce_single_daemon_process: true # Auto-enabled (container detected)`. Both real environments (podman CCY, LXC) are containers, so SB-1's trigger condition is the default there.                                                                                                                            |
| 6   | Reuse gate runs before enforcement; three-state socket probe (v2 §3, cited cli.py:333–378)                                                     | **CONFIRMED; lines drifted ~10**               | `daemon/cli.py:326–398` — reuse gate at 346–364, degenerate-contention guards 369–389, `enforce_single_daemon(...)` at 393–398.                                                                                                                                                                                                                  |
| 7   | CLI lifecycle commands already resolve socket/PID via flag > env > default (v2 §6.2, SB-9 "zero new CLI surface")                              | **CONFIRMED**                                  | `daemon/cli.py:292–306` (`_resolve_pid_path`), `309–323` (`_resolve_socket_path`); `daemon/paths.py:1167` honours `CLAUDE_HOOKS_PID_PATH` exactly as cited.                                                                                                                                                                                      |
| 8   | Opt-in mechanism `get_default_enabled()` at `core/handler.py:228`                                                                              | **CONFIRMED, exact**                           | `core/handler.py:228`.                                                                                                                                                                                                                                                                                                                           |
| 9   | "tmux is not installed in the dev container (VERIFIED)" (v2 §8, SPIKES.md preamble)                                                            | **REFUTED (now)**                              | `/usr/bin/tmux` present; `dpkg -l tmux` → `tmux 3.3a-3`. Installed ad hoc for the spikes. Not itself a problem — but see #10.                                                                                                                                                                                                                    |
| 10  | "tmux … added to ccy Dockerfile" (SPIKES.md results header)                                                                                    | **REFUTED against tracked IaC**                | `grep -i tmux` across `files/var/local/claude-yolo/Dockerfile`, `Dockerfile.project-template`, the whole `files/` tree, and fedora-desktop git history (branch `F44`): **zero hits**. The spike environment was manually provisioned; the tracked CCY image does NOT ship tmux. fedora-desktop's own #1 rule is strict IaC — this is an IaC gap. |
| 11  | Research-note premise: "Claude Code is launched inside a tmux pane," hooks inherit `$TMUX_PANE`                                                | **REFUTED for both real launchers**            | Full ccy: `claude-yolo:2746–2766` runs `podman run -it --rm … claude --dangerously-skip-permissions` — no tmux, and `TMUX`/`TMUX_PANE` are not in the forwarded `-e` list, so even a user-side host tmux never reaches the container env. Thin LXC alias: runs `claude` directly in the interactive shell — no tmux.                             |
| 12  | Secure subprocess/detach patterns exist (PLAN.md Context)                                                                                      | **CONFIRMED (spot)**                           | Arg-list subprocess pattern per CLAUDE.md security standard; `os.fork`/`os.setsid` daemonisation confirmed in `cmd_start` region of `daemon/cli.py`.                                                                                                                                                                                             |
| 13  | statusLine `vim.mode`, `cost.total_cost_usd`, debounce/cancel semantics (research-note §5)                                                     | **COULD-NOT-VERIFY here**                      | Cross-checkable only against live Claude Code docs/captures; the note itself flags them `[verify]`. `used_percentage` and `context_window` presence are corroborated by handler #1 actually consuming them.                                                                                                                                      |
| 14  | S-KEYTABLE GREEN / S-SIG core GREEN (SPIKES.md results)                                                                                        | **COULD-NOT-VERIFY (accepted with caveat)**    | Empirical host results; mechanically plausible. Caveat: run in an environment (tmux-in-CCY) that no tracked launcher produces — see Finding N-1/N-9.                                                                                                                                                                                             |

---

## 3. Problems found (ranked)

### FATAL

**N-1 — The flagship is undeliverable in every environment the user actually runs. (NEW)**
The whole corpus assumes tmux is ambient. It is not, anywhere:

- **Full ccy:** `claude-yolo` runs `podman run -it --rm … claude` in the host foreground
  (`claude-yolo:2746–2766`); `entrypoint.sh:266` `exec "$@"` puts claude directly on the
  container PTY. No tmux binary in the image (tracked `Dockerfile`: zero tmux references),
  no tmux in the launcher, no `$TMUX_PANE` in the container env (not forwarded in the `-e`
  list even if the user wraps `ccy` in host tmux — and a host tmux pane's server would be
  unreachable from inside the container anyway).
- **Thin LXC alias:** `ccy()` runs `claude update && claude --dangerously-skip-permissions`
  directly in the interactive shell. No tmux, no wrapper, no supervisor.

Consequence: ARCH-A's launcher, dedicated daemon, key-table hook, `send-keys` choke point —
**none of it can execute today**. tmux is not a precondition to detect gracefully (the plan's
"graceful no-op when `$TMUX_PANE` unset" would simply mean the feature is permanently off for
this user); it is a **new deliverable requiring cross-repo IaC changes** in fedora-desktop
(Dockerfile + entrypoint or claude-yolo) and in the LXC provisioning. The plan never budgeted
this, and the hooks-daemon installer cannot ship it.

**SB-1 — Mutual daemon reaping (RE-CONFIRMED; scope-out available).**
Verified line-by-line (claims #3–#5 above): identity is project-root-only; the spare protects
only the same-socket incumbent; container auto-enable makes the kill path the default in both
real environments (podman CCY and LXC are both containers). v2's socket-aware fix (§3) is a
correct, narrow-never-widen design — but it is a Plan 00127-invariant change requiring its own
hostile review, and it exists **solely to keep a dedicated daemon alive**. Under the
recommendation below (no dedicated daemon), SB-1 is scoped out of v1 entirely rather than
solved. If ARCH-A is ever revived, SB-1 must be fixed exactly as v2 §3 specifies.

**SB-2 — "Is the user typing?" (RE-EVALUATED; ARCH-B answers it, ARCH-A still doesn't cleanly).**
The spike results improve the picture (S-KEYTABLE observe-and-forward GREEN; empty-composer
`❯ ` anchor GREEN) but both were produced inside a hand-provisioned tmux that no real launcher
creates (N-1), and the residual caveats the spike itself lists (full-key `Any` binding
coverage, per-key `run-shell` process spawn under fast typing, control/escape/paste re-send
fidelity) are untested. Meanwhile both real launchers give ARCH-B its input byte-stream for
free: in the LXC path a supervisor wrapping `claude` sees every keystroke on the PTY master;
in the CCY path an in-container supervisor (entrypoint-wrapped) sees the same. Raw input bytes
are a positive fact; no heuristic, no tmux, no key-table. SB-2 is only *solved by construction*
under ARCH-B — which is now also the only architecture the environments support without new
IaC.

### SERIOUS

**N-2 — Launcher-artifact ownership mismatch. (NEW)**
v2 §6.1 has the hooks-daemon installer deploy `.claude/tmux/claude-tmux.sh` and assumes users
will launch Claude through it. Real users type `ccy`. The full launcher lives in
fedora-desktop (`files/var/local/claude-yolo/claude-yolo`, version-gated with hash validation
and a pre-commit hook); the thin alias lives in per-container shell config provisioned outside
both repos. **No artifact this repo deploys is on the launch path.** Any injection feature
needs an explicit integration commit in fedora-desktop (a CCY version bump) and/or the LXC
tooling. The plan must name these integration points as deliverables owned elsewhere, or the
feature ships dormant.

**N-3 — CCY splits namespaces; the v2 injector spec is partly unimplementable there. (NEW)**
If tmux were added on the **host** around `podman run`: the pane's foreground command is
`podman`, not `claude`/`node` — SB-3's hard pane rail (`pane_current_command ∈ {claude,node}`

- child-PID descendant walk) is unimplementable across the PID namespace; the injector cannot
  verify Claude's liveness, only podman's. If tmux goes **inside** the container: the "launcher"
  must be `entrypoint.sh`, tmux must enter the image (IaC), and the tmux server dies with the
  `--rm` container each session. Either way the v2 §5.1 rail needs redesign for this
  environment. (ARCH-B in-container supervision sidesteps all of it: `waitpid` on the claude
  child is the liveness rail, in-namespace.)

**N-4 — The launcher's own interactive prompts are a new mis-injection target. (NEW)**
`claude-yolo` runs interactive prompts on the SAME terminal both before Claude starts
(token/network/compose selection) and **after Claude exits** — e.g. the post-session
`read -rp "Stop compose services? [Y/n]"` loop (`claude-yolo:~2770+`). A stale-sidecar or
in-flight-countdown injection landing after Claude exits would answer the compose-teardown
prompt (or worse, a future destructive prompt) instead of typing into Claude. No prior review
saw this because none looked at the launcher. ARCH-A's pane rail *partially* covers it
(foreground command changes), except in the host-tmux topology where it can't (N-3). ARCH-B's
`waitpid` covers it absolutely: the supervisor knows the instant its child exits and never
writes afterwards.

**N-5 — Version churn makes screen-signature dependence structurally expensive. (NEW)**
The thin alias runs `claude update` on **every launch**; full ccy re-installs `@latest` daily
(`update_claude_inplace()`, re-running the ctrl+z patch each time — itself proof this stack
already fights UI churn: fedora-desktop's `ContainerRules.md` documents the suspend-patch
anchor breaking release-to-release). Any S-SIG signature config (`❯ ` anchor, rule lines,
placeholder-dim SGR class) decays at Claude Code's release cadence. The v2 self-disabling
classifier degrades this to "feature silently off" (safe), but on this update cadence
"silently off, pending signature re-capture" may be the *steady state*. Screen scraping should
be corroboration, never the primary gate — which again points at ARCH-B's byte-level signals.

**N-6 — Coexistence (the user's HARD requirement) is trivially satisfied per-environment —
the plan over-engineered for the wrong topology. (RE-FRAMING)**
"Mix tmux-injection sessions with normal sessions on the same project" was modelled as
shared-vs-dedicated daemons in one namespace. In reality: each ccy launch is its **own
ephemeral container** (`--rm`, per-container hostname → per-container daemon runtime files via
hostname-keyed paths), and LXC containers are likewise isolated. A supervised session and N
normal sessions on the same project already coexist by container isolation; the only shared
state is the bind-mounted `untracked/` — which the durable cap (keyed
`(project_root, git_branch)`, flock'd) already handles. The dedicated-daemon machinery and the
enforcement change exist to solve a same-namespace problem the real environments mostly don't
have. Under ARCH-B they vanish entirely (the *shared, existing* daemon writes the observe-only
sidecar; nothing else changes).

### MINOR

**N-7 — `CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1` shapes every screen assumption.**
Both environments force the classic in-band renderer (`entrypoint.sh:171–181`; thin alias
exports it too). Conversation lives in native terminal scrollback; only the bottom band is
Claude-owned. Whole-screen idle templates are meaningless here — matching must stay
bottom-band-anchored (the spike happened to do this correctly). Signatures must also be
captured per renderer config: any environment that re-enables fullscreen/alt-screen renders
differently. Conversely, `CLAUDE_CODE_DISABLE_MOUSE=1` removes tmux mouse-mode conflicts —
a small point in ARCH-A's favour, mooted by the recommendation.

**N-8 — Terminal stack is already customised; a supervisor must cooperate.**
Host side: `stty susp undef` with state saved/restored in `cleanup()`
(`claude-yolo:~2718–2723`). Image side: the binary `handleSuspend` no-op patch +
`CCY_DISABLE_SUSPEND=1`. An ARCH-B supervisor must save/restore termios on ALL exit paths
(including SIGKILL of the child) and not fight these existing hacks. Bounded, well-trodden
(v2 §9.5 already priced it), but the audit confirms it is not hypothetical in this stack.

**N-9 — The spike environment is unmanaged and unreproducible from IaC.**
SPIKES.md says tmux was "added to ccy Dockerfile"; the tracked Dockerfile has no tmux (claim
#10). Whatever the intent, the spike substrate exists only in this running container.
fedora-desktop's fail-fast IaC rules make this exactly the "manual state becomes permanent"
trap its own docs warn about. Any spike that gates an architecture decision must run on an
IaC-provisioned environment; re-run the deciding spikes (now S-PTY, per the recommendation)
that way.

**N-10 — Stale line citations in the plan corpus.**
`model_context.py:144–146` → now 169–170; several cli.py cites drifted ~5–15 lines (claims
#1, #6, #7). All content-correct today, but the corpus is one refactor away from citing wrong
code. Prefer symbol names over line numbers in the rewrite.

---

## 4. Launcher-reality analysis

### 4.1 Full `ccy` (fedora-desktop, podman)

Chain: host bash `claude-yolo` (long-lived, foreground) → `podman run -it --rm --name … -w /workspace $IMAGE claude --dangerously-skip-permissions …` → `entrypoint.sh` (git/gh/ssh
setup, `IS_SANDBOX=1`, `CCY_DISABLE_SUSPEND=1`, `CLAUDE_CODE_DISABLE_MOUSE=1`,
`CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`, symlinks `/root/.claude → /workspace/.claude/ccy`)
→ `exec claude …`. Project dir bind-mounted `$PWD:/workspace` (`claude-yolo:1763–1766`) — so
**anything the in-container daemon writes under `untracked/` is host-visible**, and vice
versa. `.last-launch.conf` is a launch-settings cache (token/SSH/network) under
`.claude/ccy/`, re-validated against `CCY_VERSION`+hash — the launcher is version-disciplined
and hostile to untracked drift (good news for a clean integration, bad news for casual
patching).

Key answers to the questions posed:

- **Runs Claude inside tmux?** No.
- **Inside a container?** Yes — podman (rootless by default; `CCY_CONTAINER_ENGINE` can
  select docker). Own PID/mount namespaces; daemon container-detection fires; enforcement
  auto-enables.
- **Sets `$TMUX`/`$TMUX_PANE`?** No; not forwarded even if present on the host.
- **A launcher/supervisor process that could own a PTY?** **Yes, two candidates:** (a) the
  host `claude-yolo` process around `podman run` (sees host keystrokes; but PID-namespace-blind
  to claude, and stacking a second raw-mode PTY over podman's attach is the riskier variant);
  (b) the container `entrypoint.sh`, which currently `exec`s claude and could instead exec a
  supervisor wrapping claude **in the same namespace** — the clean insertion point.

### 4.2 Thin `ccy()` alias (LXC)

`nvm` sourcing, env exports (same TUI kill-switches, `IS_SANDBOX=1`,
`CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1`, agent-teams/LSP flags), token selection
(`_claude_parse_token_arg`/`_claude_select_token` — provisioned by the LXC tooling, not
present in fedora-desktop), then `claude update && claude --dangerously-skip-permissions`.

- **tmux?** None. If the user *chose* to run `ccy` inside a self-started in-container tmux,
  `$TMUX_PANE` would genuinely reach hooks (same namespace) and ARCH-A would be mechanically
  possible there — but that is a user-behaviour change plus a tmux install, not the current
  world. Say it plainly: **the flagship cannot run in the LXC path today at all.**
- **Supervisor insertion point?** Yes — the alias itself: swap the final `claude …` for
  `claude-supervise … -- claude …`. One-line change in the LXC shell config.
- **`claude update` every launch** → maximal version churn (N-5).
- **`CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1`** → same in-band renderer as CCY (N-7), so one
  signature/fixture set can serve both environments at a given Claude version.

### 4.3 Per-environment feasibility matrix

| Capability                                   | Full ccy (podman)                                                                    | Thin LXC alias                                                     |
| -------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------ |
| tmux present (tracked IaC)                   | **No** (not in Dockerfile, launcher, or entrypoint)                                  | **No**                                                             |
| `$TMUX_PANE` visible to hooks                | **No** (and unreachable across container boundary even with host tmux)               | **No** (unless user self-hosts tmux in-container — not current)    |
| PTY supervisor insertion point               | **Yes** — entrypoint (in-container, preferred) or host wrap of `podman run`          | **Yes** — the `ccy()` alias, one line                              |
| Idle/context signal available today          | Yes — statusLine → shared in-container daemon; sidecar host-visible via bind mount   | Yes — same, all in one namespace                                   |
| Flagship deliverable via ARCH-A (tmux)       | Only after fedora-desktop changes: tmux in image + entrypoint-as-launcher + SB-1 fix | Only after user installs tmux + rewrites alias + SB-1 fix          |
| Flagship deliverable via ARCH-B (supervisor) | **Yes** — supervisor in image + one argv change; no daemon changes, no SB-1          | **Yes** — supervisor + alias change; no daemon changes, no SB-1    |
| SB-3-class "still Claude?" rail              | ARCH-A host-tmux: **unimplementable** (N-3); ARCH-B in-container: `waitpid` (exact)  | ARCH-B: `waitpid` (exact)                                          |
| Post-Claude-exit typing hazard (N-4)         | Real (compose-teardown prompt on same TTY)                                           | Minor (returns to interactive shell — still must never type there) |
| Claude version churn                         | Daily in-place `@latest`                                                             | `claude update` on **every** launch                                |
| Who owns the integration commit              | fedora-desktop (CCY version bump discipline)                                         | LXC tooling / user shell config                                    |

The verdict of the matrix is unambiguous: **ARCH-B is deliverable in both environments with
one small integration change each; ARCH-A is deliverable in neither without building new
infrastructure first.** The v2 decision rule ("S-KEYTABLE GREEN → ARCH-A viable") answered
the wrong question — it proved tmux *mechanics* in a synthetic environment while the
*deployment* environments have no tmux to be mechanical in.

---

## 5. Proposed way forward

**Architecture: ARCH-B — a thin, faithful PTY supervisor (`claude-supervise`) wrapping the
`claude` process in its own namespace, per-environment integration; the daemon stays strictly
observe-only.** Rationale: it is the only design that (a) both real launchers can adopt with
a one-line change, (b) dissolves SB-2 by construction (raw input bytes = positive
human-typing fact; empty-composer check via an in-supervisor terminal model), (c) dissolves
SB-3 by construction (`waitpid` on the child; never types after exit — also closes N-4), and
(d) **eliminates the dedicated daemon**, taking SB-1, SB-9, the socket-aware enforcement
change, its hostile review, and the orphan janitor out of scope entirely. v2 §8 already
recognised all of this ("ARCH-B … dissolves SB-1/SB-9 … *more* CI-testable than ARCH-A");
it just weighted the S-KEYTABLE spike above the environments. The environments win.

### Slice 0 — spike gate (reduced to two MUSTs)

- **S-PTY (now THE make-or-break):** run the ~100-line `pty` supervisor around the real
  `claude` in BOTH environments — in-container CCY (via a throwaway entrypoint override) and
  LXC — exercising: raw mode, bracketed paste, SIGWINCH (needs explicit forwarding beyond
  `pty.spawn`), cursor-DSR, colour, permission dialogs, and clean termios restore on child
  SIGKILL (respecting ccy's existing `stty susp undef` + cleanup, N-8). Provision the spike
  substrate via IaC, not by hand (N-9). GREEN = build; RED in either environment = fall back
  per below.
- **S-CACHE (unchanged MUST):** injected `/compact` produces guardable
  `PreCompact`/`PostCompact`; without it the re-arm latch leans on the `pct`-drop heuristic
  with the loud-disable failure branch (v2 §5.5) as primary.
- **Dropped from the critical path:** S-KEYTABLE (tmux-only), S-ENF (no dedicated daemon),
  S-SIG-as-gate. Keep the S-SIG captures only as **fixtures** for the supervisor's composer
  matcher (see below). S-TX/S-ENTER: subsumed — the supervisor sees output bytes and can
  confirm the injected text echoed in the composer before sending `\r`.

### Slice 1 — observe-only daemon sidecar handler (pure `src/`, ships alone, useful alone)

`TmuxContextSidecarHandler` renamed to something injection-neutral (e.g.
`context_sidecar`): a status_line handler, `get_default_enabled() → False`, writing
`{pct, cost_usd, session_id, ts, seq, writer_pid, dialog_open, vim_mode, idle_latch}`
atomically to `daemon_untracked_dir()/context-sidecar/` with the v2 §5.4 authentication
scheme. Plus the event-driven dialog-open flag (universally praised in both reviews). Zero
typing, zero risk, brand-consistent, TDD-able in the dev container today. This is also
independently useful (external tooling can watch context %).

### Slice 2 — the supervisor, dry-run only

`claude-supervise` as a TDD'd package (recommend `src/claude_code_hooks_daemon/supervise/`
with a console entry point — ARCH-B is `pty.openpty`-testable in CI with no display, so it
meets the 95%/QA bar that ARCH-A's injector never could; this resolves SB-8 properly rather
than by harness heroics). Components:

- PTY master loop (input observe+forward, output observe+forward, SIGWINCH, termios
  save/restore-on-any-exit, `waitpid`).
- A minimal terminal model (`pyte`) maintaining the bottom band only (N-7): the composer-empty
  check (`❯ ` anchor, non-whitespace after glyph = human composing = defer) driven by
  **committed fixtures** from the S-SIG captures; three-state IDLE/BUSY/UNKNOWN with
  UNKNOWN⇒refuse and the self-disabling drift latch (all v2 §4.4, unchanged — it was good).
- The full v2 rail set at one choke point, unchanged in substance: allowlist frozen to
  `{'/compact'}` (closed set, no arguments, control-char ban); durable flock'd
  `(project_root, git_branch)`-keyed cap with the relaunch RED test; **mandatory**
  `max_total_cost_usd` when armed (documented as lagging); wall-clock deadman; ledger written
  before send; abort file; re-arm latch with the loud-disable failure branch.
- Human-typing gate: `now - last_input_byte ≥ idle_floor` (positive, by construction) AND
  composer empty AND daemon idle-latch AND dialog-flag false AND fresh sidecar. Injection =
  write `/compact` to the master, confirm echo in the composer via the terminal model, then
  write `\r`; on non-echo, write `C-u` and abort (v2 §4.5 critical section, ported).
- **`--dry-run` is the default**; `--arm` refuses without `--max-cost`.

**Observability without the watch pane:** the second-tmux-pane requirement dies with tmux.
Replace it with (a) a supervisor decision log (`tail -f`-able from anywhere), and (b) — the
elegant option this codebase uniquely enables — a tiny status_line segment reading the
supervisor's state file and rendering `🤖 dry-run` / `🤖 armed 2/5` / `🤖 disabled(drift)`
**inside Claude's own status line**. The user watches the controller in the same TUI they
were already watching. This is strictly better UX than a second pane.

### Slice 3 — arm `/compact`, integrate per environment

- **LXC first** (cleanest namespace, identical to the S-PTY spike): one-line alias change
  `claude-supervise -- claude --dangerously-skip-permissions …`, owned by the LXC tooling.
- **CCY second:** add the supervisor to the image and thread one argv change through
  `claude-yolo`/`entrypoint.sh` (in-container wrap, NOT host-side — avoids N-3 and double raw
  mode), behind a `ccy --supervise`-style opt-in flag. This is a fedora-desktop plan with a
  CCY version bump; name it as an explicit cross-repo dependency in PLAN.md.

### Explicitly drop / defer / shelve

- **Drop from v1:** dedicated daemon, socket-aware enforcement (SB-1 fix), launcher
  `claude-tmux.sh`, key-table hook, `tmux_inject`/`send-keys` entirely, orphan janitor,
  private tmux server, `%WATCH` pane. (If ARCH-A is ever revived, SB-1 must be fixed per v2
  §3 — record that, don't lose it.)
- **Defer (roadmap, unchanged):** PostCompact re-orientation (needs the ledger reader +
  re-arm latch proven first).
- **Stay permanently cut:** `/fix`-on-failure, session bootstrap, scheduled injection,
  notification nudge, daemon-managed no-pane controller (per v2 §7).
- **Fallback of record if S-PTY fails in a real environment:** the ARCH-A in-container tmux
  design for whichever environment tolerates it — accepting tmux-into-IaC (N-1), the SB-1
  enforcement fix, and the key-table/S-SIG spikes as the price. If both paths fail: shelve
  the typist; keep Slice 1 (the observe-only sidecar), which is valuable alone.
- **Track the obsolescence risk:** a native configurable compact threshold in the CLI
  (server-side `compact-2026-01-12` beta already exists) erases the flagship. Slices 1–2 are
  cheap and mostly reusable (sidecar, supervisor plumbing); Slice 3 is the part to be willing
  to abandon.

### Why not "companion repo" (Review #2's product fork)?

The user retired the brand objection (context.md), and the launcher reality adds a practical
reason: the integration points live in *other* repos regardless (fedora-desktop, LXC tooling),
so what this repo ships must be a clean, versioned, QA'd artifact those integrations can
depend on — which argues for `src/` + installer distribution, not a loose companion script.
The observe-only daemon boundary (the daemon never types; the supervisor is a separate process
the user's own launcher started) preserves the architectural seam both reviews endorsed.

---

## 6. Open questions for the user

1. **Environment priority:** LXC-first (cleanest, one-line alias change you control) then
   CCY — agreed? Or must CCY land first?
2. **CCY integration shape:** in-container supervisor via entrypoint/argv (recommended) means
   a fedora-desktop change + image rebuild + CCY version bump. Are you willing to carry that
   cross-repo work as part of this plan's delivery, and should it be opt-in
   (`ccy --supervise`) or config-file driven?
3. **ARCH-A fallback appetite:** if S-PTY shows TUI fidelity problems, is adding tmux to the
   CCY image / LXC provisioning (via IaC) acceptable as the fallback path — or would you
   rather shelve the typist and keep only the observe-only sidecar?
4. **Placement:** supervisor in `src/claude_code_hooks_daemon/supervise/` (installer-shipped,
   full QA/95% bar — recommended) vs `scripts/`/examples. Confirm the `src/` placement given
   Review #2's product lens objected and you down-weighted it.
5. **Observability:** is the status-line armed/dry-run indicator + decision log acceptable as
   the replacement for the "watch it happen in a second pane" experience that motivated the
   original tmux framing? (The visible TUI itself is unchanged — you watch injections appear
   in the composer as if typed.)
6. **Thin-alias ownership:** where does the LXC `ccy()` function actually live (lxc-bash?),
   so the integration change can be tracked in IaC rather than hand-edited per container?
