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

**The value is `0o077`, as the report recommends.** This plan first argued for
the group-preserving `0o007` and that reasoning was refuted by adversarial
review; the refutation is recorded here rather than quietly replaced, because
the discarded argument is the one a future reader is most likely to re-derive.

The `0o007` case rested on three premises, and each fails on inspection:

- *"The socket's `0o660` proves group access is deliberate."* The comment
  directly above it (`server.py:655`) reads "owner read/write, group read, world
  none" — which describes `0o640`, not `0o660`. Comment and code disagree, so
  the mode is a copied daemon idiom, not a reasoned design. There is no
  `chown`/`chgrp` anywhere in `src/` or `scripts/`, and no `SO_PEERCRED` peer
  check, so the "group" is merely whatever the daemon's primary group happens to
  be.
- *"A host and a container share one daemon at different UIDs."* Documented, but
  already impossible: the start-lock at `server.py:727` is `os.open(..., 0o600)`
  and is deliberately left on disk for reuse, so a second UID's `start` gets
  EACCES today, umask or not. The daemon is also a descendant of every process
  that reads its files (Claude Code → hook wrapper → `init.sh` → `cli start` →
  fork), and nothing setuids.
- *"`init.sh` reads `PID_PATH` and `.socket-path` as the launching user."* True,
  and those are same-UID reads for the reason above.

`0o007` is therefore never *safer* than `0o077` and is sometimes materially
worse: where a host uses a shared primary group (`staff`, `users`, a service
account) it leaves the verdict log, `stop-events.jsonl` and `payload-capture/`
group-readable **and group-writable**. `0o077` is deployment-invariant. Both
explicit-mode sites survive it: `0o600 & ~0o077 == 0o600`, and the socket's mode
is a post-bind `chmod`, which no umask touches.

**A umask alone is not sufficient, and the exposure is wider than the report
described.** Three further sites need work a umask cannot do:

- `worktree_create` runs `git worktree add` as a child of the umask-0 daemon, so
  an entire checkout of TRACKED SOURCE lands world-writable. Reproduced: a
  daemon-created worktree has `README.md`, `pyproject.toml` and
  `.claude/settings.json` at `0666` and the worktree root at `0777`, against
  `0644` in the main repo. This one needs a *permissive* `0o022` around the
  subprocess — a source checkout should be `0644`/`0755`, and under a bare
  `0o077` it would become `0600`/`0700`.
- `utils/settings_repair.py:105-106` writes a temp file and `replace()`s it over
  the **git-tracked** `.claude/settings.json`, so the tracked file inherits the
  temp file's mode. (Live check: `settings.json` is `0644` today, so this path
  has not been firing — the mechanism is real, the frequency is not evidenced.)
- `utils/retention.py:62-64` uses the same tmp-then-replace on `verdicts.jsonl`
  and `stop-events.jsonl`, so a manual `chmod` is undone at the next trim.

## Tasks

### Phase 1: Establish the baseline

- [x] ✅ **Task 1.1**: Baseline measured — daemon `Umask: 0000`; 10 files at
  `0666` and 4 directories at `0777`, listed in JOURNAL 26-08-14. The report's
  headline artefact is NOT among them: `transcript_archiver` was removed in Plan
  00233, so its 8.3 MB of archives cannot be reproduced and the
  sensitive-content case rests on `payload-capture/` instead
- [x] ✅ **Task 1.2**: 98 runtime create sites, 35 of them directories, and
  **exactly one** passes an explicit mode (`server.py:727`, the lock at
  `0o600`). This settles A-vs-B: the report's "explicit mode at every sensitive
  create" is a permanent audit obligation across 97 sites, and the codebase has
  already failed that discipline 97 times out of 98. The umask is the single
  choke point
- [x] ✅ **Task 1.3**: `0o007`, not the report's `0o077`. Group access is
  load-bearing — socket `chmod(0o660)` after bind (`server.py:657`), a host and
  container sharing ONE daemon at different UIDs (CLAUDE.md), and `init.sh`
  reading `PID_PATH` (575) and `.socket-path` (478–482) as the launching user.
  `0o007` strips *other* — the actual exposure — and keeps group

### Phase 2: TDD the fix

- [ ] ⬜ **Task 2.1**: RED — a test that exercises the real daemonize path (or
  its helper), creates a file through the normal write path, and asserts
  `st_mode & 0o007 == 0` and no group/other write bit. Must FAIL first
- [ ] ⬜ **Task 2.2**: GREEN — `os.umask(0o077)` in place of `os.umask(0)`,
  with a comment recording why the group-preserving `0o007` was rejected so it
  is not "restored" later
- [ ] ⬜ **Task 2.3**: Defence in depth — explicit modes on the sensitive
  creates (`payload-capture/`, the verdict log, `stop-events.jsonl`) so the
  posture survives a later "fix" to the umask line
- [ ] ⬜ **Task 2.4**: `worktree_create` — set a permissive `0o022` around the
  `git worktree add` subprocess. A source checkout must be `0644`/`0755`; today
  it is `0666`/`0777` and under a bare `0o077` it would become `0600`/`0700`.
  This is the one place the daemon needs a MORE permissive umask, and the one
  place it currently has no control at all
- [ ] ⬜ **Task 2.5**: `settings_repair.py` — `copymode()` the original before
  `replace()`, so repairing a git-tracked file never rewrites its mode. Its
  sibling `hook_command_migration.py:178` rewrites in place and is already
  immune; the two differ for no reason

### Phase 3: Verify, remediate, document

- [ ] ⬜ **Task 3.1**: Restart the daemon; re-measure every artefact from
  Task 1.1 and prove the before/after difference against the LIVE daemon, not
  from the source
- [ ] ⬜ **Task 3.2**: Confirm the daemon still functions for a second UID —
  socket connect, PID read, `.socket-path` discovery — rather than assuming
  `0o007` preserved it
- [ ] ⬜ **Task 3.3**: Full QA; client-mode verification via
  `scripts/dummy-client-repo.sh` (this changes deployed runtime behaviour)
- [ ] ⬜ **Task 3.4**: DBF — a write-time fix cannot see what is already on
  disk, so add a BATCH guard: a check asserting no daemon-created artefact has
  `mode & 0o077`, runnable against an existing install rather than only in a
  unit test. Every currently-deployed daemon has world-writable files that no
  umask change retro-fixes
- [ ] ⬜ **Task 3.5**: Post-upgrade task file for existing installs whose files
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
