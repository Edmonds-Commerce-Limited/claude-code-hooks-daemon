# Plan 00127: Parallel-Session Daemon Isolation & Reuse (+ LXC detection)

**Status**: In Progress
**Created**: 2026-06-17
**Owner**: Claude (Opus)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration
**Type**: Bug Fix + Feature (detection)

## Overview

Two or more Claude Code sessions running against the same codebase can cause one
session's hooks daemon to go down while the other keeps working. The investigation
(see `context.md`) identified two compounding failure modes — a "socket theft /
PID clobber" path that is **always active**, and an `enforce_single_daemon`
"kill" path that is active in containers with enforcement on. Both stem from the
same root cause: when two sessions legitimately share `(hostname, project root)`,
the daemon treats the incumbent as a competitor to displace/kill instead of a
**shared daemon to reuse**.

This plan also adds robust **LXC/LXD container detection**, which the current
honest-marker detector misses on modern (cgroup v2) hosts.

This is a dogfooding fix: the bug is reproduced **live in this very container**
(two daemon servers, PIDs 272 & 274, same project root, one PID file).

## Goals

- Parallel sessions sharing one `(hostname, project root)` **reuse a single
  healthy daemon** instead of fighting over the socket/PID.
- A second daemon start against a **live** socket **fails fast** (or reuses) —
  never silently unlinks a healthy incumbent's socket.
- `enforce_single_daemon` never kills a healthy incumbent that the cheap
  "already running" check would have accepted.
- Orphaned daemon processes / stale runtime files are detected and reaped safely.
- LXC/LXD containers are reliably detected (env var, marker files, cgroup v1+v2).
- Full regression coverage; QA green; daemon restarts cleanly.

## Non-Goals

- Re-litigating the desktop-vs-container separation (Plan 00126) — that is
  believed correct and is out of scope except where it intersects.
- Changing the hostname-isolation scheme itself (one socket per hostname+root
  stays the model; we fix how contention over it is handled).
- Forcing per-session sockets by default (a shared daemon is the *desired*
  outcome for same-root sessions; per-session isolation stays an opt-in via the
  existing `CLAUDE_HOOKS_*_PATH` env overrides).

## Context & Background

See `context.md` for the full investigation, the two mechanisms with file:line
references, live evidence, and the 2026-05-29 prior incident
(`untracked/hooks-daemon-failed.md`). Key code sites:

- `src/claude_code_hooks_daemon/daemon/server.py` (~343-346 socket unlink, ~759
  PID overwrite) — Mechanism B.
- `src/claude_code_hooks_daemon/daemon/cli.py` (~300-365 `cmd_start` ordering) —
  Mechanism A enabler.
- `src/claude_code_hooks_daemon/daemon/enforcement.py` — single-daemon enforcement.
- `src/claude_code_hooks_daemon/daemon/process_verification.py` — process matching.
- `src/claude_code_hooks_daemon/daemon/paths.py` (~73-108 hostname, ~167-200 venv
  fingerprint).
- `.claude/init.sh` (~307-325 hostname suffix, ~505-595 start guard).
- `src/claude_code_hooks_daemon/utils/container_detection.py` — LXC gap.

## Tasks

### Phase 1: Reproduce & characterise (mostly done)

- [ ] ⬜ **Task 1.1**: Capture the live two-daemon state (PIDs 272/274) as a
  reproduction fixture description before any cleanup. Record `ps`, socket
  listing, and which PID the `.pid` file holds.
- [ ] ⬜ **Task 1.2**: Confirm via the live socket which PID actually answers
  hook dispatch (`nc`/forwarder probe), proving the other is orphaned.
- [ ] ⬜ **Task 1.3**: Write the precise reproduction as a docstring for the new
  regression tests (same root + same hostname → second start must NOT orphan
  the first).

### Phase 2: Fix Mechanism B — fail-fast on a live socket (TDD)

- [ ] ⬜ **Task 2.1**: RED — test that a second daemon server start, when a
  **live** daemon owns the socket, does NOT unlink the socket and exits
  non-zero (or cleanly defers), leaving the incumbent's socket intact.
- [ ] ⬜ **Task 2.2**: RED — test that a genuinely **stale** socket (connect
  refused, dead PID) IS still cleaned up and the new daemon binds.
- [ ] ⬜ **Task 2.3**: GREEN — in `server.py`, before unlinking, probe socket
  liveness (attempt connect, and/or verify the PID file points at a running
  process). Live → do not steal; stale → unlink and bind. Replace the
  unconditional PID overwrite with the same liveness gate.
- [ ] ⬜ **Task 2.4**: REFACTOR — extract a `_socket_is_live(path)` helper;
  named constants for log messages; no magic strings.

### Phase 3: Fix Mechanism A — reorder `cmd_start` & spare the incumbent (TDD)

- [ ] ⬜ **Task 3.1**: RED — test that when a healthy same-root daemon is
  already running, `cmd_start` returns success and `enforce_single_daemon` is
  NOT invoked (incumbent untouched).
- [ ] ⬜ **Task 3.2**: GREEN — reorder `cmd_start`: run the "already running &
  healthy" check before `enforce_single_daemon`; short-circuit to reuse.
- [ ] ⬜ **Task 3.3**: GREEN — make `enforce_single_daemon` skip a healthy
  incumbent that owns our own socket/PID (shared daemon, not competitor);
  keep killing only genuinely stale/duplicate peers.
- [ ] ⬜ **Task 3.4**: Consider atomic PID acquisition (O_EXCL / `flock`) in
  `init.sh` + `server.py` so two concurrent starts cannot both proceed; the
  loser reuses the winner. Spike first, decide in a Technical Decision.

### Phase 4: LXC / LXD detection (TDD)

**Real signals captured on host-a (unprivileged LXC, cgroup v2):** only
`systemd-detect-virt --container` → `lxc` worked; the `container` env var was
unset, `/proc/1/environ` was root-only, no marker files existed, and
`/proc/1/cgroup` was `0::/init.scope` (no token). See `context.md` "Real LXC
signals captured" for the full table and the resulting priority-ordered design.

- [ ] ⬜ **Task 4.1**: Add `lxc` and `lxc-libvirt` to `_CONTAINER_ENV_RUNTIMES`
  (decide `_RUNTIME_LXC` vs `generic` in a Technical Decision). Cheapest check.
- [ ] ⬜ **Task 4.2**: RED+GREEN — read **`/run/systemd/container`**
  (env-overridable `HOOKS_DAEMON_SYSTEMD_CONTAINER_PATH`), the world-readable
  systemd file that contains `lxc`. **Pending confirmation it exists on host-a**
  — if confirmed, this is the preferred LXC check (cheap, no subprocess, matches
  the existing marker-file pattern).
- [ ] ⬜ **Task 4.3**: RED+GREEN — `systemd-detect-virt --container` subprocess as
  the **authoritative fallback** when cheap checks find nothing. Trusted system
  tool, list args, no `shell=True` (per the project subprocess security rules);
  exit 0 + stdout token = container, non-zero/`none` = host. Confirmed to return
  `lxc` non-root on host-a.
- [ ] ⬜ **Task 4.4**: Optionally probe LXD via `/dev/lxd/sock` / `/dev/.lxc`
  (absent on host-a but present on some LXD setups), env-overridable.
- [ ] ⬜ **Task 4.5**: Keep the existing `lxc` cgroup token for cgroup-v1 hosts.
- [ ] ⬜ **Task 4.6**: Ensure `environment_indicator` status handler renders an
  LXC icon, and `yolo_container_detection` recognises LXC.
- [ ] ⬜ **Task 4.7**: Reassess whether LXC should auto-enable
  `enforce_single_daemon_process` — only AFTER Phases 2-3 land, since enabling it
  before the reuse/fail-fast fix would re-expose Mechanism A.

### Phase 5: Orphan / stale-runtime janitor (TDD)

- [ ] ⬜ **Task 5.1**: RED+GREEN — on start, detect the "two server PIDs, one
  socket" state and reap the orphan **only when safe** (same project root,
  dead/removed socket). Never touch a different project root's daemon.
- [ ] ⬜ **Task 5.2**: Clean stale `daemon-*.{pid,sock,socket-path}` whose PID is
  dead — but only for entries we can positively attribute to this root.
- [ ] ⬜ **Task 5.3**: Decide whether to surface a session-start health warning
  when an orphan/stale state was found and reaped (advisory handler).

### Phase 6: Docs, QA, daemon verification

- [ ] ⬜ **Task 6.1**: Update CLAUDE.md / SELF_INSTALL / hostname-isolation docs
  to describe shared-daemon reuse and the `CLAUDE_HOOKS_*_PATH` opt-out for
  genuinely-shared `untracked/`.
- [ ] ⬜ **Task 6.2**: Add a truth-changes entry if any documented behaviour
  changes (e.g. "second start steals socket" → "second start reuses/fails").
- [ ] ⬜ **Task 6.3**: Run `./scripts/qa/llm_qa.py all` (or `run_all.sh`) — all
  checks green.
- [ ] ⬜ **Task 6.4**: Restart daemon, verify RUNNING; confirm the live
  two-daemon orphan state is resolved.
- [ ] ⬜ **Task 6.5**: Add/extend H-1 acceptance coverage for the
  parallel-start scenario if feasible.

## Dependencies

- Related: Plan 00126 (container detection), 00124/00100 (venv keying),
  00118/00119 (single-daemon enforcement scoping).
- Blocks: none currently.

## Technical Decisions

### Decision 1: Reuse vs. fail-fast for a same-root live socket

**Context**: Two sessions, same `(hostname, root)`. Options:

1. **Reuse** — second start detects the live daemon and exits 0; both sessions'
   forwarders talk to the one daemon (the intended model).
2. **Fail-fast** — second start exits non-zero, forwarder reports clearly.
3. **Per-session sockets** — isolate by default.

**Leaning**: (1) reuse as the default (it is the desired shared-daemon outcome),
with (2) fail-fast as the safety net when the socket is ambiguous, and (3)
remaining an opt-in via `CLAUDE_HOOKS_*_PATH`. **Decision: TBD — confirm with user.**

### Decision 2: LXC runtime label

**Context**: Add a distinct `_RUNTIME_LXC = "lxc"` vs. folding into `generic`.
**Leaning**: distinct label for an accurate status-line icon and clearer logs.
**Decision: TBD.**

## Success Criteria

- [ ] Two parallel same-root sessions both have a working daemon (shared), or the
  second fails fast with a clear message — never a silent orphan.
- [ ] A stale socket is still cleaned up correctly (no regression to normal
  single-session start/restart).
- [ ] `enforce_single_daemon` never kills a healthy incumbent.
- [ ] LXC/LXD detected on cgroup v1 AND v2 hosts (verified against real signals).
- [ ] Live orphan state in this container resolved after the fix.
- [ ] QA all green; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                | Impact | Probability | Mitigation                                                               |
| --------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------ |
| Liveness probe false-negative unlinks a live socket | High   | Low         | Probe by connect AND PID-alive; only unlink on both-stale                |
| Reuse model masks a genuinely wedged daemon         | Med    | Med         | Health-check the incumbent before reuse; fail-fast if unhealthy          |
| LXC probes need root (`/proc/1/environ`)            | Med    | Med         | Treat unreadable as "no signal"; rely on env var + `/dev/lxd/sock` first |
| Janitor reaps a different project's daemon          | High   | Low         | Strict same-root attribution; fail-safe leave-running                    |

## LXC debug commands (for the user to run INSIDE a real LXC/LXD container)

Run these inside an LXC/LXD container and paste the output back so detection can
be designed against real signals (we have no LXC environment here):

```bash
# 1. The 'container' env var (LXD typically sets container=lxc)
echo "container env (shell): '${container:-UNSET}'"
# PID 1's view (most reliable; needs root):
sudo tr '\0' '\n' < /proc/1/environ 2>/dev/null | grep -i '^container=' || echo "  (/proc/1/environ: unreadable or no container=)"

# 2. Marker files
ls -la /.dockerenv /run/.containerenv /dev/lxd/sock /dev/.lxc 2>&1

# 3. cgroup (v1 shows /lxc/...; v2 shows just 0::/)
echo "--- /proc/1/cgroup ---"; cat /proc/1/cgroup
echo "--- /proc/self/cgroup ---"; cat /proc/self/cgroup
echo "cgroup version:"; stat -fc %T /sys/fs/cgroup 2>/dev/null   # cgroup2fs = v2, tmpfs = v1

# 4. systemd's own detector (authoritative when present)
command -v systemd-detect-virt >/dev/null && systemd-detect-virt --container || echo "systemd-detect-virt: not installed"

# 5. Misc corroborating signals
echo "hostname: $(hostname)"
cat /proc/1/comm 2>/dev/null
mount 2>/dev/null | grep -iE 'lxc|lxd' || echo "  (no lxc/lxd mounts visible)"
```

What we expect to learn:

- Whether `container=lxc` is reliably present (env and/or `/proc/1/environ`).
- Whether `/dev/lxd/sock` (LXD) or `/dev/.lxc` exist.
- What `/proc/1/cgroup` looks like on the host's cgroup version (does the `lxc`
  token survive on cgroup v2, or do we need the env/marker fallbacks?).
- Whether `systemd-detect-virt --container` is available and returns `lxc`.

## Notes & Updates

### 2026-06-17

- Plan created. Opus review agent confirmed two mechanisms; live two-daemon
  orphan state observed in this container (PIDs 272/274, one PID file).
- `context.md` written with full investigation. LXC detection gap identified
  (cgroup-v2 misses LXC; `container=lxc` not mapped; no LXD marker probe).
- Fixes NOT yet implemented — awaiting user direction on Decision 1 (reuse vs.
  fail-fast) and LXC debug output.
