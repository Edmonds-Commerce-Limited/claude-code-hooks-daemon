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

- [x] ✅ **Task 3.1**: Push Phase 1 and read the next CI failure set
- [x] ✅ **Task 3.2**: `test_ensure_venv` / `test_venv_include_resolution` /
  `test_fingerprint_parity` — venv creation in the runner
  - [x] ✅ `test_ensure_venv` (4): `ensure_venv` skips when `CI=true`; harness
    now strips the gate vars, and both halves of the gate gained coverage
  - [x] ✅ `test_fingerprint_parity` (1): the venv-detection guard read
    `sysconfig.get_config_var("base_prefix")`, which is always `None` — the
    pair is now CONSTRUCTED instead of assumed
  - [x] ✅ `test_venv_include_resolution` (1): resolver discovered its own
    interpreter; `HOOKS_DAEMON_PYTHON` now pins it, with a guard test
  - [x] ✅ CI installs `uv` so the real bootstrap runs on all three interpreters
- [x] ✅ **Task 3.3**: `test_server_modes` / `test_server_validation` /
  `test_paths_stale_cleanup`
  - [x] ✅ Root cause: Python 3.12 made `runtime_checkable` Protocol
    `isinstance` use `inspect.getattr_static`, so a bare `Mock()` stops
    satisfying `Controller`. Verified on a real 3.12.13 interpreter
  - [x] ✅ `Mock(spec=Controller)` everywhere, plus an assertion pinning WHICH
    controller branch runs
  - [x] ✅ `test_paths_stale_cleanup` passes on 3.12 — not this cause; watch it
    in the next CI run
- [x] ✅ **Task 3.4**: `test_git_sync_rewrite_detection` — git fixture assumptions
  - [x] ✅ Identity was set on three of four repos; `commit-tree` runs in the
    bare remote, which had none. A developer's global config masked it
  - [x] ✅ Supplied via `GIT_*_NAME`/`EMAIL` in the fixture environment, which
    covers repos that do not exist yet
- [x] ✅ **Task 3.5**: `test_client_owned_asset_lint` — ruff default rule set
  - [x] ✅ ruff 0.16 promoted DTZ and BLE into its defaults; the two DTZ
    findings got behaviour-preserving fixes in the asset
  - [x] ✅ `BLE001` declared in the manifest with its reason, honoured by the
    guard, and pinned to the client doc by a new test
  - [x] ✅ Linter output no longer depends on ambient `FORCE_COLOR`

### Phase 4: Make CI's verdict load-bearing

- [ ] 🔄 **Task 4.1**: Confirm a fully green run on all three interpreters
  - [x] ✅ Every previously-failing file passes on real 3.11/3.12/3.13 locally
    under runner conditions (`CI=true`, no global git identity): 95–96 passed
  - [x] ✅ The 41 failures in the last two CI runs are accounted for exactly —
    same 8 files, same counts, so nothing in the set is unexplained
  - [x] ✅ Read the CI run for the pushed commit: 41 failures became 4 (×3
    interpreters = 12), a set that was NEVER passing — the four upgrade gates
    had been silently skipped for want of `uv`, and Decision 3 un-skipped them
  - [x] ✅ Root-caused and fixed: `fetch-depth: 0` on the qa job's checkout.
    `tests/acceptance/conftest.py` clones the checkout and runs `git describe --tags` on it; the default shallow tagless checkout leaves the clone with no
    reachable tag. `fetch-tags: true` would NOT fix it — a depth-1 clone has no
    ancestors, so an earlier commit's tag is unreachable regardless
  - [x] ✅ Proved locally rather than by pushing: cloned this repo `--depth 1 --no-tags` and ran the four gates against it (same 4 failures, same exit
    128), then `fetch --unshallow --tags` and re-ran (4 passed)
  - [x] ✅ Added `-rs` to the CI pytest step so a skip is NAMED. CI reports 14
    skipped against 6 locally, and a skip that nobody can see is what let these
    four sit inert
  - [ ] ⬜ Read the CI run for the fetch-depth commit and confirm green
- [x] ✅ **Task 4.2**: Record in LESSONS.md that a permanently-red CI is a
  blind guard, not a nuisance
  - [x] ✅ Plus the two generalisable lessons this phase produced: the ambient
    -premise defect shared by all six clusters, and installing the interpreter
    that failed instead of reasoning about it

## Dependencies

- Related: Plan 00244's project-handler QA gate, whose CI half is inert until
  this plan lands.

## Technical Decisions

Recorded in full in [DECISIONS.md](DECISIONS.md) — options considered and why,
extracted so this plan stays readable at a glance:

| #   | Decision                                                                  |
| --- | ------------------------------------------------------------------------- |
| 1   | Set the premise rather than relax the `init.sh` repo-detection guard      |
| 2   | No source scanner for Task 2.2 — CI is the guard                          |
| 3   | Install `uv` in CI rather than skip the venv-bootstrap tests              |
| 4   | Construct the interpreter pair instead of reading the ambient one         |
| 5   | Declare an accepted lint finding rather than defeat the code or the guard |
| 6   | The ambient environment is the recurring defect, not the tests            |
| 7   | `fetch-depth: 0`, not `fetch-tags: true`, and not a fixture change        |

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
