# Plan 00239: daemon umask world writable runtime files

**Status**: In Progress
**Created**: 2026-08-14
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

`daemon/cli.py:579` calls `os.umask(0)` in the double-fork daemonize path and
never restores it. The live daemon runs with `Umask: 0000`, so every create that
does not pass an explicit mode lands at `0666` (files) / `0777` (directories).
Measured on this project: 10 files and 4 directories, including
`untracked/payload-capture/` (0777), `untracked/logs/hooks/verdicts.jsonl`,
`untracked/stop-events.jsonl`, `context-sidecar/`, `thread-registry/`, the PID
file and the `.socket-path` discovery file.

`os.umask(0)` is the textbook daemonize step (Stevens, *APUE*) and is only safe
when every subsequent create passes an explicit mode. This daemon does that at
exactly two sites — the socket (`server.py:657`, `chmod(0o660)` after bind) and
the lock file (`server.py:727`, `os.open(..., 0o600)`) — which is good evidence
the contract was understood and simply not applied to the data files.

Reported externally against v3.51.0 (`untracked/hooks-daemon-umask.md`). The
report's headline artefact does not apply to current code: it cites 8.3 MB of
`transcript_archiver` conversation archives at `0666`, and that handler was
removed in Plan 00233 — `untracked/transcripts/` no longer exists and cannot be
recreated. The defect is nonetheless live, continuous, and reproduced here; the
sensitive-content argument now rests on `payload-capture/` rather than on
transcripts.

## Goals

- The daemon creates no group-or-other-**writable** file or directory, and no
  other-**readable** one, under its own untracked tree.
- The fix survives someone later "restoring" the textbook `umask(0)` line —
  i.e. the sensitive creates carry explicit modes too.
- A regression test pins the permission bits, so this cannot silently return.
- Existing installations are told how to remediate files already on disk, since
  changing the umask does not retro-fix them.

## Non-Goals

- Not auditing permissions of files the INSTALLER writes (different flow,
  covered by Plan 00165); this plan is the running daemon only.
- Not changing the socket's `0o660` or the lock file's `0o600` — both are
  explicit and both are correct.
- Not a retro-fix sweep run automatically at startup; remediation for existing
  installs is documented, not enforced (a startup chmod sweep over a
  user-owned tree is its own risk).

## Context & Background

**The report recommends `os.umask(0o077)`; that value is wrong for this
project.** `0o077` strips group access, and group access is load-bearing here:

- The socket is explicitly `0o660` — group, not owner-only. That mode exists so
  a second process can connect.
- `CLAUDE.md` documents that a host and a container sharing a bind-mounted
  `untracked/` **deliberately share one daemon**, resolving the same
  `(hostname, project root)`. Those two contexts routinely run as different
  UIDs (host user vs container root).
- `.claude/init.sh` — the bash forwarder, running as whichever user launched
  Claude Code — reads `PID_PATH` (line 575) and the `.socket-path` discovery
  file (lines 478–482).

Under `0o077` those files become `0600` and the shared-daemon setup breaks for
the non-owning UID. `0o007` is the group-preserving equivalent: files default to
`0660`, directories to `0770`, both explicit-mode sites are unaffected
(`0o600 & ~0o007 == 0o600`), and *other* access — the actual exposure the report
is about — is gone entirely.

## Tasks

### Phase 1: Establish the baseline

- [ ] ⬜ **Task 1.1**: Record the current mode of every artefact the daemon
  creates under its untracked tree, from a fresh restart, as the before-state
- [ ] ⬜ **Task 1.2**: Enumerate every runtime create site in
  `src/claude_code_hooks_daemon/` (open, write_text, mkdir, os.open, makedirs,
  tempfile, os.replace) and mark which pass an explicit mode
- [ ] ⬜ **Task 1.3**: Confirm which artefacts are read cross-UID in the
  documented shared-daemon setup, so the umask value is chosen on evidence
  rather than on the report's default

### Phase 2: TDD the fix

- [ ] ⬜ **Task 2.1**: RED — a test that exercises the real daemonize path (or
  its helper), creates a file through the normal write path, and asserts
  `st_mode & 0o007 == 0` and no group/other write bit. Must FAIL first
- [ ] ⬜ **Task 2.2**: GREEN — `os.umask(0o007)` in place of `os.umask(0)`,
  with a comment naming why `0o077` is wrong here
- [ ] ⬜ **Task 2.3**: Defence in depth — explicit modes on the sensitive
  creates (`payload-capture/`, the verdict log, `stop-events.jsonl`) so the
  posture survives a later "fix" to the umask line

### Phase 3: Verify, remediate, document

- [ ] ⬜ **Task 3.1**: Restart the daemon; re-measure every artefact from
  Task 1.1 and prove the before/after difference against the LIVE daemon, not
  from the source
- [ ] ⬜ **Task 3.2**: Confirm the daemon still functions for a second UID —
  socket connect, PID read, `.socket-path` discovery — rather than assuming
  `0o007` preserved it
- [ ] ⬜ **Task 3.3**: Full QA; client-mode verification via
  `scripts/dummy-client-repo.sh` (this changes deployed runtime behaviour)
- [ ] ⬜ **Task 3.4**: Post-upgrade task file for existing installs whose files
  are already world-writable, plus a truth-changes entry if any documented
  statement about daemon file permissions changes

## Success Criteria

- [ ] `grep -i '^Umask' /proc/<daemon-pid>/status` shows a restrictive value
- [ ] Zero group/other-writable and zero other-readable artefacts under the
  daemon's untracked tree after a restart, measured not inferred
- [ ] The socket remains `0660` and the lock file `0600`
- [ ] A regression test fails if `os.umask(0)` is restored
- [ ] QA green; daemon RUNNING; client-mode fixture verified

## Delivery & Milestones

- Reported externally in `untracked/hooks-daemon-umask.md`; report retained in
  this plan folder rather than left in scratch
