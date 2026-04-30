# Review #3 — Opus 4.6 Post-Amendment Hostile Review (2026-04-30)

## Verdict: FATAL

The plan, as amended through Reviews #1 and #2, has resolved the original five-site bug-equivalence and the silent-fallback regression. However, this third pass surfaces **seven new FATAL findings** (F12–F18) and **nine new RISKY findings** (R17–R25) that will brick the daemon, brick the QA gate, or ship a broken release if the plan is executed as currently written.

The most serious problems are not subtle: the plan undercounts `venv_resolver.sh` callers by 7 (only 2 of 9 are listed in Task 4.4), references the wrong path for `init.sh::_resolve_python_cmd` (file is at `/workspace/init.sh`, not in the skill bundle), conflates two distinct meanings of "python3" in Decision 6 (interpreter command name vs. shell-fallback identifier), and specifies no commit ordering for the irreversibly-coupled Phase 4 changes.

The plan is salvageable but must NOT proceed to Phase 2 in its current form.

---

## Resolved Prior Concerns

The amended plan correctly addresses (relative to Reviews #1 and #2):

- F1/F7 (5-site bug-equivalence): all five sites enumerated in Overview, all five targeted by Phase 4 tasks.
- F2 (tomllib import-time crash): Phase 2 promoted ahead of Phase 3/4 as primary defense-in-depth.
- F4 (silent legacy fallback): Decision 5 explicitly forbids the canonical resolver from emitting `untracked/venv/bin/python`; Task 3.2 guards.
- F6/F11 (false race-condition diagnosis): Phase 4 (race) dropped; root cause correctly relocated to `venv.sh:261` hardcoded `python3`.
- F8 (`venv_lock_hash_matches` hardcoded `python3`): Task 4.6 fixes.
- F9 (multi-host hostname dimension): Decision 2 revised, all three dimensions composed inline; Task 3.10 covers.
- F10 (skill-bundle deploy ordering): Task 4.8 calls out install-deploy ordering verification.
- A18 (`${HOOKS_DAEMON_PYTHON:-python3}` diceroll): Decision 6 added per user instruction.

## New FATAL Findings

### F12 — Task 4.4 catastrophically undercounts venv_resolver.sh callers; deletion will brick the QA gate

**Severity:** FATAL — irreversibly breaks the daemon QA top-level gate the moment Task 4.4 lands.

**Evidence:** Repository-wide grep for `venv_resolver\.sh` (excluding plan/context/release-note self-references) returns **9 distinct caller sites**, not 2:

| Caller | Lines | In Plan Task 4.4? |
|---|---|---|
| `scripts/upgrade_version.sh` | 43, 44 | listed |
| `scripts/qa/<top-level QA gate>` | 17–19 | NOT LISTED |
| `scripts/qa/run_strategy_pattern_check.sh` | 31–33 | NOT LISTED |
| `scripts/debug_hooks.sh` | 14–16 | NOT LISTED |
| `scripts/validate_worktrees.sh` | 32–34 | NOT LISTED |
| `scripts/setup_worktree.sh` | 41–42 | NOT LISTED |
| `scripts/detect_location.sh` | 28–30 | NOT LISTED |
| `scripts/install/project_detection.sh` | 26–28 | NOT LISTED |
| `scripts/install/rollback.sh` | 25–27 | NOT LISTED |

Task 4.4 reads: *"DELETE `scripts/install/venv_resolver.sh` entirely. Update its callers (`upgrade_version.sh:44, 86`) to source `scripts/lib/resolve_venv.sh` directly."*

The moment that file is deleted with only `upgrade_version.sh` updated, **seven additional bash scripts become broken** — including the top-level QA gate, the very script Phase 5 Task 5.1 relies on to validate the rest of the plan. It would fail at line 19 (`source: file not found`) before any QA check executes. The plan would have no way to verify itself.

`scripts/install/rollback.sh` is the most damaging miss: rollback is the operator escape hatch when an upgrade goes wrong. Bricking rollback while landing a venv-resolution refactor is precisely the recovery vector you cannot afford to lose.

**Remedy:** Task 4.4 must enumerate ALL 9 caller sites (not 2) and either (a) update each to source the new canonical, or (b) keep `venv_resolver.sh` as a one-line shim that re-exports the canonical API under the legacy function names, deferring deletion to a follow-up plan. Option (b) is strictly safer for a patch release.

### F13 — Task 4.5 references wrong file path for `init.sh::_resolve_python_cmd`; fix will not be applied where intended

**Severity:** FATAL — Task 4.5 is ambiguous about which `init.sh` to fix; the file is not where the plan implies.

**Evidence:** Task 4.5 says *"Reduce `init.sh::_resolve_python_cmd` (`init.sh:244-292`)"*. The plan Overview line 21 lists this resolver alongside files in `src/.../skills/hooks-daemon/scripts/`, suggesting the reviewer believed it lived there. Glob `**/init.sh` returns:

- `/workspace/init.sh` (actual location, contains `_resolve_python_cmd` at lines 244–292)
- `/workspace/untracked/claude-code-hooks-daemon/init.sh` (downstream user mirror)
- `/workspace/untracked/repos/site/.claude/init.sh` (worktree clone)
- `/workspace/.claude/worktrees/agent-af3973f4/init.sh` (worktree)

`init.sh` lives at the **repository root**, not in the skill bundle. This matters because:

1. `init.sh` is sourced by **every hook wrapper on every event fire** (the hot path Review #2 R12 flagged). It is shipped to every consumer repo at install time, copied verbatim from daemon source. Task 4.8 says "ship `scripts/lib/resolve_venv.sh` AND `scripts/lib/python_fingerprint.sh` in the skill bundle" — but `init.sh` lives outside the skill bundle, so the source-path resolution at `init.sh:251-258` looks for `python_fingerprint.sh` at `$HOOKS_DAEMON_ROOT_DIR/scripts/install/python_fingerprint.sh` and `$PROJECT_PATH/scripts/install/python_fingerprint.sh` — neither matches the canonical deploy location `scripts/lib/`.
2. Decision 5 says "*Sources `scripts/lib/python_fingerprint.sh` from a stable path that works in both deploy locations (repo source + skill bundle)*" — but that is two locations, not three. The downstream-clone deployment of `init.sh` is a third deploy location not covered.

**Remedy:** Plan must (a) correct the file path everywhere it is referenced (clarify whether the target is repo-root `init.sh` or the installed copy at `.claude/hooks-daemon/init.sh`), (b) add explicit deploy-target enumeration for `python_fingerprint.sh` covering all three locations: skill-bundle (`.claude/hooks-daemon/scripts/lib/`), self-install repo (`scripts/lib/`), AND the legacy `scripts/install/` location that `init.sh:253` currently probes.

### F14 — Decision 6 conflates the candidate command `python3` with the shell-fallback identifier `:-python3`; static check will miss real regressions

**Severity:** FATAL — strict literal application of Decision 6 will leave a class of regressions undetected.

**Evidence:** Decision 6 says *"`skills/hooks-daemon/scripts/install.sh:40-89` (FAIL-FAST template) currently includes a `python3` step in its probe list. This step is REMOVED — replaced with a hard-fail when none of `3.13/3.12/3.11` is present."* Task 4.7 then says *"Replace `${HOOKS_DAEMON_PYTHON:-python3}` in bootstrap layers (`skills/hooks-daemon/scripts/install.sh:40-89`, `skills/hooks-daemon/scripts/upgrade.sh:86-110`) with the explicit `python3.13` -> `python3.12` -> `python3.11` probe per Decision 6."*

These are **not the same construct**:
- The probe-list `python3` is a literal command name passed to `command -v`. Removing it from the probe list is the right call (a host with `python3 -> 3.9` should fail-fast even if `python3` is on PATH).
- The shell parameter expansion `${HOOKS_DAEMON_PYTHON:-python3}` substitutes the literal string `python3` when the env var is unset. Removing it means deciding what to substitute instead.

The static check in Task 4.9 — *"Greps the entire repo for `${[A-Z_]*:-python3}` and fails if any match outside the bootstrap probe block"* — only catches the parameter-expansion form. It does NOT catch a bare `local candidates=("python3" "python3.13" ...)` array, which is what `upgrade.sh:86-110` actually contains today: `local candidates=("python3" "python3.13" "python3.12" "python3.11")`.

So Task 4.7 Decision-6 spec says "remove `python3` from the candidate list", but the static check in Task 4.9 would not catch a regression where someone re-added it.

Worse: the Decision 6 text *"Bootstrap explicitly probes `python3.13` -> `python3.12` -> `python3.11`"* leaves Python 3.14+ **unsupported by hardcoding**. The next time a stable Python ships, the bootstrap will silently refuse to find it on a brand-new host with only `python3.14` installed, even though `python3.14` would be the *most* compatible interpreter. The plan claims to be a fail-fast clarity fix but quietly bakes in a maximum-Python-version ceiling.

**Remedy:** (a) Decision 6 must specify probe-list contents AND parameter-expansion forbidden-patterns separately; (b) Task 4.9 must add a check for bare `python3` strings in candidate-list bash arrays in bootstrap files; (c) the probe sequence must be open-ended (e.g. probe `python3.13` -> `python3.12` -> `python3.11` AND ALSO try any `python3.NN` matching `NN >= 11` discovered via `compgen -c python3.`) so future stable Pythons work without daemon source changes.

### F15 — Phase 4 task ordering is unspecified; intermediate commits will brick the QA gate irrecoverably

**Severity:** FATAL — there is no commit-by-commit safe path through Phase 4.

**Evidence:** Phase 4 has 11 tasks. The CLAUDE.md non-negotiable rule "Never accumulate more than ~300 lines of uncommitted changes" requires checkpoint commits. But the dependency graph between Phase 4 tasks is non-trivial:

- Task 4.1 (create canonical lib) is a prerequisite for 4.2/4.3/4.4/4.5.
- Task 4.5 (`init.sh` shim) writes the canonical path into the hot path. If the canonical lib is mis-deployed, **every hook event blocks**.
- Task 4.6 (`venv.sh:261` hardcoded `python3` -> `resolve_venv_python`) requires the canonical lib to exist on the upgrade path. But `venv.sh::ensure_venv` runs at daemon startup. If the canonical is sourced under `set -euo pipefail` and the source-path resolution misfires, the daemon will not start.
- Task 4.10 (wire `check_canonical_callers.sh` into the QA top-level) MUST land AFTER Task 4.7 (replace `${HOOKS_DAEMON_PYTHON:-python3}` in bootstrap), or the QA gate goes red. But it must land BEFORE the release pipeline QA Verification Gate.

The plan does not specify commit ordering. A naive Sonnet sub-agent would commit Tasks 4.1–4.5 in alphabetical order, leaving `venv_resolver.sh` deleted in a commit before all 9 callers are updated (F12), bricking the QA gate, then trying to recover by force-pushing — which the project explicitly forbids.

**Remedy:** Phase 4 must specify an explicit commit order with a per-commit verification step:

```
Commit 4.A: Add scripts/lib/resolve_venv.sh + python_fingerprint.sh (purely additive). Verify QA passes.
Commit 4.B: Update ALL 9 venv_resolver.sh callers to source canonical (do NOT delete venv_resolver.sh yet). Verify QA passes.
Commit 4.C: Replace _resolve-venv.sh body with shim. Verify QA passes.
Commit 4.D: Replace venv-include.bash::_resolve_venv_dir body with shim. Verify QA passes.
Commit 4.E: Replace init.sh::_resolve_python_cmd body with shim. Verify daemon restart RUNNING.
Commit 4.F: Replace venv.sh:261 hardcoded python3. Verify daemon restart RUNNING after upgrade-path exercise.
Commit 4.G: Replace bootstrap ${HOOKS_DAEMON_PYTHON:-python3} per Decision 6.
Commit 4.H: Add scripts/qa/check_canonical_callers.sh. Verify it passes against current tree.
Commit 4.I: Wire check_canonical_callers.sh into the QA top-level script.
Commit 4.J: Convert venv_resolver.sh into a 5-line shim that re-exports the canonical (NOT deletion — F12).
```

Without this, Phase 4 cannot be executed safely.

### F16 — Task 6.3 conflates two test scenarios that must be covered separately

**Severity:** FATAL — the "Python-3.9 acceptance test" as currently described will fail to reproduce the field bug.

**Evidence:** Task 5.4 says *"Choose one mechanism and lock it: (a) Docker `python:3.9-slim` container with the daemon mounted in (preferred — most realistic), or (b) `/tmp/fake-python3` shim that pretends to be 3.9 and is first on PATH."* Task 6.3 then references this in Phase 6.

But the **field report bug** is on a host that has BOTH `python3 -> 3.9.21` AND `python3.13` available, with the daemon running healthily on the 3.13-built venv. The bug is that wrappers fall back from the venv to legacy because they invoked the SSOT with the wrong interpreter.

A `python:3.9-slim` Docker container has ONLY `python3 -> 3.9`. There is no `python3.13` available. The bootstrap will fail-fast (which is what the plan intends), but the **post-bootstrap regression** (the actual field bug) cannot be exercised in this image because no compatible venv can be created.

A `/tmp/fake-python3` shim approach is closer but still wrong: the shim sits on PATH ahead of the system `python3`, but a real RHEL host has `/usr/bin/python3 -> 3.9` AND `/usr/bin/python3.13` on PATH simultaneously. The shim approach does not replicate the multi-interpreter reality.

**Remedy:** Task 5.4 / Task 6.3 must specify TWO distinct fixtures:
1. **Bootstrap-fail fixture**: `python:3.9-slim` (or equivalent) with NO compatible interpreter. Asserts bootstrap exits non-zero with directive.
2. **Post-bootstrap-regression fixture** (the field bug): a host (or container) with `python3 -> 3.9` AND `python3.13` BOTH available, where the daemon was previously bootstrapped against `python3.13` and a venv exists. Asserts diagnostic scripts succeed using the venv, never falling through to the legacy path. `python:3.13-slim` with a symlinked `/usr/local/bin/python3 -> /usr/bin/python3.9` is one workable construction; or use Fedora multi-Python container.

Without fixture (2), the v3.9.0 regression cannot be regression-tested.

### F17 — `set -euo pipefail` cascade through `venv-include.bash:56` is uncovered by Task 3.9

**Severity:** FATAL — the canonical library will silently kill caller shells in a non-obvious way.

**Evidence:** `/workspace/scripts/venv-include.bash` line 8 sets `set -euo pipefail`. Line 56 (`VENV_DIR="$(_resolve_venv_dir)"`) calls the resolver at module load. If `_resolve_venv_dir` is reduced to a shim that sources the canonical, AND the canonical no-venv path uses `exit 5` per Decision 5, then sourcing `venv-include.bash` from any caller will cause the **entire calling shell** to exit 5 — not just the function.

This is exactly what `set -euo pipefail` does to subshells, command substitution, and source-blocks. The plan Task 3.9 (*"sourcing the canonical library under `set -euo pipefail` does not abort the parent shell on a benign no-match condition; only `exit` paths terminate, and they emit a clear stderr message first"*) acknowledges the issue but specifies the wrong contract: the test asserts that `exit` paths DO terminate the shell. That is the bug.

When `health-check.sh` sources `venv-include.bash` to inspect a half-installed daemon, it expects to *gracefully report* the missing venv to the operator — not to be silently killed by a bare `exit 5` from a sourced module-load expression. The diagnostics suite was designed around graceful exit-code propagation, not catastrophic shell termination.

**Remedy:** The canonical library API contract must distinguish between:
- **Function returns** (`return 5`) when called from another function — caller decides what to do.
- **Process exits** (`exit 5`) when run as a top-level script.

The current Decision 5 specs only `exit:`, conflating the two. Task 3.9 must invert its assertion: sourced-and-called-as-function must `return`, never `exit`. Top-level-invoked must `exit`. Add `test_resolver_when_sourced_under_pipefail_does_not_kill_caller_shell` covering the `venv-include.bash:56` path specifically.

### F18 — Static check `scripts/qa/check_canonical_callers.sh` is ill-defined and will produce false positives

**Severity:** FATAL — Will fail Task 4.10 (wire into QA top-level) the moment release notes, plans, or test fixtures contain the forbidden pattern in any context.

**Evidence:** Task 4.9 specifies the check as *"Greps the entire repo for `${[A-Z_]*:-python3}` and fails if any match outside the bootstrap probe block"*. But "the entire repo" includes:

- `RELEASES/v3.8.2.md` — release notes documenting the historical pattern.
- `CHANGELOG.md` — same.
- `CLAUDE/Plan/00103-v3.9.1-venv-resolution-failfast/PLAN.md` — THIS plan, which contains the pattern in Overview, Decision 6, Task 4.7, etc. as text discussing the change.
- `tests/integration/test_install_venv_resolver.py` and any integration test fixtures.
- `CLAUDE/Plan/00100-venv-ssot-consolidation/PLAN-v1.md` — historical plan text.
- The "allowlist the bootstrap probe block by exact line-anchor match" in the risk-mitigation table is a one-line gesture that does not translate to a robust grep allowlist (line anchors shift on every edit).

The risk-mitigation says *"Scope to repo source paths; exclude `vendor/`, `node_modules/`, `untracked/`, and the test fixture directory"* — but does NOT exclude `CHANGELOG.md`, `RELEASES/`, `CLAUDE/`, or the README, all of which legitimately discuss the pattern.

**Remedy:** Task 4.9 must specify the include set positively (only `scripts/`, `src/`, `init.sh`, the skill-bundle scripts directory) and exclude all documentation paths. The line-anchor allowlist must be replaced with an inline marker comment recognised by the grep, e.g.:

```bash
# CANONICAL_CALLERS_ALLOWED_PROBE — bootstrap-only python interpreter probe
local candidates=("python3.13" "python3.12" "python3.11")
```

So the static check excludes the line below the marker, and any drift requires editing both the marker and the line — making accidental regressions visible.

---

## Risky Findings

### R17 — Hot-path latency: every hook fire now sources two extra bash files

`init.sh::_resolve_python_cmd` is sourced per hook event (10–100/min in active sessions). Reducing it to a shim that sources `scripts/lib/resolve_venv.sh` AND `scripts/lib/python_fingerprint.sh` adds two `source` calls per fire. Bash `source` of a 200-line file is ~2ms; on a 20Hz hook fire pattern that is 40ms/sec of pure source overhead. Below the 50ms hook latency budget but tight. The fingerprint cache at `untracked/.python-cmd-cache` (Task 4.5: "Preserve the fingerprint cache") helps only after first hit. Recommend: benchmark before/after with `pytest-benchmark` or equivalent and assert <5ms median resolve time.

### R18 — Fingerprint cache chicken-and-egg

Task 4.5 says preserve `untracked/.python-cmd-cache`, but the cache is keyed on the fingerprint, which itself requires a Python invocation to compute. If the cache is invalidated (file deleted, fingerprint mismatch), the canonical re-invokes Python — but the canonical "expected_dir composed inline" path (Decision 5 Algorithm step 1) ALSO requires the fingerprint. So the canonical needs a Python invocation BEFORE it can decide whether to use the fast path. That is the slowness Plan 00100 was supposed to avoid.

### R19 — `HOOKS_DAEMON_PYTHON` override semantics in bootstrap are now ambiguous

Decision 4 says bootstrap "MAY honour `HOOKS_DAEMON_PYTHON` … only when the override interpreter passes `--version` and is `>= 3.11`. Failure = abort with directive." But Task 4.7 says replace `${HOOKS_DAEMON_PYTHON:-python3}` with the explicit probe. So when does the override apply — before the probe (and abort if invalid) or as the first probe candidate? The two specifications are non-orthogonal. Recommend: make the override a hard-precedence step that runs BEFORE the version probe, with explicit fail-fast on invalid value.

### R20 — `paths.py:407` `tomllib.TOMLDecodeError` deferral is more invasive than Task 2.2 suggests

`tomllib.TOMLDecodeError` referenced at module top of an `except` clause becomes a `NameError` if `tomllib` is deferred. Plan says "Defer `tomllib.TOMLDecodeError` reference at `paths.py:407` accordingly (use a runtime-imported alias or guard the except clause)". A "runtime-imported alias" approach risks losing the exception narrow-catching: catching a deferred class via `except (tomllib.TOMLDecodeError if tomllib else Exception)` is wider than the current contract. Recommend: factor the `except` into a helper function that imports `tomllib` locally and catches the narrow type.

### R21 — `untracked/venv` legacy path test (Task 3.2) does not cover the case when the legacy directory is the ONLY thing present

Pre-v3.7.0 install with no fingerprint-keyed venv. The plan says the canonical "REFUSES to emit it" — meaning such installs will fail-fast. Decision 1 / Non-Goal #4 acknowledge this. But the upgrade path (`upgrade.sh`) for a pre-v3.7.0 install will now hit the canonical and fail before the upgrade can clean up the legacy directory. There is a circular bootstrap dependency. Mitigation: `upgrade.sh` must stay independent of the canonical until the upgrade has been completed (Layer-1 only) — but Task 4.7 explicitly converts upgrade.sh to use the canonical-style probe, possibly deleting the recovery path.

### R22 — Multi-host fingerprint with no HOSTNAME set: ambiguity unresolved

Decision 2 algorithm step 3: "filter by hostname suffix if HOSTNAME set". Step 5: "Two+ matches -> use FIRST candidate bin/python … to invoke `paths.py resolve-venv` for canonical disambiguation." But on an NFS-shared `untracked/` with two hostname-suffixed venvs and no `HOSTNAME` set, step 3 filter is a no-op, leaving 2 matches, falling to step 5. Step 5 invokes `paths.py resolve-venv` using one of the venvs Python. But which Python is correct? The Python SSOT only knows which venv matches the *current* host fingerprint. So tiebreak SSOT will return one venv — but the fingerprint composition in step 1 already failed because no `HOSTNAME_SUFFIX` was applied. Result: tiebreak picks the venv built by some other host. Caller then runs the daemon with the wrong host venv, which may use NFS-incompatible paths in compiled `.pyc` caches. Recommend: explicit fail-fast when `HOSTNAME` is unset AND multiple matching venvs exist, with directive to `export HOSTNAME=...`.

### R23 — Bootstrap probe order `3.13 -> 3.12 -> 3.11` may pick a non-default Python on multi-Python hosts

A host with `/usr/bin/python3 -> 3.13` AND `/usr/bin/python3.11` AND `/usr/bin/python3.12` has all three available. The probe picks 3.13 (correct). But on a host where the project `pyproject.toml` declares `requires-python = ">=3.11,<3.13"` (excluding 3.13 deliberately for a known-good-version constraint), the bootstrap will pick 3.13 and the daemon will refuse to install. Plan does not specify cross-checking the discovered interpreter against `requires-python`. Bootstrap layer at `install.sh:40-89` already does this for the single chosen interpreter; needs to be repeated for each probe candidate.

### R24 — `check_canonical_callers.sh` failure mode masks the real fix on regression

The static check is a single-shot grep with `exit 1` on any match. When a developer accidentally re-introduces `${VAR:-python3}` in a refactor, the check fails with no signal pointing at the offending file. Recommend: emit a structured stderr line per offending match (`file:line:column: forbidden pattern '${HOOKS_DAEMON_PYTHON:-python3}'`) so QA output makes the regression actionable.

### R25 — Task 5.5 (upgrade.sh preflight) is folded into Phase 5 but has no failing test in Phase 3

Phase 3 enumerates 14 test tasks (3.1–3.14), none of which cover `upgrade.sh` tracked-vs-untracked collision detection. Phase 5 Task 5.5 says *"Failing test + implementation using `git ls-files --others --exclude-standard` filtered against target ref tracked files"* — but Phase 3 already declared "all expected failures fire", which would not include this test. Recommend: move the failing test into Phase 3 (e.g. Task 3.15) for consistency with the plan TDD discipline.

---

## Clear Observations

- The fail-fast contract (Goal 4, Decisions 1/4/6) is internally consistent.
- The DRY consolidation plan is correct in shape — five sites collapsing to one canonical with shims is the right architecture.
- Phase ordering (Phase 2 before Phase 3 before Phase 4) is correct given F2/F11 from prior reviews.
- The decision to keep `venv_resolver.sh` semantically (even if F12 forces it as a shim rather than deleted) preserves existing integration tests.

---

## Reviewer Summary

This is a third-iteration plan that has cleared the major architectural concerns from Reviews #1 and #2 but has accumulated implementation-detail bugs at the level where Sonnet sub-agents will execute it incorrectly. The seven new FATAL findings cluster around three root causes:

1. **Insufficient evidence-gathering before drafting**: F12 (caller count off by 7), F13 (wrong file path), F14 (wrong syntax category), F18 (grep allowlist incomplete) are all repository-grep mistakes — the plan author relied on Reviews #1/#2 enumerations rather than re-verifying against the live tree.
2. **Missing operational specs**: F15 (no commit ordering), F17 (no exit-vs-return contract). The plan describes target end-state but not the safe path to reach it.
3. **Insufficient acceptance fidelity**: F16 (`python:3.9-slim` cannot reproduce the field bug). The acceptance test must replicate the *multi-Python* host configuration that triggered the regression, not the simpler single-Python case.

**Recommendation**: Split into two plans:

- **v3.9.1 hotfix (this plan, scope-narrowed)**: Phase 2 (deferred tomllib) + tactical fixes for the five sites WITHOUT canonical-library refactor. Each site gets the same explicit fix (replace `${HOOKS_DAEMON_PYTHON:-python3}` with explicit probe; remove `2>/dev/null`; remove silent legacy fallback). Ships in days.
- **v3.10.0 structural plan (new plan)**: DRY consolidation into `scripts/lib/resolve_venv.sh`, `venv_resolver.sh` collapse, `init.sh` hot-path optimisation, hostname-NFS fail-fast (R22), `requires-python` cross-check (R23). Ships in weeks with proper acceptance coverage.

This split honours the user "fail fast and clear" directive on the v3.9.1 timeline while giving the DRY refactor the engineering time it needs. Bundling them — as the current plan does — is the source of every FATAL finding above.

The hostile-review contract is satisfied: this third pass has surfaced concrete failure modes that would brick QA, brick rollback, brick the daemon, and ship a regression-untested release. None of them are theoretical.

**Verdict: FATAL. Do NOT proceed to Phase 2 in current form.**
