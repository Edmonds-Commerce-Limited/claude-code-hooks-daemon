# Context: Parallel Claude Code Sessions vs. the Hooks Daemon

**Plan**: 00127
**Status**: Investigation written; fixes not yet implemented
**Audience**: anyone picking up this plan

## The general problem

This daemon is increasingly run in environments where **two or more Claude Code
sessions operate against the same codebase at the same time**:

- Two YOLO/Podman containers launched against the same project.
- A desktop/host session AND a container session sharing a **bind-mounted**
  project directory (and therefore a shared `untracked/` runtime directory).
- Two agents/sessions inside the **same** container.

Over the last several releases we deliberately hardened the daemon's
**desktop-vs-container separation**:

- **Honest container detection** (Plan 00126 / v3.20.0) — `utils/container_detection.py`
  no longer mis-classifies every desktop Claude Code session as a container.
- **Venv keying by project-path slug + fingerprint** (Plan 00124 / v3.19.1,
  Plan 00100) — a host view (`/home/user/project`) and a container view
  (`/workspace`) of the *same* bind-mounted project no longer collide on one venv.
- **Container uv link-mode** (Plan 00125 / v3.19.2).
- **Project-root-scoped single-daemon enforcement** (Plans 00118/00119 / v3.18.x)
  — in a container, daemon-start kills *other* daemons serving the **same**
  project root, but leaves daemons serving *different* roots alone.

That desktop/podman separation work is believed largely correct. **This plan is
about the issues we may have left open — or introduced — in the
parallel-same-project case.**

## The symptom the user reported

> "One agent had the hooks daemon working, but another one did not."

Two parallel sessions on the same codebase; one session's hooks fire normally,
the other reports the daemon as unreachable (`daemon_startup_failed` /
`socket_not_found`).

## What the investigation found (Opus review + live evidence)

There are **two distinct, compounding failure modes**. Both require the two
sessions to resolve the **same hostname AND same project root**, so they share
one `untracked/daemon-{hostname}.{sock,pid}` triple. (Two *separate* containers
get different hostnames — the container ID — so they do NOT collide. Collision
needs same-container, or a host+container sharing a bind-mounted `untracked/`
where the resolved hostname matches.)

### Mechanism A — `enforce_single_daemon` SIGTERM/SIGKILL ("the kill path")

Only active when ALL hold:

1. `daemon.enforce_single_daemon_process: true` (default False; auto-enabled by
   `init` when a container is detected).
2. `is_container_environment()` is True.
3. Another process matches `_is_daemon_server_process`
   (`daemon/process_verification.py`).
4. That process's derived project root **equals** this start's `--project-root`.

The v3.18.x scoping work intentionally **kept same-project-root daemons
killable** — it only spared *different*-root daemons. So for two sessions on the
same root in a container with enforcement on, session B's start SIGKILLs session
A's daemon. Worse, `cmd_start` runs `enforce_single_daemon` **before** the cheap
"already running and healthy" check (`daemon/cli.py`), so a perfectly healthy
incumbent is killed before the check that would have aborted.

### Mechanism B — socket theft + PID clobber ("the displace path")

**Always active**, regardless of config flags or container detection. When a
second daemon server starts on the same socket path
(`daemon/server.py` ~lines 343-346) it **unconditionally unlinks the existing
socket** ("Removing stale socket") and later **overwrites the PID file**
("Daemon already running with PID %d, overwriting"). There is no live-socket
probe and no bind-conflict guard. Result: the newcomer steals the socket path;
the incumbent keeps running but is **orphaned** (its socket file removed out from
under it); the PID file now points at the newcomer. One session's hooks reach a
live daemon, the other talks to a stale/removed socket — exactly the reported
symptom.

### Live evidence in THIS container (2026-06-17)

```
PID 272  PPID 1  ... daemon.cli --project-root /workspace start
PID 274  PPID 1  ... daemon.cli --project-root /workspace start
untracked/daemon-c2ab9545bc27.pid  → (one PID only)
```

Two fully-daemonised server processes, same project root, one PID file. This is
Mechanism B reproduced empirically, no setup required.

### Prior incident (2026-05-29) — `untracked/hooks-daemon-failed.md`

A host session lost its daemon mid-session while a container shared the host's
bind-mounted `untracked/`. Root cause then was the same family: shared runtime
directory + cross-instance interference (idle-timeout self-exit at
`idle_timeout_seconds: 600` and/or container single-daemon enforcement reaching
a host-visible PID). That report's prevention advice (stop sharing `untracked/`;
use `CLAUDE_HOOKS_SOCKET_PATH`/`PID_PATH`/`LOG_PATH` overrides; raise idle
timeout; on-disk logging; session-start health check) remains relevant.

## Root cause, plainly stated

The daemon's runtime identity is **(hostname, project root) → one socket/pid in
`untracked/`**. When two sessions legitimately share that identity, the code
treats the incumbent as a competitor to displace/kill rather than a **shared
daemon to reuse**. Same project root + same socket should mean "reuse the one
daemon", not "fight over it".

## Venv keying is (mostly) a red herring for THIS symptom

Two parallel sessions with the same interpreter resolve to the **same** venv,
which is fine for reads. A rebuild fight only happens immediately after an
upgrade/lock change (`ensure_venv` is short-circuited when the lock-hash
matches). The v3.19.1 slug fix correctly separates *host vs container path*
views. Venv contention is a secondary, lower-probability contributor, not the
main cause of "one daemon up, one down".

## The LXC detection gap (second user request)

The user also wants to detect when we're running inside an **LXC/LXD** container.
The current `detect_container_runtime()` (`utils/container_detection.py`) checks,
in order:

1. `container` env var → mapped via `_CONTAINER_ENV_RUNTIMES`
   (`podman`/`docker`/`oci`/`crio`) — **`lxc` is NOT in this map**.
2. `/.dockerenv` (Docker) — absent in LXC.
3. `/run/.containerenv` (Podman) — absent in LXC.
4. `/proc/1/cgroup` token scan — includes an `lxc` token, **but** on cgroup v2
   `/proc/1/cgroup` is just `0::/` with no runtime token, so this misses modern
   LXC/LXD.

So LXC is currently only caught on cgroup-v1 hosts, and even then only when the
cgroup path carries an `lxc` segment. **Gaps to close:**

- Map `container=lxc` (and `lxc-libvirt`) in `_CONTAINER_ENV_RUNTIMES`.
- Add LXC/LXD marker probes: `/dev/lxd/sock` (LXD), `/dev/.lxc`,
  `/proc/1/environ` containing `container=lxc` (readable as root).
- Optionally consult `systemd-detect-virt --container` when present (returns
  `lxc` / `lxc-libvirt`).

We are NOT in an LXC container in this environment, so detection must be designed
against signals gathered from a real LXC/LXD container — see the debug commands
in PLAN.md Phase 4. Marker paths must be env-overridable (mirroring the existing
`HOOKS_DAEMON_*_PATH` pattern) so tests run hermetically.

## Why this matters

Parallel sessions are a first-class workflow now (multiple agents, multiple
containers, host+container dev loops). A daemon that silently goes down for one
of two sessions erodes trust in the entire hook system for that session — every
protection is off, invisibly. Fail-fast and shared-daemon-reuse are the correct
postures.
