# Plan 00124: ensure_venv drops the project-path slug → host/container venv collision

**Status**: Complete
**Created**: 2026-06-13
**Owner**: Claude (Opus)
**Priority**: High (hotfix)
**Type**: Bug Fix
**Severity**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

A desktop-level Claude Code session and a containerised (ccy/Podman) session that
open the **same bind-mounted project** are supposed to get **separate venvs** —
that isolation is the whole point of Plan 00100 Task 3.0.5's project-path slug
(`venv-{slug}-py{MM}-{hash}`). On a machine where the desktop host and the
container run the **same Python** (same `sys.version` / `sys.base_prefix` /
arch), they were instead sharing ONE venv and fighting over it.

## Root Cause

`ensure_venv()` (`scripts/install/venv.sh:353`) computes the fingerprint with:

```bash
fingerprint=$(python_venv_fingerprint "$python_bin")     # <-- no root passed
```

`python_venv_fingerprint` only adds the slug when given a root as `$2` (or via
`$HOOKS_DAEMON_ROOT_DIR`). `ensure_venv` already HAS the root — it is `$1`
(`daemon_dir`) — but never passes it, and `HOOKS_DAEMON_ROOT_DIR` is not exported
at venv-creation time. So the venv is created with the **bare, slug-less** key
`venv-py{MM}-{hash}`.

The bare hash = `md5(sys.version | sys.base_prefix | platform.machine())` is
**identical** for a host and a container that share the same Python. Because
ccy bind-mounts the project (so `untracked/` is one physical directory), both
views resolve to the SAME `venv-py{MM}-{hash}` and collide.

The Python resolver (`paths.py` `get_venv_path` / `resolve_existing_venv_python`)
ALREADY passes the root and so looks for the slugged name first — but, missing
it, falls through to its broad `venv-*` scan and picks up the slug-less venv.
Bash creation and Python resolution therefore disagree on the venv key.

### Evidence

- Live venv on disk: `untracked/venv-py311-66bbc57c` (no slug).
- `python_venv_fingerprint /usr/bin/python3.11` → `py311-28fb230b`
- `python_venv_fingerprint /usr/bin/python3.11 /workspace` → `workspace-py311-28fb230b`
- `python_venv_fingerprint /usr/bin/python3.11 /home/user/project` → `home_user_project-py311-28fb230b`
  (the hash part is constant; only the slug differs — the slug is the only discriminator).

### Why it only surfaced on a new machine

On the old machine the desktop Python differed from the container Python →
different bare hash → coincidentally-separate venvs even without the slug. On
the new machine they coincide → identical bare hash → collision. The slug would
have isolated them in both cases; its absence only *manifests* when the Pythons
match.

## Goals

- `ensure_venv` creates venvs keyed WITH the project-path slug, matching the
  Python resolver's keyed lookup.
- A host view and a container view of the same bind-mounted project get
  distinctly-named venvs in a shared `untracked/`.
- Bash creation key == Python resolution key (no silent reliance on the broad
  `venv-*` scan fallback).

## Non-Goals

- No change to the Python fingerprint/slug functions (already correct).
- No change to the broad `venv-*` scan fallback semantics (out of scope; it is
  no longer reached in steady state once keys agree).
- No change to socket/PID hostname isolation (verified working).

## Tasks

### Phase 1: Reproduce & RED

- [x] Confirm live venv is slug-less and prove the slug collision empirically (DONE in diagnosis)
- [x] Add failing integration test: `ensure_venv` produces `venv-{slug}-{fp}` and
  two different roots yield two differently-named venvs

### Phase 2: GREEN

- [x] Fix `scripts/install/venv.sh:353` to pass `$daemon_dir` as the slug root
- [x] Update existing `test_ensure_venv.py` expectations from bare → slugged key

### Phase 3: Regression & Verify

- [x] `python -m pytest tests/integration/test_ensure_venv.py tests/integration/test_fingerprint_parity.py -v`
- [x] Full QA: `./scripts/qa/llm_qa.py all`
- [x] Daemon restart + status RUNNING (dogfood the new key)
- [x] One-time cleanup guidance for the orphaned slug-less venv on affected machines

## Success Criteria

- [x] New isolation test passes; existing ensure_venv tests pass
- [x] All QA checks pass
- [x] Daemon restarts cleanly on a slugged venv
- [x] Bash-created venv name == Python-resolved keyed name

## Notes & Updates

### 2026-06-13

- Diagnosed from a user report: desktop + container sessions sharing one venv.
- Single-line root cause at `venv.sh:353`; Python side already correct.
