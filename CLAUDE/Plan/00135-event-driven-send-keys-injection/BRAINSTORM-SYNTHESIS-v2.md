# Brainstorm Synthesis v2 — Plan 00135: Launcher-Controlled `send-keys` Injection

**Status:** Design proposal v2 (consolidates six round-2 design-deepening angles + HOSTILE-REVIEW-2's NO-GO + SB-1..SB-9 + required-changes §7 + context.md user direction).
**Supersedes nothing:** v1 (`BRAINSTORM-SYNTHESIS.md`) and HOSTILE-REVIEW-2 remain on disk; versions accrue.
**Goal of v2:** convert the review-#2 NO-GO into a BUILDABLE plan by resolving — or explicitly spike-gating — every SB-1..SB-9 blocker, honouring the two locked user decisions (brand objection DOWN-WEIGHTED; concurrent coexistence is a HARD REQUIREMENT, not a spike).

---

## 1. What changed since v1

v2 is not a polish of v1 — it changes the spine on three axes the hostile review proved unsound, and drops one objection the user retired.

1. **The "is the user typing?" signal is no longer `client_activity`.** Review-#2 SB-2 assessed `#{client_activity}` >70% likely to measure terminal *redraw*, not keystrokes, with **no residual positive human signal** if it fails. v2 **drops `client_activity` as a primary signal** and replaces it with two positive constructions, evaluated in priority order by a Phase-0 spike: (a) a **tmux-native per-key stamp** (a `root`-key-table hook on a private `tmux -L` server that observes keystrokes without consuming them), and (b) a **positive idle-screen-template** (whole-band match that asserts a known-idle composer, fails closed on anything unrecognised). `client_activity` survives only as optional corroboration and is dropped entirely if (a) lands.

2. **Coexistence moved from spike to design requirement, solved by socket-aware enforcement.** v1's `--no-enforce-single` "one flag" mitigation was shown to be one-directional (SB-1): it stops the dedicated daemon killing others but does nothing to stop the *shared* daemon reaping the *dedicated* one on its next restart under the default container config. v2 replaces it with **socket-aware peer identity** in `enforce_single_daemon` / `find_all_daemon_processes` (identity = `(project_root, socket_path)`, narrow-never-widen), plus a belt-and-braces `--dedicated` do-not-reap marker. This is a Plan 00127-invariant change and is flagged for its own hostile review.

3. **The brand objection is dropped** per context.md: the daemon already blocks and guides Claude actively; injection is another dimension of that. Review-#2's Product DO-NOT-BUILD rested heavily on brand inversion and `src/` placement — those arguments are **retired by user decision**. The technical objections (mis-injection, runaway cost, pane identity, untested-injector) stand on their own and are all addressed below. Consequence: the typist MAY live in `src/` as a proper package, deployed by the installer like `mkplan.bash` — provided it meets the project's 95%/TDD/QA bar (SB-8, now satisfiable via a CI tmux harness).

4. **ARCH-B (PTY supervisor) reassessed and PROMOTED to co-primary / fallback-of-record.** Round-2 analysis showed a faithful supervisor is ~60-120 lines (stdlib `pty.spawn` handles raw-mode + byte copy; only SIGWINCH needs ~6 explicit lines; bracketed-paste/DSR/mouse/truecolor pass through *by being transparent*), and that under ARCH-B both FATALs **dissolve by construction** (raw input bytes = positive human-typing fact; `waitpid` on the child = SB-3 gone). ARCH-B is the pre-committed fallback if the ARCH-A FATAL-2 spikes fail, and the decisive go/no-go rule is stated in §8.

Everything review-#2 listed as GENUINELY SOUND is kept: pane-id-as-birth-data via 1:1 frozen environ, daemon strictly observe-only, hook auto-routing via `CLAUDE_HOOKS_SOCKET_PATH`, the event-driven dialog-open flag, the persisted flock'd `os.replace` cap (the flaw was the *key*, fixed in §5), ledger-written-before-send, deadman outside the loop, dry-run-first default + visible countdown + `/compact`-only allowlist.

---

## 2. Recommended architecture

**Baseline = ARCH-A (launcher → dedicated observe-only daemon → injector pane), with ARCH-B as the pre-committed fallback.** Prose diagram:

```
launcher (scripts/.../claude-tmux.sh, installer-deployed)
  │  mints token, creates 0700 session dir, exports CLAUDE_HOOKS_{SOCKET,PID,LOG}_PATH
  │  + CLAUDE_HOOKS_{TARGET_PANE,DEDICATED=1,LAUNCH_TOKEN,CAP_KEY}
  │  runs the WHOLE session on a PRIVATE tmux server: tmux -L cchd-<token>
  ├─► dedicated daemon (observe-only, --dedicated, --socket <session>.sock)
  │        └─ writes authenticated sidecar: pct, total_cost_usd, idle_latch,
  │           dialog_open, vim_mode, writer_pid, seq, mtime
  ├─► %CLAUDE pane: claude (same env → hooks auto-route to session socket)
  └─► %WATCH pane: injector loop (the ONLY send-keys caller; disarmed unless --arm)
           reads sidecar + live tmux + key-stamp → composite predicate (§4)
           → visible countdown → tmux send-keys -l "/compact" ; capture-confirm ; Enter
```

### The FATAL-2 PRIMARY signal — decisive recommendation

**PRIMARY: the tmux-native per-key stamp (key-table hook on a private server), CONDITIONAL on spike S-KEYTABLE landing its observe-only "Candidate C" form.** Rationale: it is the only ARCH-A construction that answers "is the human typing *right now*" as a **positive fact** rather than an inference, *without* reimplementing the PTY (ARCH-B). A per-keypress tmux hook attached to `run-shell -b` is **not in the key-delivery path**, so it physically cannot eat a keystroke — it stamps `last_human_keypress_epoch` and tmux still delivers the key to Claude. This gives the ARCH-B guarantee at ARCH-A cost.

**CORROBORATION #1: the positive idle-screen-template** (S-SIG). This is the *irreplaceable* catch for the **paused typist** — a human who typed a half-line then stopped to think. No keystroke stamp and no hook event fires while they stare at the screen; only the screen shows the non-empty composer. The template asserts a known-idle composer positively (box anchor present, interior empty after stripping the dim-placeholder SGR run, no forbidden tokens) and returns one of three states — `IDLE` / `BUSY` / `UNKNOWN` — where **both BUSY and UNKNOWN block injection** (fail-closed on unrecognised screens, fixing SB-2's fail-open negative-blocklist).

**CORROBORATION #2: the event-driven dialog-open flag** from the dedicated daemon (`PermissionRequest`/`Notification` open it, next non-dialog event closes it). Authoritative for the modal class the screen template is weakest at (teardown/redraw race).

**Claude-idle (orthogonal axis): the daemon idle-latch** (Stop seen, no later `UserPromptSubmit`/`PreToolUse`) tells us *Claude's* turn is done — a separate question from *the human's* fingers. Both axes must read idle.

**FALLBACK ladder if spikes fail:**

- S-KEYTABLE yields only enumerated bindings (Candidate B, *in* the delivery path) that drop any key → **key-table REJECTED** (eating keystrokes is worse than the bug we prevent) → fall back to **ARCH-B** (§8).
- S-SIG too theme-fragile to classify placeholder-dim → degrade to "any non-empty composer interior = defer" (per-theme literal placeholder strip), then to **cap+cooldown-only, fail-closed on any non-empty band**, leaning on the dialog-open flag for modals.

`client_activity` is corroboration-only and is dropped entirely if S-KEYTABLE Candidate C passes.

---

## 3. FATAL-1 + coexistence — socket-aware enforcement (SB-1)

### The confirmed bug (verified against the repo)

`cmd_start` (cli.py:333-378) runs two stages. Stage 1 = Plan 00127 reuse/liveness gate keyed on the start's **own** socket (`_socket_liveness_sync(Path(socket_path))`, cli.py:334) — it never probes a *different* socket. Stage 2 = `enforce_single_daemon(config, pid_path, project_root=project_path, socket_path=...)` (cli.py:373). Inside enforcement.py: `find_all_daemon_processes(project_root=...)` (enforcement.py:70) enumerates peers via `_is_daemon_server_process` + `_extract_project_root == target_root` (process_verification.py:87-95, 116-135). **`_extract_project_root` derives root from `--project-root` OR the venv-interpreter `_VENV_PATH_MARKERS` — socket path is NEVER consulted.** The only spare (enforcement.py:79-83) excludes the live owner of the *start's own* socket. A dedicated daemon owns a *different* socket and shares `/workspace` root → it lands in `other_daemons` → in a container (`in_container and other_daemons`, enforcement.py:88) it is SIGTERM→SIGKILLed. Container auto-enable (init_config.py:19-21) makes this the default. **SB-1 confirmed.**

### The fix — identity becomes `(project_root, socket_path)`; socket DISCRIMINATES peers

**Layer A (PRIMARY) — socket-aware peer exclusion.** The daemon's resolved socket is computed at cli.py:316, well before the fork at cli.py:393. Add an explicit `--socket-path PATH` token to the **daemonized process argv** at fork time (so it is greppable in `/proc/<pid>/cmdline`, exactly where root is already read from). Add `_socket_from_cmdline(cmdline)` and, in `find_all_daemon_processes`, when the caller passes its own `socket_path`, **exclude any peer whose cmdline socket differs**. The slot-in goes into `enforce_single_daemon` after `other_daemons` is built (enforcement.py:74) and BEFORE the live-socket spare (enforcement.py:79):

```
# SB-1: a same-root daemon owning a DIFFERENT socket is a peer, not a duplicate.
if socket_path is not None:
    other_daemons = [
        pid for pid in other_daemons
        if _daemon_socket_for_pid(pid) in (None, _normalize_socket(socket_path))
    ]
```

`_daemon_socket_for_pid` returns the peer's normalized socket or `None` when unreadable. The `in (None, ...)` clause preserves the existing **fail-safe-leaves-running** posture (process_verification.py:67-68): a peer whose socket we cannot read is left alone, never killed. This **only ever removes PIDs from the kill set** — it can never widen it, so it cannot regress Plan 00127.

**Layer B (BELT-AND-BRACES) — `--dedicated` do-not-reap marker.** The launcher starts the dedicated daemon with `--dedicated` on argv (and `CLAUDE_HOOKS_DEDICATED=1` in env). `find_all_daemon_processes` skips any peer carrying it. This is the *asymmetric* guarantee the review demanded: it protects the dedicated daemon *from the shared daemon's enforcement*, which a one-directional `--no-enforce-single` flag on the dedicated daemon could not. Read via argv (robust across `/proc` permission boundaries) with `/proc/<pid>/environ` as a fallback.

**Reuse gate untouched.** v2 changes ONLY `enforce_single_daemon` / `find_all_daemon_processes`. `cmd_start`'s reuse gate (cli.py:333-369) and `server._reuse_or_clear_socket` (server.py:618-655) are unchanged — they still reuse a live same-socket incumbent and never unlink a LIVE/INDETERMINATE socket. The "live owner of its own socket is always spared" invariant is preserved verbatim; v2 *additionally* spares different-socket peers.

**Enforcement stays ON** (including in the dedicated daemon, so it reaps its own stale same-socket predecessor on relaunch). Container auto-enable is unchanged — it is now SAFE because identity is `(root, socket)`. This is strictly better than v1's rejected `--no-enforce-single`, which disabled a needed protection.

### Coexistence behaviour matrix (the HARD REQUIREMENT)

| Scenario (container, enforce ON, same root `/workspace`) | Required outcome                                                |
| -------------------------------------------------------- | --------------------------------------------------------------- |
| Shared start, dedicated live (different socket)          | dedicated SURVIVES (v1: killed — the bug) — Layer A + B exclude |
| Dedicated launcher start, shared live                    | shared SURVIVES — Layer A excludes                              |
| Shared restart, STALE shared duplicate (same socket)     | stale duplicate KILLED (Plan 00127 unchanged)                   |
| Two dedicated launchers (two sockets)                    | both SURVIVE — distinct sockets mutually excluded               |
| Bare `cli restart` (no env)                              | targets shared socket only; never touches dedicated             |

This satisfies context.md's HARD REQUIREMENT: a tmux-injection session and N normal sessions coexist on one project; neither daemon reaps the other; a normal session never inherits injection (the `CLAUDE_HOOKS_DEDICATED==1` + token gate at the injector choke point guarantees this).

**This change requires its own hostile review** before merge (flagged in the PLAN header). Spike **S-ENF** is re-scoped to prove *survival under a shared-daemon restart in a real container* (the RED test that must go GREEN), NOT merely "matching is root-only" (which only confirms breakage — review-#2's "spike's green is the design's red" trap).

---

## 4. FATAL-2 — the safe-to-inject predicate (positive, fail-closed)

`inject_once` ANDs four positive assertions; any unavailable / stale / unknown input → **refuse**, never inject.

### 4.1 Human-typing axis (the user's literal question)

- **PRIMARY (positive):** `now - last_human_keypress_epoch >= human_idle_floor_seconds`, where `last_human_keypress_epoch` is written by the tmux key-table hook (§2, S-KEYTABLE). Catches *active typing* by construction.
- **CORROBORATION (paused typist):** the **positive idle-screen-template** asserts the composer interior is empty. Catches the human who typed then paused — the case any keystroke-timing signal clears after its idle floor.

**The empty-box discriminator (heart of the user's seed).** An empty composer is **not blank** — it carries a dim placeholder hint. The discriminator is **SGR-class based**, which is why we capture with `tmux capture-pane -e` (colour-preserving): isolate the composer interior by box-anchor geometry, **strip the contiguous dim/faint-SGR run** (CSI `2m` / low 8-bit grey, per-theme config), and require the remainder empty. A non-empty *normal-foreground* run = human text = defer. Residual fragility stated honestly: a theme rendering the placeholder non-dim mis-classifies it as user-text → fails **closed** (never injects — safe direction). Per-theme placeholder-SGR class is config; unknown theme → fail closed.

### 4.2 Claude-idle axis

- **Daemon idle-latch == idle** (Stop seen, no later `UserPromptSubmit`/`PreToolUse`), from the clean 1:1 event stream.
- **`transcript_path` size/mtime unchanged ≥ N s** (S-TX) as version-stable corroboration of "not streaming".

### 4.3 Hard gates (fail-closed preconditions)

- `pane_in_mode == 0` (copy/menu mode).
- `alternate_on == 0` — NEW hardening: catches a shelled-out full-screen program (`less`/`vim`/a pager launched by node) that `pane_current_command` misses because it stays `node`.
- `pane_current_command ∈ {claude,node}` AND the recorded Claude child PID alive and a descendant of `pane_pid` (SB-3, §5.1).
- `pane_dead == 0`.
- **dialog-open flag == false** (event-driven, §2 corroboration #2).
- `vim_mode != insert` (sidecar field — VERIFIED `vim.mode` exists).
- `pct` freshness ≤ `idle_freshness_seconds`.

### 4.4 The three-state classifier and self-disabling version-resilience

The screen template is a **config-driven positive matcher** (signatures in versioned config, not code — a CC UI change is a config edit). It returns `IDLE` (all positives hold), `BUSY` (a recognised forbidden token: spinner glyph, `esc to (interrupt|cancel)`, menu marker `❯`/numbered options, `-- (NORMAL|INSERT) --`, `Compacting conversation`, red error banner, or a non-empty interior), or `UNKNOWN` (no composer box AND no recognised modal). **Both BUSY and UNKNOWN refuse.**

**Self-disabling on drift:** `UNKNOWN` recurring N consecutive cycles latches the injector into a hard-disabled state for the session with a loud `%WATCH` banner ("CC screen unrecognised — auto-injection disabled; UI likely updated; re-run S-SIG capture"). A CC update thus degrades to *exactly native behaviour* (you compact manually), never to mis-injection — fail-closed containment in its strongest form. The pure classifier function is **fully unit-testable against committed `.ansi`/`.txt` fixtures with zero tmux**, so a signature update is TDD-able in the dev container (closing the SB-8 gap for the predicate's decision logic; only the live capture is host-only).

### 4.5 Two-sample stability + critical-section re-capture (type-right-after-check race)

1. **Stability pre-check:** classify → if `IDLE`, sleep `stability_gap_ms` jitter → re-classify; require **two consecutive `IDLE` with byte-identical interior rows**.
2. **Critical-section final re-capture (load-bearing):** immediately before Enter, re-run the FULL classifier + re-read dialog-flag + idle-latch in the same section. Then: `send-keys -l '/compact'` → **re-capture to confirm `/compact` now sits in the composer interior** (proves it landed in the box, not a modal that ate it) → only then `send-keys Enter`. If the post-type capture does NOT show `/compact`, send `C-u` (kill-line) — never Enter — and abort + log.
3. **Countdown is a gate:** poll interval (`~500ms`) < countdown (`~3s`); each tick re-classifies; one non-`IDLE` tick cancels mid-countdown ("aborted: screen became busy at T-2").

---

## 5. Injector choke-point spec (SB-3..SB-7, TDD-ready)

A tracked package `src/claude_code_hooks_daemon/tmux_inject/` (`injector.py`, `predicate.py`, `ledger.py`, `sidecar.py`, `allowlist.py`). The dedicated daemon NEVER imports it. `inject_once(cmd) -> InjectResult` is the **only** place `subprocess.run([...'send-keys'...])` appears. **CI invariant (dev-container, no tmux):** a source scan asserts `'send-keys'` appears in exactly one file + one line, and `'paste-buffer'`/`'load-buffer'`/`'set-buffer'`/`'TIOCSTI'`/`shell=True` appear NOWHERE. `InjectResult` names the deciding rail so `%WATCH` logs *why it didn't act* as loudly as why it did.

**Ordered fail-closed gate sequence (cheapest→most-expensive):**

1. **Arming gate** — `CLAUDE_HOOKS_DEDICATED == '1'` AND non-empty `CLAUDE_HOOKS_LAUNCH_TOKEN`, else `disabled`. Same code under a shared daemon is inert (FATAL-1 containment).
2. **Abort sentinel** (§ below) — read FIRST and again last.
3. **Allowlist** (SB-6).
4. **Cost ceiling** (SB-5).
5. **Durable cap** (SB-4) — read under flock; reserve the slot only after rails 6-8 pass.
6. **Pane-hosts-this-session rail** (SB-3, §5.1).
7. **Idle composite + dialog flag** (§4) from authenticated sidecar (§5.4) + live tmux.
8. **Critical-section re-validation + send** (§4.5).

### 5.1 Pane rail (SB-3)

Single `display-message`, tab-delimited:

```
tmux display-message -t '%N' -p '#{pane_dead}	#{pane_current_command}	#{pane_pid}'
```

PASS only if ALL hold (else `refused`, rail=`pane`): exit 0 (empty/nonzero → fail-closed); `pane_dead == 0`; `pane_current_command ∈ {claude,node}` (**hard precondition** — fixes "types into a bare shell after Claude exits"); `pane_pid` alive AND `CLAUDE_HOOKS_CLAUDE_CHILD_PID` alive and a descendant of `pane_pid` (walk `/proc/<child>/stat` ppid up to bounded depth — catches a *different* claude/node reclaiming a reused `%N`). Liveness via `os.kill(pid, 0)` (`ProcessLookupError`→dead; `PermissionError`→alive same-uid).

### 5.2 Durable cap (SB-4)

**Key = `sha256(f'{project_root}\x00{git_branch}')[:16]` (`usedforsecurity=False`).** Decision rationale: `transcript_path` REJECTED (churns on `/clear` and is rotated by `/compact` itself — the cap would reset on the very action it governs); `session-name` REJECTED (user-settable, non-unique); `(project_root, git_branch)` ACCEPTED — durable across relaunch and `/clear`, stable through `/compact`; two concurrent same-branch sessions sharing a budget is the SAFE direction (under-injects). Launcher exports `CLAUDE_HOOKS_CAP_KEY`; injector verifies it recomputes (fail-closed on mismatch).

**Ledger:** `untracked/tmux-sessions/ledger/<key>.jsonl` (a SHARED dir, NOT under the per-launch token dir — it must outlive any launch). Rolling-window: config `max_injections` per `window_seconds`; drop rows older than the window, refuse if remainder `>= max`. **Atomicity:** read-modify-write under exclusive `flock` on `<key>.lock`, spanning read→count→decide→append→fsync→`os.replace` of a temp file, so two same-branch injectors cannot both pass. **Launcher reads the ledger on startup** and starts `disabled` with a banner if already at cap. **RED test:** inject to cap → SIGKILL injector+launcher → relaunch → next `inject_once` returns `refused` rail=`cap` (dev-container testable — no tmux).

### 5.3 Mandatory cost ceiling (SB-5)

`max_total_cost_usd` is REQUIRED when armed; launcher refuses to arm (starts `disabled`) if absent or `<= 0` — no default-infinite. Enforced at the injector (rail 4, latched-disabled once tripped, never retried) AND an independent launcher deadman loop. Documented as **LAGGING**: `cost.total_cost_usd` arrives only on the debounced Status event, stalest during the heaviest turn; sidecar records cost + `mtime`; a reading older than `cost_freshness_seconds` → `refused` rail=`cost-stale` (never inject on a stale all-clear). Wall-clock deadman is a BACKSTOP (bounds time, not dollars).

### 5.4 Authenticated sidecar (SB-7)

The dedicated daemon's observe-only status handler WRITES it; the injector READS it. The token is an IDENTIFIER, never an authenticator (S-PANE proves any same-uid process reads `CLAUDE_HOOKS_LAUNCH_TOKEN` from `/proc/<pid>/environ`). Path `untracked/tmux-sessions/<token>/sidecar.json`; launcher creates the dir `os.mkdir(path, 0o700)` failing if it exists; reader `os.open(..., O_NOFOLLOW)` and `os.fstat`s the fd (TOCTOU-safe). Contents: `{writer_pid, seq, mtime, pct, total_cost_usd, idle_latch, dialog_open, vim_mode, session_id}`, written atomically (temp + `os.replace`) each Status event. **Reader auth (any mismatch → `refused` rail=`sidecar`):** `st_uid == getuid()`, regular file, dir mode `0o700`; **`writer_pid` == the dedicated-daemon PID read via `CLAUDE_HOOKS_PID_PATH`** (VERIFIED honoured at paths.py:1167); **monotonic `seq`** (in-memory last-seen; backwards = replay → refuse); **freshness** `now - mtime <= idle_freshness_seconds`. A forged `pct=99,idle,dialog_open=false` from a random same-uid process has the wrong `writer_pid` and cannot outrun the genuine writer's `seq`.

### 5.5 Abort sentinel + re-arm failure branch

**Abort:** `untracked/tmux-sessions/<token>/ABORT` exists = stop. Launcher binds `prefix+I` → `run-shell 'touch <abort>'`. Invariant `poll_seconds < countdown_seconds`. On abort → `disabled`, banner, loop exits (no busy-loop). **Re-arm latch:** after an injected `/compact`, wait for a sidecar reading with `pct` below threshold AND `mtime` after the injection's ledger `ts`. If within `rearm_timeout_seconds` no below-threshold post-injection `pct` arrives (user cancelled the dialog, `/compact` errored, pct didn't drop) → distinct **loudly-surfaced `disabled`** state ("compact did not reduce context — injection DISABLED; re-arm manually"). Never silently wedges, never retries into the cap, never busy-loops.

### 5.6 Allowlist (SB-6)

**v1 closed set = exactly `{'/compact'}`.** `validate(cmd)`: (1) membership `cmd.strip() in frozenset({'/compact'})` — primary gate, a set test not a regex; `/clear`/`/quit`/`/exit`/custom commands fail here; (2) **argument ban** — reject any whitespace after the slash token (bare commands only — kills the v1 `( ...)?` arg group that smuggled attacker text); (3) secondary shape `^/[a-z][a-z0-9_-]*$`; (4) control-char ban (`< 0x20` or `0x7f`). Send invariant: `send-keys -t <pane> -l <cmd>` (`-l` ALWAYS so `#`/`!`/`;` are literal) then a SEPARATE `send-keys -t <pane> Enter`.

### 5.7 TDD coverage map

Dev-container (no tmux) tests EVERYTHING except two rails: allowlist, durable cap + relaunch RED test, sidecar auth (synth files + fake PID file), cost ceiling + stale, abort + poll\<countdown, single-call-site/banned-primitive scan, and the **predicate's decision logic against `.ansi`/`.txt` fixtures**. Only the **pane rail (real pane / exit-to-shell / id-reuse)** and the **critical-section send + `-l` invariant + capture-confirm** genuinely need the CI tmux harness — five of seven safety-critical rails are dev-container-testable, closing SB-8 for all but the irreducibly tmux-dependent send.

---

## 6. Launcher + dual-daemon lifecycle + CI tmux harness (SB-8 / SB-9)

### 6.1 Launcher `scripts/.../claude-tmux.sh`

Bundled template at `src/claude_code_hooks_daemon/install/templates/claude-tmux.sh` (wheel package-data), deployed by `_deploy_claude_tmux()` mirroring `install/plan_workflow.py:_deploy_mkplan()` (read_text → write into client `.claude/tmux/claude-tmux.sh` → `chmod 0755` → record in `BootstrapResult.messages`); **overwrite on every upgrade** (daemon-owned tooling, audit/security fixes must reach the field). Deploy under the client `.claude/` tree, NOT `.claude/hooks-daemon/` (daemon_location_guard forbids `cd`-ing there).

Flags: `--dry-run` (DEFAULT; injector disarmed, prints `WOULD inject /compact`); `--arm` (opt-in; HARD-refuses without `--max-cost`); `--threshold N` (`1<=N<=95`); `--max-cost USD` (MANDATORY with `--arm`); `--max-wall-clock SECONDS` (finite default, never infinite); `--window N` + `--max-injections N`.

**Nested-tmux precondition (FATAL-1 Finding 4):** if `$TMUX` set → REFUSE by default; `--isolated-server` opt-in runs on a private `tmux -L cchd-<token>` server (which ALSO satisfies the key-table requirement of §2 — custom `root`-table bindings must not leak into the user's other sessions — so the private server is **mandatory whenever the key-table primary signal is active**). Every tmux call threads the same `-L`.

**Pane-id capture (VERIFIED primitives):** `CLAUDE_PANE=$(tmux ... display-message -t "$SESSION" -p '#{pane_id}')`; `WATCH_PANE=$(tmux ... split-window -P -F '#{pane_id}')` — `%N` ids survive reflow. **Token (no `uuidgen` in-container):** `od -An -N16 -tx1 /dev/urandom | tr -d ' \n'`, fallback `python3 -c 'import secrets;print(secrets.token_hex(16))'`, fail-closed if neither. **Session dir:** `mkdir -m 700` (fails if exists), no-symlink check (resolve + compare; `realpath` portability is a macOS-floor spike). Record Claude's child PID, the daemon's `version.py` + git HEAD (`daemon.meta`), and the chosen `-L` arg.

### 6.2 Dual-daemon lifecycle (SB-9) — VERIFIED already socket-aware

Every lifecycle command resolves through `_resolve_socket_path(args, project_path)` / `_resolve_pid_path` (cli.py:289-303 / 272-286): precedence **explicit `--socket`/`--pid-file` > env (`CLAUDE_HOOKS_SOCKET_PATH`/`PID_PATH`) > project default**. `cmd_status`/`cmd_stop`/`cmd_logs` (cli.py:552-554/616-618/653-655) consume them. **So dual-daemon disambiguation needs ZERO new CLI surface** — the operator/launcher targets the dedicated daemon by env or `--socket`/`--pid-file`. Remaining gaps: (a) confirm `cmd_check` (cli.py:849) / `health` thread the same resolver (one read to verify); (b) optional ergonomic `--session-dir DIR` expanding to the three paths.

**Dogfooding stale-code rule (document loudly):** the dedicated daemon is pinned to launch-time code; a developer running bare `cli restart` restarts ONLY the shared daemon, leaving the dedicated one on stale code. Mitigations: launcher writes resolved version + git HEAD to `daemon.meta`; `cli status --session-dir <token>` prints the pinned revision (makes staleness observable); document that dedicated sessions are for *using* injection, not *developing handler code* — develop against the shared daemon, then relaunch.

**Orphan janitor — in the SHARED daemon's startup sweep** (reuses the `startup_cleanup` 🧹 indicator pattern, handlers/status_line/startup_cleanup.py): sweep `untracked/tmux-sessions/*`; for each token dir, read `daemon.pid`; if dead/missing AND dir mtime older than a grace window, remove it. **NEVER touch a dir whose `daemon.pid` is live** (a running dedicated session — the coexistence case). This keeps orphan reaping in the always-present shared daemon, preserving Plan 00127's single-owner cleanliness (which removed the daemon orphan path — the launcher re-introduces the orphan class, so the janitor reconciles it).

### 6.3 CI tmux harness (SB-8)

`tests/integration/test_tmux_injection_harness.py` + acceptance-tier `tests/acceptance/test_tmux_send_keys_invariants.py`, module-level skip when `shutil.which("tmux") is None` (dev container skips; CI installs tmux). Each test spawns a real private-server session (`tmux -L cchd-test-<pid>`) and tears it down (`kill-server`). RED matrix: allowlist closed-set (dev-container); `-l` + single-call-site + banned-primitive scan (dev-container); fail-closed on unknown screen (predicate vs fixture buffers — dev-container; real capture host-only); pane-current-command mismatch incl. exit-to-shell (real tmux); cap survives relaunch (dev-container); sidecar auth mismatch (dev-container). The H-1 acceptance test (allowlist + `-l`/single-site/banned-primitive invariants) is added to RELEASING.md Step 12.0 so every release re-asserts them — the regression guarantee a one-time host spike cannot give.

---

## 7. Smallest buildable v1 + roadmap

**v1 = "watch-along custom-threshold `/compact`, dry-run-first, coexisting with normal sessions."**

1. Socket-aware enforcement (Layer A + B, §3) — **built and hostile-reviewed FIRST**; it is the HARD-REQUIREMENT gate and is dev-container/CI-testable without tmux (synthetic cmdlines + a real two-`cli-start` container fixture for the survival rows).
2. The dedicated observe-only status handler writing the authenticated sidecar (§5.4).
3. The `tmux_inject` package (§5) — allowlist hard-defaulted to `/compact`, durable cap, fail-closed predicate, single `send-keys` site.
4. The launcher (§6.1) — two panes on a private server, disarmed injector, visible countdown.
5. The CI tmux harness (§6.3) + H-1 invariants.

The FATAL-2 primary signal (key-table vs screen-template vs ARCH-B) is selected by the Phase-0 spikes (§8) BEFORE the injector send path is wired — but the cap/sidecar/allowlist/enforcement work is independent of that selection and proceeds in parallel.

**Roadmap (ordered):** (1) PostCompact re-orientation prompt with the re-arm latch + a defined ledger reader; (2) status-segment armed/off indicator + `prefix+I` polish; (3) generalised slash-command allowlist (only after the closed `{'/compact'}` set proves safe in the field); (4) `/fix`-on-failure ONLY on field demand, drain-when-idle, never on Stop. **Permanently CUT:** session-bootstrap (CLAUDE.md/`--append-system-prompt` owns it), scheduled injection (`/loop` owns it), notification stall-nudge (dialog danger zone), daemon-managed no-pane controller (trades away the watchability that is the point).

---

## 8. Phase-0 spike gate (go/no-go on the FULL architecture)

Build nothing in the send path until these pass; fail-closed where unproven. tmux is absent in the dev container (VERIFIED) — all tmux/PTY spikes run on a real host.

| Spike                           | Make-or-break?                                                                                                                                                                                                                                                                                                                                            | If it FAILS, fall back to…                                                                                                                                                                                                                                                                                                                                |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **S-KEYTABLE** (NEW, run FIRST) | **YES — selects the FATAL-2 spine.** Does a per-keypress tmux *hook* (Candidate C, observe-only) exist on the host's tmux, and does it stamp every key WITHOUT dropping any key into Claude?                                                                                                                                                              | Candidate C passes → **key-table = PRIMARY human signal; client_activity dropped; S-ACT downgraded to optional.** Only Candidate B (enumerated bind, in delivery path) AND any key dropped → **key-table REJECTED → ARCH-B.** B lossless-but-fragile → ship behind a launcher startup self-test (probe-string round-trip) that refuses to arm on failure. |
| **S-SIG**                       | **YES.** Capture real bottom-band signatures (empty box, typed, paused-typed, spinner, permission dialog, MCP/trust modal, vim NORMAL/INSERT, error, `/compact` progress, post-compact) across the user's themes; distil into the positive idle-template config; confirm `capture-pane -e` SGR encoding can classify placeholder-dim.                     | Positive whole-screen template (fixtures committed, classifier unit-tested). Placeholder-dim unclassifiable → per-theme literal-string strip → then **cap+cooldown-only, fail-closed on any non-empty band**, leaning on the dialog-open flag for modals.                                                                                                 |
| **S-ENF** (re-scoped)           | **YES.** In a real container with `enforce_single_daemon_process: true`: dedicated daemon SURVIVES a shared-daemon restart (the RED→GREEN test); shared survives a dedicated restart; stale same-socket duplicate IS reaped; two dedicated sockets coexist; `/proc/<pid>/cmdline` (A) or `/environ` (B) carries the discriminating token cross-namespace. | No survival → no build. Sub-spike S-ENF-OBS picks argv `--socket-path` (A1) vs discovery-file (A2) by cross-namespace readability.                                                                                                                                                                                                                        |
| **S-PANE**                      | YES (cheap), DOUBLE-EDGED. Env reaches `/proc/<pid>/environ`; `#{pane_id}` survives detach/reattach.                                                                                                                                                                                                                                                      | Will pass; its success PROVES the token is readable by any same-uid process → token is an identifier, never a secret (drives SB-7).                                                                                                                                                                                                                       |
| **S-PTY** (ARCH-B gate)         | YES *if* ARCH-B is selected. `pty.spawn(["claude"])`: clean termios restore on Claude SIGKILL; correct SIGWINCH forwarding; `isatty()` true and TUI renders identically (S-ISATTY); supervisor reads `pct` without a dedicated daemon (S-PCT, e.g. statusLine sidecar).                                                                                   | If pty fidelity is broken on the target platform → stay on ARCH-A; if ARCH-A FATAL-2 also fails → companion-script floor (cap+cooldown, fail-closed).                                                                                                                                                                                                     |
| **S-CACHE**                     | MUST. Does an *injected* `/compact` produce a guardable `PreCompact`/`PostCompact`; do `stop`/`status` honour `CLAUDE_HOOKS_PID_PATH`.                                                                                                                                                                                                                    | Re-arm latch leans on the `pct`-drop heuristic + the §5.5 failure branch.                                                                                                                                                                                                                                                                                 |
| **S-TX**, **S-ENTER**           | SHOULD. Transcript incremental-append; capture-confirm-then-Enter timing.                                                                                                                                                                                                                                                                                 | Corroboration / replace `sleep 0.3` with the capture-confirm closed loop.                                                                                                                                                                                                                                                                                 |

**Decisive ARCH-A → ARCH-B abandonment rule:** if **S-KEYTABLE yields no observe-only per-key signal (Candidate C fails) AND S-SIG cannot give a positive fail-closed template**, ARCH-A has no positive human-typing answer for the one feature whose entire risk is mis-injection — **abandon ARCH-A and build ARCH-B** (PTY supervisor + `pyte` positive whole-screen template), which dissolves SB-2 and SB-3 by construction and — by reading `pct` via a statusLine sidecar instead of a dedicated daemon — also dissolves SB-1/SB-9 (no second daemon; shared daemon untouched; coexistence trivial). ARCH-B is *more* CI-testable than ARCH-A (`pty.openpty` needs no display). Keep the companion-script floor (cap+cooldown, fail-closed, `/compact`-only) as the no-PTY fallback of last resort.

---

## 9. Honest residual risks (after all fixes)

1. **Screen-template / placeholder-dim is the single most theme-fragile element.** It fails closed (never injects) on drift, but a CC release that restyles the composer silently disables the paused-typist catch until S-SIG is re-run. The three-state self-disabling classifier contains this to "degrades to native manual compaction," not "mis-injects" — but the maintenance burden is real and recurring.
2. **Cost ceiling remains a LAGGING bound.** `cost.total_cost_usd` arrives only on the debounced Status event and is stalest precisely during a runaway turn. The ceiling must be set conservatively; the wall-clock deadman bounds time, not dollars. This is the weakest rail on the actual-harm (spend) axis even after being made mandatory.
3. **Socket-aware enforcement is a Plan 00127-invariant change.** Layer A narrows-never-widens (provably cannot orphan), but cross-PID-namespace `/proc/<pid>/cmdline` readability under bind-mounted containers is the same class of concern Plan 00127's flock note raises — it MUST clear its own hostile review and the S-ENF container survival test before merge.
4. **The injector's two irreducibly-tmux rails** (live send + pane identity) depend on the CI tmux harness staying green across tmux versions; a tmux behaviour change (e.g. `send-keys -l` or `display-message` format drift) is invisible to the dev container and surfaces only in CI.
5. **If S-KEYTABLE Candidate C does not exist** and we fall to ARCH-B, the cost is a launch-command change (`claude-supervise` not `claude`) and a hardened termios-restore-on-crash path (R1) — a wedged operator terminal on an unclean supervisor death is bounded and well-trodden but real.

**The single biggest residual risk:** **the FATAL-2 "is the screen safe to type into?" gate is ultimately heuristic on ARCH-A** — even with the positive key-stamp + positive screen-template + dialog flag ANDed fail-closed, a Claude Code modal class that emits no hook event AND renders no recognised signature would be classified `UNKNOWN` (refuse) — which is safe — but the *guarantee* that we never type into a live human prompt rests on the key-stamp spike (S-KEYTABLE) landing its observe-only form. If it doesn't, only ARCH-B closes this by construction. **The entire architecture decision hinges on S-KEYTABLE.**
