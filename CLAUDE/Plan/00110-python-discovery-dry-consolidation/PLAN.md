# Plan 00110: Python Interpreter Discovery — DRY Consolidation & Latest-Always Policy

**Status**: Not Started
**Created**: 2026-05-26
**Owner**: TBD
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Teams

## Overview

The daemon has at least **four** independent implementations of "find a compatible Python interpreter on PATH", each with hardcoded version lists like `(python3.13, python3.12, python3.11)`. Field report on host `host-a` (2026-05-26, `untracked/hooks-daemon-upgrade-python-version.md`) demonstrated the consequence: the skill-level `install.sh` aborted on the default `python3` (3.9.21) and suggested `HOOKS_DAEMON_PYTHON=python3.11` even though `python3.13` and `python3.14` were on PATH. The operator had to manually export the env var to recover.

The root problem is **WET, not buggy**. Every site reinvents discovery with slight variations and a hand-rolled candidate list that goes stale every Python release. The fix is two coupled changes:

1. **Single canonical discovery helper** (one bash, one python) used by every caller — no more duplication.
2. **Glob-and-sort, not enumerate** — discovery walks `$PATH` for `python3.[1-9][0-9]` executables, sorts by minor version descending, and picks the highest that satisfies `pyproject.toml::requires-python`. New CPython releases need zero code changes.

## Goals

- One bash helper, one python helper. Every caller — `scripts/upgrade.sh`, `scripts/install/prerequisites.sh`, `scripts/install/parse_min_python.sh`, `src/.../skills/.../install.sh`, `scripts/lib/resolve_venv.sh`, `daemon/paths.py` — uses them. Zero duplicate `_is_python_at_least_311`, zero duplicate `requires-python` regex, zero duplicate candidate enumeration.
- Discovery is **version-agnostic**: glob `python3.[1-9][0-9]` on `$PATH`, sort numerically by minor, pick highest that satisfies `requires-python`. `python3.14` works the day it ships, no release required.
- Error messages name an interpreter that **actually exists on the host**. If glob returns `python3.13` but it's below the floor, suggest installing a newer one — never suggest a version that isn't there.
- Precedence ladder preserved: explicit `HOOKS_DAEMON_PYTHON` env > existing venv interpreter > glob-and-sort discovery > error with accurate remediation.

## Non-Goals

- No new uv/pyenv integration. Discovery stays in POSIX bash + stdlib python.
- No removal of the `HOOKS_DAEMON_PYTHON` escape hatch — operators must still be able to pin.
- No change to fingerprint-keyed venv pathing (Plan 00100 work stands).
- No removal of `parse_min_python.sh` — it has a legitimate single-responsibility (extract `requires-python` from pyproject.toml) and is reused by both helpers.

## Context & Background

**Exploration report sites** (from session-of-record agent run on 2026-05-26):

| Site                                             | Lines                     | Current logic                                                                                                                                                                              | Status                                   |
| ------------------------------------------------ | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------- |
| `scripts/upgrade.sh`                             | 77-278                    | Hardcoded `(3.13, 3.12, 3.11)` + `compgen -c python3.` fallback + inline `requires-python` parse                                                                                           | **WET**                                  |
| `scripts/install/prerequisites.sh`               | 40-164                    | Verbatim copy of `_is_python_at_least_311`, same candidate list, no `requires-python` cross-check                                                                                          | **WET — explicit duplicate**             |
| `scripts/install/parse_min_python.sh`            | whole file                | `grep` `requires-python` from pyproject.toml, echo `X.Y`                                                                                                                                   | **OK — pure helper, reusable**           |
| `src/.../skills/hooks-daemon/scripts/install.sh` | 47-72                     | Fetches remote pyproject.toml, parses `requires-python`, probes ONLY `$HOOKS_DAEMON_PYTHON` or default `python3` — **no glob, no candidate list**                                          | **The host-a failure path**            |
| `src/.../daemon/paths.py`                        | 239-272, 350-361, 407-483 | `_find_compatible_python_on_path()` with `_COMPATIBLE_PYTHON_CANDIDATES = ("python3", "python3.13", "python3.12", "python3.11")`, `_parse_requires_python_min()`, `can_inline_bootstrap()` | **WET — same hardcoded list, in Python** |
| `scripts/lib/resolve_venv.sh`                    | 85-131, 232-281           | `_rv_pick_python()` precedence ladder — delegates version checking to `paths.py`                                                                                                           | **OK — uses SSOT**                       |
| `src/.../skills/.../_resolve-venv.sh`            | 1-42                      | Thin shim sourcing canonical `resolve_venv.sh`                                                                                                                                             | **OK — Plan 00104 thin shim**            |

**The failure mode on host-a** was the *skill-level* `install.sh` (row 4), which has no glob discovery at all — it only checked `python3` (3.9.21) against `requires-python` (>=3.11) and aborted. Even fixing `scripts/upgrade.sh` and `paths.py` to use glob-and-sort would not have helped; the skill `install.sh` runs *before* the canonical scripts are even on disk.

**Why glob-and-sort, not enumerate** (operator's question on 2026-05-26): hardcoded lists are stale by design. `python3.14` shipped 2025-10; any project pinned to `(3.13, 3.12, 3.11)` will miss it. The glob `python3.[1-9][0-9]` matches `python3.10` through `python3.99` — covers every realistic minor version with no maintenance. Sort numerically by minor (`sort -t. -k2,2n`) to pick the highest after filtering by floor.

## Tasks

### Phase 1: Design

- [ ] **Task 1.1**: Specify the canonical bash helper API in `scripts/lib/python_discovery.sh`
  - [ ] Function signature: `find_latest_python <min_major.min_minor> [--require-pyproject <path>]` → stdout: absolute path to interpreter; exit 0 success, exit 1 not found
  - [ ] Precedence: `$HOOKS_DAEMON_PYTHON` (validated against floor) → glob `$PATH` for `python3.[1-9][0-9]` → sort by minor desc → first that meets floor
  - [ ] On failure: print to stderr a remediation hint naming an interpreter **observed during the glob** (not a hardcoded one); if no candidates at all, say so explicitly
  - [ ] Reuses `parse_min_python.sh` for `--require-pyproject` parsing — no inline regex
- [ ] **Task 1.2**: Specify the canonical python helper API in `daemon/paths.py`
  - [ ] Function: `find_latest_python(min_version: tuple[int,int], *, require_pyproject: Path | None = None) -> Path | None`
  - [ ] Same precedence, same glob, same sort
  - [ ] Returns `None` on failure (caller decides error format); paired with `find_latest_python_or_explain()` that returns `(path | None, list[ProbeResult])` for diagnostics
  - [ ] Delete `_COMPATIBLE_PYTHON_CANDIDATES` constant — gone forever
- [ ] **Task 1.3**: Decide bash↔python parity strategy
  - [ ] Option A: Bash helper invokes the python helper via existing `python3` (fragile when python3 is too old — the exact case we're fixing)
  - [ ] Option B: Bash helper is self-contained POSIX shell; python helper is independent re-implementation; behavioural parity enforced by shared test fixtures
  - [ ] **Decision**: Option B. The bash helper MUST work when no compatible python exists yet (skill bootstrap case). The two implementations are tested against the same fixture set in Phase 6.

### Phase 2: TDD — Canonical Bash Helper

- [ ] **Task 2.1**: Write failing tests in `tests/acceptance/test_python_discovery_bash.py`
  - [ ] Fixture: synthesised `$PATH` with controlled set of fake `python3.N` symlinks (each prints its version)
  - [ ] Test: empty PATH → fail with "no python3.N found"
  - [ ] Test: only `python3.9` present, floor 3.11 → fail with "found python3.9 — below floor, install 3.11+"
  - [ ] Test: `python3.9`, `python3.13`, `python3.14`, floor 3.11 → returns `python3.14`
  - [ ] Test: `python3.9`, `python3.13`, `python3.14`, floor 3.11, `HOOKS_DAEMON_PYTHON=python3.13` → returns `python3.13` (env wins when satisfies floor)
  - [ ] Test: `HOOKS_DAEMON_PYTHON=python3.9`, floor 3.11 → fail explicitly ("env override violates floor")
  - [ ] Test: `--require-pyproject` with `requires-python = ">=3.12"` overrides any lower floor arg
  - [ ] Test: `python3.13` exists but is not executable → skipped
- [ ] **Task 2.2**: Implement `scripts/lib/python_discovery.sh` to make tests pass
  - [ ] Self-contained POSIX shell, no python dependency
  - [ ] Glob: `"$dir"/python3.[1-9][0-9]` per `$PATH` entry
  - [ ] Sort: `sort -u -t. -k2,2n` then `tail -1` after filtering
  - [ ] Version probe: `"$bin" --version 2>&1 | awk '{print $2}'` parsed against floor
- [ ] **Task 2.3**: Run QA, verify all tests pass

### Phase 3: TDD — Canonical Python Helper

- [ ] **Task 3.1**: Write failing tests in `tests/unit/daemon/test_paths_python_discovery.py`
  - [ ] Same fixture matrix as Task 2.1, expressed via `monkeypatch` on `$PATH`
  - [ ] Test parity assertion: for each fixture, bash helper and python helper return the same interpreter
- [ ] **Task 3.2**: Implement `find_latest_python()` and `find_latest_python_or_explain()` in `daemon/paths.py`
  - [ ] Use `os.environ["PATH"].split(os.pathsep)` + `pathlib.Path.glob("python3.[1-9][0-9]")`
  - [ ] Probe via `subprocess.run([bin, "--version"], capture_output=True, timeout=3)`
  - [ ] Delete `_COMPATIBLE_PYTHON_CANDIDATES`, `_find_compatible_python_on_path()`, fold the latter's callers into `find_latest_python()`
- [ ] **Task 3.3**: Run QA, verify all tests pass and coverage ≥95% on the new functions

### Phase 4: Migrate WET Sites

Each migration is its own commit so we can bisect if any caller regresses.

- [x] ✅ **Task 4.1**: `scripts/upgrade.sh` — replaced `find_compatible_python()` and `_is_python_at_least_311()` (200 lines) with a 25-line thin wrapper that sources `scripts/lib/python_discovery.sh` and calls `find_latest_python 3.11 "$pyproject"`. Two obsolete extraction-pattern integration tests (`test_bootstrap_explicit_probe.py`, `test_bootstrap_requires_python_cross_check.py`) deleted — sourced functions no longer exist; behaviours covered by 13 tests in `tests/acceptance/test_python_discovery_bash.py`. Sweep of 49 bootstrap/upgrade tests passes.
- [x] ✅ **Task 4.2**: `scripts/install/prerequisites.sh` — `_is_python_at_least_311()` removed; `check_python3()` collapsed to a thin wrapper that sources `scripts/lib/python_discovery.sh` and delegates to `find_latest_python 3.11`. Manual smoke test `test_prerequisites_manual.sh` passes against migrated code (Python 3.11 found at `/usr/bin/python3.11`, all prerequisite checks green).
- [x] ✅ **Task 4.3**: `src/.../skills/hooks-daemon/scripts/install.sh` — **the host-a fix**. Added `PYTHON_DISCOVERY_URL` constant; the pre-check block now fetches `scripts/lib/python_discovery.sh` from `main` alongside `pyproject.toml`, sources it, and delegates to `find_latest_python "$MIN_PY" "$PYPROJECT_TMP"`. On success the discovered absolute path is exported as `HOOKS_DAEMON_PYTHON` so the inner installer reuses it (no redundant probe). On failure the helper's own observed-interpreter diagnostic is shown — no hardcoded `python3.11` suggestion. The plan called for a `--require-pyproject` flag; the canonical helper signature is actually positional `find_latest_python <min> [pyproject_path]`, so the migration uses the real signature. Smoke-tested against synthesised PATH layouts: host-a scenario (python3=3.9 + python3.13/python3.14 present) selects `python3.14`; degraded scenario (only python3=3.9) aborts with "No python3.NN interpreter found on $PATH" — no hardcoded suggestion of a missing version.
- [ ] **Task 4.4**: `src/.../daemon/paths.py::can_inline_bootstrap()` — replace `_find_compatible_python_on_path()` call with `find_latest_python()`. `BootstrapDecision` missing-id stays `"compatible-python"` for backward compat.
- [ ] **Task 4.5**: `scripts/lib/resolve_venv.sh::_rv_pick_python()` (lines 85-131) — `--fallback-target python3` branch becomes `--fallback-target $(find_latest_python ...)`. Other precedence rungs unchanged.
- [ ] **Task 4.6**: Grep audit. Run `rg -n 'python3\.1[12345]'` across the repo. Every remaining match must be either a test fixture, a docs example, or justified (e.g. CI matrix). Document each survivor in the plan completion notes.

### Phase 5: host-a Field-Report Closure

- [ ] **Task 5.1**: Replay the host-a scenario as a deterministic acceptance test in `tests/acceptance/test_skill_install_python_discovery.py`
  - [ ] Fixture: `$PATH` contains `/usr/bin/python3` → 3.9.21, `/usr/bin/python3.13` → 3.13.11, `/usr/bin/python3.14` → 3.14.0
  - [ ] Invoke production `src/.../skills/hooks-daemon/scripts/install.sh` against a mocked release
  - [ ] Assert: install proceeds using `python3.14`, no `HOOKS_DAEMON_PYTHON` required, no abort
  - [ ] Assert: if `python3.13` and `python3.14` are removed and only `python3` (3.9) remains, the abort message reads `"available interpreters on PATH: python3 (3.9.21) — all below floor 3.11. Install python3.11 or newer."` — NOT a hardcoded `python3.11` suggestion
- [ ] **Task 5.2**: Add this test to RELEASING.md Step 12.0 H-1 acceptance gate (alongside the existing 19 tests). Update memory note `H-1 gate test count` from 19 to 20.

### Phase 6: Parity & Regression

- [ ] **Task 6.1**: Shared fixture set in `tests/fixtures/python_discovery/` — JSON describing PATH layouts and expected interpreter selection. Both Phase 2 and Phase 3 tests consume it.
- [ ] **Task 6.2**: Property-style test: for 50 randomised fixture combinations, bash helper and python helper agree on selected interpreter (or both fail with structurally equivalent reasons).
- [ ] **Task 6.3**: Full QA: `./scripts/qa/run_all.sh` — all 13 checks pass.
- [ ] **Task 6.4**: Daemon restart verification.

### Phase 7: Release

- [ ] **Task 7.1**: Run `/release` skill. Bump is MINOR (new helper API, no breaking changes for callers — `HOOKS_DAEMON_PYTHON` still honoured, fingerprint paths unchanged).
- [ ] **Task 7.2**: Release notes call out the host-a scenario explicitly so operators in the same position know the upgrade resolves it.
- [ ] **Task 7.3**: Post-upgrade task entry under `CLAUDE/UPGRADES/UNRELEASED/post-upgrade-tasks/` documenting that operators no longer need `HOOKS_DAEMON_PYTHON=python3.NN` workaround for the "default python3 too old" case.

## Dependencies

- Depends on: Plan 00104 (canonical `resolve_venv.sh` library) — **Complete**
- Depends on: Plan 00109 (skill thin-shim model) — **Complete**
- Blocks: future Python 3.14+ compatibility work (becomes automatic after this lands)
- Related: Plan 00100 (venv SSOT consolidation) — Phases 3.5/4/5/6 still deferred; this plan does not unblock them but shares the "DRY across bash and python" theme

## Technical Decisions

### Decision 1: Glob-and-sort over hardcoded enumeration

**Context**: Existing helpers all hardcode `(3.13, 3.12, 3.11)` or similar. host-a had `python3.14` installed but neither helper would have found it without explicit env var.

**Options Considered**:

1. **Hardcoded list, bumped per release** — simple, but stale by design and requires a daemon release for every CPython release.
2. **Glob `python3.[1-9][0-9]` + sort by minor** — covers `3.10`–`3.99` with zero maintenance. Matches how tab completion and `compgen -c python3` work internally.
3. **Wrap `pyenv` / `uv python list`** — adds a hard dependency on tooling that may not be installed on minimal hosts (the skill bootstrap case).

**Decision**: Option 2. The glob form is what every shell already does under the hood; the daemon should match. Matches the user's intuition on 2026-05-26 ("the glob/sort approach seems more sensible").

**Date**: 2026-05-26

### Decision 2: Independent bash and python implementations, not one wrapping the other

**Context**: Tempting to make the bash helper invoke the python helper for DRY. But the skill `install.sh` runs **before** any python is guaranteed to be available — that's the whole reason it exists.

**Options Considered**:

1. **Bash wraps python** — minimal duplication, but breaks the bootstrap case (chicken-and-egg).
2. **Python wraps bash** — works, but couples python imports to subprocess and breaks isolation for unit tests.
3. **Two independent implementations, shared fixture set, parity test** — true DRY at the *behavioural* level even though the source has two implementations.

**Decision**: Option 3. Implementation duplication is acceptable when behaviour is asserted equivalent by tests; coupling discovery to one runtime would break the bootstrap path.

**Date**: 2026-05-26

### Decision 3: Error messages name observed interpreters, never hardcoded ones

**Context**: The host-a abort suggested `python3.11` — which wasn't installed. The operator wasted time investigating what they assumed was the recommended interpreter.

**Decision**: Failure output must enumerate what was **actually observed during the glob** ("found: python3, python3.9 — all below floor 3.11"). If nothing was found, say so. Never name a version that the discovery code didn't see.

**Date**: 2026-05-26

## Success Criteria

- [ ] `rg -n '_COMPATIBLE_PYTHON_CANDIDATES|_is_python_at_least_311' src/ scripts/` returns zero matches outside `python_discovery.sh` and `paths.py::find_latest_python`
- [ ] `rg -n '\bpython3\.1[12345]\b' src/ scripts/` returns only test fixtures and docs — no production discovery code
- [ ] host-a acceptance test (Task 5.1) passes — `python3.13` / `python3.14` auto-selected, no env override needed
- [ ] Parity test (Task 6.2) — bash and python helpers agree on all 50 fixtures
- [ ] `./scripts/qa/run_all.sh` — all 13 checks pass
- [ ] Daemon restart verified RUNNING
- [ ] H-1 gate count in RELEASING.md updated 19 → 20
- [ ] Release notes reference the host-a scenario by name

## Risks & Mitigations

| Risk                                                          | Impact   | Probability | Mitigation                                                                                                                                          |
| ------------------------------------------------------------- | -------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Bash and python helpers drift apart                           | Medium   | Medium      | Parity test (Task 6.2) blocks merge if any fixture disagrees                                                                                        |
| Removing `HOOKS_DAEMON_PYTHON` precedence breaks pinned hosts | High     | Low         | Precedence preserved as rung 1 of ladder; explicitly tested (Task 2.1)                                                                              |
| Glob matches non-CPython binaries (e.g. `python3.99-config`)  | Low      | Low         | Glob is `python3.[1-9][0-9]` — `-config` is excluded by trailing char class. Tested with realistic `/usr/bin/python3*` fixture from host-a output |
| Skill `install.sh` migration regresses bootstrap              | Critical | Low         | Task 5.1 acceptance test replays exact host-a layout end-to-end against production skill script                                                   |
| Parsing `python3.99 --version` output varies by distro        | Low      | Low         | Use regex `^Python (\d+)\.(\d+)` — handles `Python 3.13.11`, `Python 3.14.0a1`, debian-suffixed builds                                              |

## Notes & Updates

### 2026-05-26

- Plan created in response to host-a field report (`untracked/hooks-daemon-upgrade-python-version.md`) and operator instruction to "make this DRY, holistic" with "no multiple WET approaches".
- Operator preference recorded in conversation: glob-and-sort over hardcoded version lists; no single-digit minor support (`python3.9` and below are filtered out structurally by the glob `python3.[1-9][0-9]`).
- Decision 1 records the rationale for glob over hardcoded lists.
