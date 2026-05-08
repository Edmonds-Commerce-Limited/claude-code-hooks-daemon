# Review #2 — Opus 4.6 DRY-Focused Hostile Review (2026-04-30)

**Verdict**: FATAL (second consecutive)

**Reviewer**: Opus 4.6, second-pass with explicit DRY focus per user feedback ("F1 - so SSOT is failing by not having a single source of truth for how to load python? seems like we need DRY?")

**Outcome**: Reviewer recommends **splitting v3.9.1**: surgical hotfix now (defer tomllib only) + structural v3.10.0 later (full DRY consolidation).

---

## FATAL findings (additive to Review #1's F1-F6)

### F7. Review #1 missed the FOURTH resolver — `init.sh::_resolve_python_cmd` is on the hook hot path

`init.sh:244-292` defines `_resolve_python_cmd()`, sourced by every hook wrapper at `.claude/hooks/{event}` on every event fire. Same broken pattern (`${HOOKS_DAEMON_PYTHON:-python3}` + `2>/dev/null` + legacy fallback). On the field-report Python-3.9 host this means **every hook fire** during the broken state silently falls back, then either serves stale code from the legacy venv or **silently disables all hooks**. Review #1 framed the issue as "three bash files" — should have enumerated `init.sh` as #4. The hot-path bug is worse than the diagnostic-tool bug from the field report.

### F8. Review #1 missed the FIFTH paths.py invocation — `scripts/install/venv.sh:261` hardcodes `python3`

`scripts/install/venv.sh:261` (`venv_lock_hash_matches`) calls `python3 "$paths_script" check-venv-fresh` — literal `python3`, NOT `${HOOKS_DAEMON_PYTHON:-python3}`. On a Python-3.9 host with `HOOKS_DAEMON_PYTHON` correctly exported by Layer 1, this STILL invokes the wrong interpreter, `tomllib` fails, function silently returns "stale" (because `2>/dev/null` swallows the import error), and `ensure_venv` rebuilds the venv on every upgrade attempt.

**This is the actual root cause of the field-report "rebuilding" loop** — Review #1 F6 was right that the plan misdiagnosed it, but Review #1 also misdiagnosed the actual cause. Phase 4 of the plan should be DELETED, not re-scoped. The symptom disappears once F8 is fixed.

### F9. Decision 2 ("glob first") gives the wrong answer when fingerprint dimensions multiply

`paths.py::resolve_existing_venv_python_with_diagnostics` constructs venv path from THREE dimensions: Python version (`py{MM}`), fingerprint (8-hex), and OPTIONAL hostname suffix (when `HOSTNAME` env var set). On multi-host NFS-shared `untracked/`, the glob matches venvs from OTHER hosts whose `bin/python` symlinks point to interpreters that don't exist on the current host. Broken symlinks cascade silently.

**The hostname dimension is documented behaviour** in `CLAUDE.md` ("Multi-Environment Support") — not a corner case. Phase 3 must compose the expected venv dir from ALL THREE dimensions and only glob as a last resort.

### F10. Skill-deployment contract — canonical lib must install atomically with wrappers

When `install.py` deploys the skill bundle, the new canonical `scripts/lib/resolve_venv.sh` must be copied BEFORE the wrappers are made executable, otherwise the first hook fire after install sources a wrapper that sources a missing canonical and crashes with `source: not found`. Plan does not mention this dependency. Self-install hosts unaffected; every external installation will brick.

### F11. Phase 4 is the wrong fix for the wrong cause (extends Review #1 F6)

Once F8 is fixed, the "venv mismatch → rebuilding" output disappears. There is no race; there is a stale-detection false-negative. Delete Phase 4.

---

## RISKY findings (additive)

- **R11**. `init.sh` is sourced by every hook wrapper. Any latency in the canonical resolver multiplies by hook fire frequency (10-100/min during active work). Canonical MUST keep fast-path inlined.
- **R12**. `scripts/qa/run_all.sh` indirectly sources `venv_resolver.sh`. Phase 3 contract change risks breaking CI.
- **R13**. `scripts/debug_hooks.sh`, `scripts/setup_worktree.sh`, `scripts/validate_worktrees.sh` all source `venv_resolver.sh`. None are covered by tests.
- **R14**. Canonical `resolve_venv.sh` will be sourced from skill-deployed AND repo-source paths. SCRIPT_DIR resolution must be robust.
- **R15**. `init.sh::_resolve_python_cmd` writes a `.python-cmd-cache` for performance. Canonical must preserve caching.
- **R16**. `python_fingerprint.sh` is sourced by `init.sh`. Canonical must continue to source it from a stable path that works in both deploy locations.

---

## Recommended DRY architecture: Option A

**One canonical bash library: `scripts/lib/resolve_venv.sh`**, shipped in both repo source AND skill bundle, sourced by all five existing sites with each reduced to a 3-5 line shim.

### Why Option A and not B/C/D

- **B (`_resolve-venv.sh` IS canonical)**: Skill-bundle source coupling is fragile.
- **C (Pure Python SSOT)**: Every hook fire pays Python startup (~120ms cold). `init.sh::_resolve_python_cmd` exists precisely because we need shell-fast resolution on the hot path.
- **D (status quo)**: Rejected by Review #1 F1 and F7-F8 above.

### Canonical contract (sketch)

```
File: scripts/lib/resolve_venv.sh

# Public API (sourced):
#   resolve_venv_python <daemon_dir> [--fallback-target] -> stdout: bin/python path; exit 0 on success
#   resolve_venv_dir    <daemon_dir> [--fallback-target] -> stdout: venv dir; exit 0 on success
#
# Exit codes:
#   0 = success, 5 = no venv (install directive), 6 = corrupt source (reinstall directive),
#   7 = ambiguous (list matches)
#
# NEVER returns legacy untracked/venv path. Function refuses to emit it.
# Honors HOOKS_DAEMON_PYTHON ONLY in --bootstrap context.
#
# Algorithm (post-bootstrap fast path):
#   1. Compose expected dir from (py_version, fingerprint, hostname_suffix) inline.
#   2. If expected dir has valid bin/python: return.
#   3. Glob untracked/venv-py*/bin/python; filter by hostname suffix if HOSTNAME set.
#   4. Exactly one + executable + --version succeeds: return.
#   5. Two+: shellout to paths.py via FIRST candidate's bin/python (after -x and --version verified).
#   6. Zero: exit 5.
```

### The 5-to-1 collapse

| #   | Site                                   | Today (LOC)         | After (LOC)  | What it becomes                                       |
| --- | -------------------------------------- | ------------------- | ------------ | ----------------------------------------------------- |
| 1   | `_resolve-venv.sh`                     | 50                  | ~8           | `source canonical; PYTHON=$(resolve_venv_python ...)` |
| 2   | `venv-include.bash::_resolve_venv_dir` | 20                  | ~5           | source canonical, call `resolve_venv_dir`             |
| 3   | `venv_resolver.sh` (whole file)        | 53                  | DELETE       | callers source canonical directly                     |
| 4   | `init.sh::_resolve_python_cmd`         | ~50                 | ~8           | source canonical (preserve cache)                     |
| 5   | `venv.sh:261`                          | hardcoded `python3` | one-line fix | covered by Phase 5 + var fix                          |

Net delta: ~173 lines of duplicated shell collapse to ~26 lines of shim + ~120 lines of canonical = neutral LOC, but ONE place to fix bugs instead of FIVE.

### Bootstrap ordering

Layer 1 (`upgrade.sh`, `install.sh`, skill `install.sh`) MUST NOT source the canonical. They run BEFORE a venv exists. Their job is `find_compatible_python` (PATH probing) and exporting `HOOKS_DAEMON_PYTHON`. Layer 2+ ONLY source the canonical and ignore `HOOKS_DAEMON_PYTHON`. Enforced by static-check QA script `scripts/qa/check_canonical_callers.sh`.

---

## Plan amendments (additive to A1-A10 from Review #1)

- **A11**: Phase 3 — enumerate `init.sh::_resolve_python_cmd` as resolver #4. Reduce to canonical shim. Preserve fingerprint cache (`untracked/.python-cmd-cache`) at canonical level.
- **A12**: Phase 5 — fix `scripts/install/venv.sh:261` hardcoded `python3` AND ensure tomllib deferral covers `check-venv-fresh`. Test: "lock-hash check on Python 3.9 host with HOOKS_DAEMON_PYTHON set returns correct freshness".
- **A13**: Phase 3 — specify canonical's location (`scripts/lib/resolve_venv.sh`), public API contract, source-path resolution. Add Decision 5 documenting canonical contract.
- **A14**: Static-check QA script `scripts/qa/check_canonical_callers.sh` fails if Layer-1 entry points source the canonical.
- **A15**: Phase 2 — parity-matrix test `tests/integration/test_venv_resolver_parity.py` invokes resolution from all five sites against same fixture; asserts identical output.
- **A16**: Phase 6 — install-deploy contract test: simulate partial deploy (canonical not copied, wrappers copied), verify wrappers fail LOUDLY. Add deploy-order guarantee in `install.py` and `upgrade.sh`.
- **A17 (DROP Phase 4)**: Remove Phase 4 entirely. "venv mismatch → rebuilding" is a side-effect of F8.
- **A18**: Phase 3 — canonical's algorithm composes expected dir from all three dimensions (py-version, fingerprint, hostname). Phase 2 test: "multi-host NFS-shared untracked, HOSTNAME=A → resolver returns A's venv, not B's".

---

## Reviewer's strategic recommendation

> **Two FATAL verdicts in succession indicates this plan needs a structural rewrite, not another patch.** The v3.9.1 patch may need to be split:
>
> - **v3.9.1 hotfix**: just defer tomllib (one-line, surgical, eliminates the field bug for 90% of users)
> - **v3.10.0**: DRY consolidation properly (A11-A18 work)
>
> Reviewer recommends this split.

---

## Files referenced

- `init.sh:244-292` (resolver #4 — Review #1 missed)
- `_resolve-venv.sh:36-44` (resolver #1)
- `scripts/venv-include.bash:35-54` (resolver #2)
- `scripts/install/venv_resolver.sh:26-43` (resolver #3)
- `scripts/install/venv.sh:240-360` (paths.py invocation #5 — Review #1 missed)
- `paths.py:22, 406-407, 580-738, 1233-1263`
- `scripts/upgrade.sh:86-110` (Layer 1, allowed PATH-probe)
- `scripts/upgrade_version.sh:44, 86` (Layer 2 boundary)
- `tests/integration/test_skill_scripts_venv_resolution.py:140-154`
- `skills/hooks-daemon/scripts/install.sh:40-89` (FAIL-FAST template)
