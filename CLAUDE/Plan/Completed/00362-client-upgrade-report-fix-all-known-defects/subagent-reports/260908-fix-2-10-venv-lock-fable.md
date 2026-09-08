# Task 2.10 (D4): venv rebuild is serialised — fix report

**Branch**: `agent-acf1f3aaafed6dc49-e71cdd3b` (worktree)
**Code commit**: `80417d4b`
**Defect**: DEFECT-LEDGER D4 / Plan 00100 Phase 4 (Tasks 4.0–4.4), HIGH.

## Task 4.0 spike: `flock` under the Podman bind mount

Run in this CCY container (`container=podman`, `/run/.containerenv` present;
the repo path reports `btrfs`, i.e. the host filesystem seen through the bind
mount). Script: `untracked/scratch/flock_spike.sh` (scratch, not committed).

- Two processes on `untracked/.venv-bootstrap.lock`: A takes the lock and
  holds it 3s; B, 0.5s later, is REFUSED by `flock -n`, then blocks on
  `flock -w 10` and acquires only after A releases. Log order was exactly
  `A acquired | B nonblock-refused | A released | B acquired | B released`.
- Twenty processes each read-increment-write a counter under the lock:
  final value 20 (no lost update).

Verdict: `flock(2)` gives mutual exclusion across processes sharing the bind
mount from inside the container, so `flock` is the default backend.
Not verifiable from here: host-side contention (a host shell against a
container process on the same mount). That case is why the `mkdir` fallback
exists and can be forced with `HOOKS_DAEMON_VENV_LOCK_BACKEND=mkdir` if a
mount ever turns out not to propagate `flock`.

## What changed

- `scripts/install/venv.sh`: `acquire_venv_lock` / `release_venv_lock`
  around a new `_ensure_venv_build`; the two fast-path checks are one helper
  (`_venv_is_fresh`) called lock-free first and again under the lock, so a
  waiter reuses the venv the holder just built. Lock file
  `{daemon_dir}/untracked/.venv-bootstrap.lock`; mkdir fallback
  `.venv-bootstrap.lock.d` with a `pid` file and a stale-age reclaim
  (`HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS`, 600). Bound
  `HOOKS_DAEMON_VENV_LOCK_TIMEOUT` (120); messages name the lock path.
- `src/claude_code_hooks_daemon/daemon/venv_lock.py` (new): the same
  contract in Python (`fcntl.flock` / mkdir, same file, same env vars).
  `cmd_repair` runs `uv sync` inside it and reports a timeout as exit 1.
- Tests: `tests/integration/test_ensure_venv_lock.py` (stub `uv` that sleeps,
  two starters 0.3s apart → one sync, second says "waiting up to", both
  print the same path; 20-iteration gate marked `slow`; bounded wait with
  an external bash holder; fast path ignores a held lock; mkdir backend
  serialises, reclaims a stale dir, times out on a fresh one; unknown
  backend rejected). `tests/unit/daemon/test_venv_lock.py` (14 cases incl.
  exclusion against a real bash `flock` holder). Two new `cmd_repair` cases.
- Callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-venv-rebuild-is-serialised.md`.

## QA run

- RED confirmed first: 8 of 9 new shell tests failed on the unlocked code,
  each with two `uv sync` calls into the same target.
- After the fix: new shell tests 9 passed; repair + lock unit tests 25
  passed; the nine pre-existing `venv.sh` shell suites 42 passed.
- `shellcheck -x scripts/install/venv.sh` clean; `ruff check`/`format` and
  `mypy --strict` clean on all touched Python.
- Not done here, by instruction: daemon restart (Task 4.4's restart step is
  for the merge session), no full `run_all.sh`.

## Notes for the merge

- The worktree's `ensure_venv` sync omits dev extras; `pytest` needed
  `uv sync --frozen --all-extras` into the venv first (Plan 00358 wrinkle,
  not touched here).
- `cmd_repair` still runs a bare `uv sync` (no `--frozen`); pre-existing,
  out of scope.
