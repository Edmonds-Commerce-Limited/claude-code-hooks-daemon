# Plan 00411: host hostname in status line

**Status**: In Progress
**Created**: 2026-09-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

A session looks identical in every terminal, whichever machine it runs on. The
status line should be able to say WHICH — optionally, because a single-machine
user gains nothing and pays status-line width.

Inside a container the answer is not the container's hostname. A container gets
its own UTS namespace, so `hostname`, `uname -n`, `/etc/hostname` and
`/proc/sys/kernel/hostname` all agree on a value that is the container ID and
tells the reader nothing about where they are.

Probing this environment (rootless podman, Debian 12 container on a Fedora 44
host) established that **the host hostname is not readable from inside it**.
Every candidate was tried and failed: no `/run/host`, no container socket
mounted, `/run/.containerenv` is zero bytes, and reverse DNS on both
`169.254.1.1` and `169.254.1.2` returns nothing.

A field report suggested reading the host's name from a loopback alias in
`/etc/hosts`. That is a real effect with a real cause, but it is
**host-distro-dependent rather than a mechanism**. Podman does inherit the
host's `/etc/hosts` — proven here by the host's own LAN entries appearing in
the container's copy — but whether that file names the host depends on the host
distribution: Debian and Ubuntu write `127.0.1.1 <hostname>` at install time,
Fedora does not. The reporting environment had a Debian-flavoured host; this
one is Fedora, and the same read finds nothing.

So the only authoritative route is an explicit hand-off from outside the
container. This plan is ordered around that, and degrades honestly instead of
guessing.

## Goals

- An optional status-line segment naming the machine the session is really on.
- Resolution order, first hit wins: an explicit environment variable (the ccy
  supervisor's hand-off), then a configured override, then — only when NOT
  containerised — the real `gethostname()`, then the `/etc/hosts` hint.
- An INFERRED value renders visibly differently from a read one. Knowing which
  machine you are on is the whole point of the segment, so a confidently-wrong
  name is worse than no name.
- Nothing resolvable renders nothing, not a placeholder.

## Non-Goals

- Making the host hostname readable from inside a container. It is not, and
  this plan does not add a privileged mount, a socket or a helper daemon to
  change that. An export is the fix; this consumes one.

- Showing the container's own hostname as a substitute. It is the container ID
  and answers a different question; the existing environment indicator already
  says a container is in play.

- Rendering by default. The segment is opt-in.

## Tasks

### Phase 1: Resolution

- [x] ✅ **Task 1.1**: Failing tests first — one per rung of the ladder, plus
  the precedence between them: the env var beats config; config beats
  `gethostname()`; `gethostname()` is consulted ONLY when not containerised;
  the `/etc/hosts` read is last and is marked inferred; nothing resolvable
  yields no segment at all.

  Pin the two `/etc/hosts` shapes that actually differ in the field as
  fixtures: a Fedora-style file whose `127.x` lines carry only `localhost*`
  (must yield nothing) and a Debian-style file carrying `127.0.1.1 <name>`
  (must yield that name, marked inferred).

- [x] ✅ **Task 1.2**: Implement resolution in a util, resolved ONCE at daemon
  startup and cached the way `container_runtime()` already is. The status line
  re-renders on every Claude Code refresh, and per-render file reads are the
  mistake this handler directory's own guidance calls out.

### Phase 2: The segment

- [x] ✅ **Task 2.1**: New `status_line` handler, disabled by default, showing
  the resolved name with inferred values visibly distinguished from read ones.
  `explain_segment()` names which rung produced the current value, so the
  segment explains its own provenance rather than leaving the reader to guess.

- [x] ✅ **Task 2.2**: Document the environment-variable contract, so the ccy
  supervisor (or any wrapper) has a name to export against, and record why the
  loopback read is a hint rather than the mechanism.

## Success Criteria

- [x] ✅ With the variable exported, the segment shows that name as
  authoritative inside this podman container. Verified end-to-end through the
  real hook (`.claude/hooks/status-line` → daemon), not through the CLI
  explainer — which resolves in its OWN process and therefore reported "not
  resolved" while the daemon was rendering the name correctly. That near-miss
  is recorded in `JOURNAL/`.

- [x] ✅ With nothing exported, this Fedora-hosted container renders no segment
  rather than the container ID or a wrong guess. Verified by restarting without
  the variable and re-rendering: the segment disappears.

- [ ] ⬜ On a desktop host and under LXC, the real hostname shows with no
  export needed. Covered by unit tests, and NOT live-verified: this session has
  neither machine available. Left unticked deliberately rather than ticked on
  the strength of a passing test, because the whole point of the other two
  criteria was that the live behaviour surprised the tests once already.

- [ ] ⬜ Full QA passes, the daemon is restarted, and CI is green.

## Delivery & Milestones

- Requested by the owner, who identified the container-hostname trap in the
  request itself and flagged the loopback read as needing verification rather
  than trust. That verification is why the design does not lead with it.
