# Plan 00245: CI Suite Green Again

**Status**: In Progress
**Created**: 2026-08-17
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Single-Threaded

## Overview

GitHub Actions has failed on **every push for at least 25 consecutive runs**,
reaching back to 2026-08-14 and beyond. 73–79 tests fail in the runner while all
12,388 pass locally. The `Shell` and `Daemon load` jobs pass; only
`QA (Python 3.11/3.12/3.13)` → "Tests + coverage" fails, identically on all
three interpreters.

A CI that is red on every run supplies no signal, so nothing has been acting on
it. That is the same blind-guard shape `CLAUDE.md` Core Standard 15 (DBF) is
about, one level above the local gate: the check runs, reports failure, and no
decision depends on the result.

This matters beyond tidiness. Plan 00244's work added a project-handler test
step to this workflow; a step added to an already-red workflow can never be the
thing that turns CI red or green, so that coverage is wired in but not
load-bearing until the suite is green.

## Goals

- Get `QA (Python 3.11/3.12/3.13)` passing, so a red CI run means something
  again.
- Fix root causes; never mark a failing test skipped to buy a green tick.
- Leave behind a guard for each root cause, so the divergence cannot silently
  return.

## Non-Goals

- Reworking the workflow's structure or its deliberate divergence from
  `run_all.sh` (documented at `.github/workflows/qa.yml:38-42`: the script
  resolves its interpreter through the daemon's fingerprint-keyed venv, which is
  a self-install entrypoint, not a CI one).
- Raising or lowering the 95% coverage threshold.

## Context & Background

### Root cause 1 — tests depend on an untracked local artifact (SOLVED)

`init.sh:246-265` refuses to run inside the hooks-daemon repo unless
self-install is evident. It accepts either `HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH`
or the presence of `.claude/hooks-daemon.env` — and that `.env` is **gitignored
and untracked** (`.claude/.gitignore:10`).

Three test files source the real `.claude/init.sh`, whose repo-detection check
runs at SOURCE time using `PROJECT_PATH` derived from `BASH_SOURCE` — the real
repo — before any test override takes effect:

| File                                          | Tests |
| --------------------------------------------- | ----- |
| `tests/integration/test_forwarder_jq_free.py` | 40    |
| `tests/unit/test_ci_passthrough.py`           | 14    |
| `tests/integration/test_init_hot_path.py`     | 9     |

So on a self-installed developer tree the guard passed by accident; on a fresh
checkout it emitted `hooks_daemon_repo_detected` and exited. That is ~63 of the
failures, and it is the LESSONS.md lesson "a fixture must ESTABLISH the premise
its test documents" — the same file's own `_sandbox_project` helper already did
this correctly by writing its own `.env`.

Reproduced exactly outside the repo (temp dir with a hooks-daemon git remote and
no `.env`): sourcing emits the byte-identical JSON the CI assertion diffed
against; adding the `.env` makes it source cleanly.

The fix sets `HOOKS_DAEMON_ROOT_DIR` to the repo root at each site. That is not
a workaround — it is precisely what the untracked `.env` exports in a real
self-install session.

### Root cause 2+ — remaining clusters (NOT root cause 1)

Verified by running these files with `.claude/hooks-daemon.env` moved aside: all
91 tests pass, so their CI failures have a different cause.

| File                                                  | Tests | Likely area                       |
| ----------------------------------------------------- | ----- | --------------------------------- |
| `tests/integration/test_ensure_venv.py`               | 4     | venv creation in the runner       |
| `tests/unit/daemon/test_server_modes.py`              | 3     | daemon server mode actions        |
| `tests/unit/daemon/test_server_validation.py`         | 3     | request validation (asyncio)      |
| `tests/unit/utils/test_git_sync_rewrite_detection.py` | 3     | git fixtures / git config         |
| `tests/integration/test_fingerprint_parity.py`        | 1     | bash/python fingerprint parity    |
| `tests/integration/test_venv_include_resolution.py`   | 1     | venv include resolution           |
| `tests/unit/daemon/test_paths_stale_cleanup.py`       | 1     | stale-file cleanup exception path |
| `tests/integration/test_client_owned_asset_lint.py`   | 1     | ruff DEFAULT rule set on assets   |

These need diagnosis against the runner rather than locally, since they pass
here under every condition tried so far. CI itself is the instrument: push, read
the failure, fix, repeat.

## Tasks

### Phase 1: Root cause 1 — the untracked-artifact dependency

- [x] ✅ **Task 1.1**: Establish that CI is red on every push, and for how long
- [x] ✅ **Task 1.2**: Identify the `hooks_daemon_repo_detected` root cause in `init.sh`
- [x] ✅ **Task 1.3**: Reproduce it outside the repo, byte-for-byte against the CI assertion
- [x] ✅ **Task 1.4**: Confirm the escape-hatch file is gitignored and untracked
- [x] ✅ **Task 1.5**: Set the premise explicitly at all three sites
- [x] ✅ **Task 1.6**: Verify the three files pass with the `.env` moved aside
- [x] ✅ **Task 1.7**: Confirm the remaining clusters are NOT this cause

### Phase 2: Guard the root cause

- [x] ✅ **Task 2.1**: Pin `init.sh`'s repo-detection contract in a test
  - [x] ✅ Passes with `HOOKS_DAEMON_ROOT_DIR == PROJECT_PATH` and no `.env`
  - [x] ✅ Emits `hooks_daemon_repo_detected` with neither present
  - [x] ✅ Control: an unrelated remote is never refused
- [x] ✅ **Task 2.2**: Decide the guard for a NEW test sourcing the real
  `init.sh` without the premise — see Decision 2 (no scanner; CI is the guard)

### Phase 3: Remaining clusters

- [ ] ⬜ **Task 3.1**: Push Phase 1 and read the next CI failure set
- [ ] ⬜ **Task 3.2**: `test_ensure_venv` / `test_venv_include_resolution` /
  `test_fingerprint_parity` — venv creation in the runner
- [ ] ⬜ **Task 3.3**: `test_server_modes` / `test_server_validation` /
  `test_paths_stale_cleanup`
- [ ] ⬜ **Task 3.4**: `test_git_sync_rewrite_detection` — git fixture assumptions
- [ ] ⬜ **Task 3.5**: `test_client_owned_asset_lint` — ruff default rule set

### Phase 4: Make CI's verdict load-bearing

- [ ] ⬜ **Task 4.1**: Confirm a fully green run on all three interpreters
- [ ] ⬜ **Task 4.2**: Record in LESSONS.md that a permanently-red CI is a
  blind guard, not a nuisance

## Dependencies

- Related: Plan 00244's project-handler QA gate, whose CI half is inert until
  this plan lands.

## Technical Decisions

### Decision 1: set the premise rather than relax the guard

**Context**: `init.sh`'s repo-detection guard is what broke the tests in CI.

**Options Considered**:

1. Relax the guard in `init.sh` — it would stop protecting real client installs
   from a misconfigured self-install.
2. Mark the tests as requiring a self-installed tree (skip in CI) — buys a green
   tick and removes the coverage; the bodge.
3. Have each test establish the premise explicitly.

**Decision**: Option 3. The guard is correct and worth keeping; the defect was a
test depending on ambient untracked state. Setting `HOOKS_DAEMON_ROOT_DIR` is
exactly what the untracked `.env` does in a real self-install session, so the
tests now assert against the same conditions a real session has.

**Date**: 2026-08-17

### Decision 2: no source scanner for Task 2.2 — CI is the guard

**Context**: Task 2.2 asked for a guard catching a NEW test that sources the
real `init.sh` without establishing the premise. Enumerating the landscape
first: 30 test files mention `init.sh`, but only five actually run it. Two of
those five (`test_socket_timeout_daemon_alive.py`,
`test_emit_hook_error_jqless.py`) copy it into a sandbox and write their own
`.env`, so they were correctly absent from the CI failure set.

**Options Considered**:

1. **A source scanner** over test files that touch the real `init.sh`. Rejected:
   the discriminator is not "mentions `init.sh`" (a false-positive machine — most
   of the 30 only name it in a docstring or a path list) but "hands the REAL path
   to a subprocess that executes it, rather than a copy". Separating those needs
   dataflow analysis, which is disproportionate. A weaker text rule ("must
   mention `HOOKS_DAEMON_ROOT_DIR` somewhere") is satisfied by a bare mention and
   so proves nothing.
2. **Require an import of a shared premise helper**, making the check crisp. Rejected:
   it forces an abstraction at three sites, and `CLAUDE.md`'s own ratio is "three
   similar lines of code is better than a wrong abstraction… six identical blocks
   means you need a proper pattern".
3. **An autouse `conftest.py` fixture** exporting `HOOKS_DAEMON_ROOT_DIR` for the
   whole session. Rejected as actively harmful: it would make the tests pass for a
   reason invisible at the test site — relocating the ambient dependency rather
   than removing it, which is the very defect this plan exists to fix. It also
   would not reach tests that build their environment from scratch, which is what
   `_build_clean_env` does.
4. **CI is the guard.** A fresh checkout with no untracked `.env` is exactly what
   the runner provides, and it already caught this — 25 consecutive times.

**Decision**: Option 4, plus the contract test from Task 2.1. The blind guard
here was never a missing scanner: CI detected the defect on every single push and
no decision depended on the result. Adding a third partial guard while the second
stays unread would be treating the symptom. Phase 4 is therefore the real
remedy, and Task 2.1 pins the contract so the two ways through the guard cannot
be silently narrowed to the untracked one.

**Date**: 2026-08-17

## Success Criteria

- [ ] `QA (Python 3.11)`, `QA (Python 3.12)` and `QA (Python 3.13)` all pass
- [ ] Zero tests skipped or deleted to achieve it
- [ ] Each root cause has a guard that fails if it returns
- [ ] Local `llm_qa.py all` still passes

## Risks & Mitigations

| Risk                                               | Impact | Probability | Mitigation                                                    |
| -------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------- |
| Remaining clusters are not locally reproducible    | Medium | High        | Use CI as the instrument: small pushes, read each failure set |
| A "fix" masks a real defect in the code under test | High   | Low         | Never skip; fix causes, and add a guard per cause             |
| Coverage margin is thin (95% threshold)            | Medium | Medium      | Local run measures 95.1%; watch the CI figure per push        |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Phase 1 delivered at the commit that also files this plan.
