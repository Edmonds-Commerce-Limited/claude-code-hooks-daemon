# Review #1 — Opus 4.6 Hostile Review (2026-04-30)

**Verdict**: FATAL

**Reviewer**: Opus 4.6, hostile-review brief

**Outcome**: Plan rejected pending amendments A1-A10. Re-review required after amendments.

---

## FATAL findings

### F1. Plan only patches ONE of THREE bug-equivalent files

The exact same anti-pattern (`bare python3` + `paths.py` + `2>/dev/null` fallback) exists in:

1. `src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh:36-44` (the file the plan covers)
2. `scripts/venv-include.bash:36-49` (calls `paths.py resolve-venv --fallback-target` with `python_cmd="${HOOKS_DAEMON_PYTHON:-python3}"` and `2>/dev/null`, falls back to legacy `${PROJECT_ROOT}/untracked/venv` on miss)
3. `scripts/install/venv_resolver.sh:35-43` (same pattern; sourced by `upgrade_version.sh:44`, called at `upgrade_version.sh:86` BEFORE `find_compatible_python` exports `HOOKS_DAEMON_PYTHON` — see F2)

The field report's symptom was the skill-shipped `_resolve-venv.sh`. But on the same Python-3.9 host, every developer-facing bash entry point in the daemon repo (`scripts/test.bash`, `scripts/run-qa-runner.sh`, `scripts/health_check.sh`) also fails silently if it sources `venv-include.bash`. The plan's "single source of truth" goal is structurally violated unless ALL THREE wrappers are fixed.

**Remedy**: Phase 3 must rewrite `venv-include.bash::_resolve_venv_dir` and `scripts/install/venv_resolver.sh::resolve_existing_venv_python` with the same glob-first contract. Add tests for both. Phase 2 must add at least one test per file.

### F2. Decision 2 creates an unbootstrappable upgrade from v3.8.x on a Python-3.9 host

Walk-through: a v3.8.2 install on the field-report host has exactly one venv (`untracked/venv-py313-956ed987/`). The user runs `/hooks-daemon upgrade`. Layer 1 (`scripts/upgrade.sh`) calls `find_compatible_python()` (line 86–110) which DOES probe `python3.13/3.12/3.11` on PATH and exports `HOOKS_DAEMON_PYTHON` — fine. But `upgrade_version.sh:86` does `VENV_PYTHON="$(resolve_existing_venv_python "$DAEMON_DIR")"` BEFORE Layer 2 has any chance to forward `HOOKS_DAEMON_PYTHON` into the resolver call.

`venv_resolver.sh` reads `${HOOKS_DAEMON_PYTHON:-python3}` from the env at call-time. This works today because the parent `upgrade.sh` exported it. But under Decision 2 the rewritten resolver would still try the glob first, find one venv, and... what? Per the plan it would just return that venv's python — fine. EXCEPT Decision 2 says "two+ venvs → invoke SSOT with a venv-resident python". Which venv-resident python? The one we just globbed. So the resolver invokes `${some-venv}/bin/python paths.py resolve-venv` to disambiguate, but that venv's python may itself have been built against a Python-3.9 base prefix on a different host (multi-host shared filesystem) and `paths.py` itself imports `tomllib` at top of module.

**The defense-in-depth in Phase 5 IS load-bearing — it is not optional.** The plan classifies it as defense-in-depth and the "Test for deferred tomllib import is hard to write portably" risk is rated Low/High — it should be rated High/High. Without Phase 5, the multi-venv case (which Decision 2 explicitly handles) re-introduces the very bug the plan claims to fix.

**Remedy**: Reclassify Phase 5 from "defense-in-depth" to "primary fix component". Make Task 5.1 (deferred tomllib import) a Phase-3 prerequisite. Note that `paths.py` line 22 is `import tomllib`, lines 406-407 call `tomllib.loads(...)`/`tomllib.TOMLDecodeError`. Moving the import is straightforward — just need to also defer `tomllib.TOMLDecodeError` in the except clause. The "skip if neither works" mitigation is unacceptable: the test must pass.

### F3. Phase 3 task 3.1 ("invoke SSOT only when multiple matches exist using a venv-resident Python") is itself the original bug

A venv-resident Python's `bin/python` is a SYMLINK to the base interpreter. On the field-report host the venv's `bin/python` resolves to `/usr/bin/python3.13` — fine. But on a host where the venv was built earlier with python3.11 and the system `/usr/bin/python3.11` was later removed (broken symlink), the venv's `bin/python` is a dead symlink and `${venv}/bin/python paths.py …` exits with `-bash: …/bin/python: No such file or directory`. The current trace tail in `paths.py:649-661` already calls this out (`step 2 recovery: no compatible alternative …`) — but the rewritten shell wrapper would not benefit from that trace because it's invoking the SSOT WITH a broken venv-resident python. The SSOT never runs.

**Remedy**: Test `_pick_interpreter` semantics in shell — must verify the candidate is actually executable (`-x`) AND `--version` succeeds before using it as the SSOT interpreter. Add a Phase-2 test for "venv with broken bin/python symlink → resolver falls back to next candidate, not exits 1". Currently zero coverage.

### F4. Removing `2>/dev/null` without specifying where stderr goes will pollute every diagnostic invocation

`health-check.sh` at lines 27 (sourcing) and 45 (running daemon CLI) is captured in operator output. `daemon-cli.sh` is invoked by automation. If `_resolve-venv.sh` now prints a 5-line precedence trace to stderr on every healthy run too (per `paths.py:1257-1262` — the trace is only printed on failure, but Phase 5's deferred-import error would surface even on success), users will see `import tomllib` import-time stderr noise on EVERY `/hooks-daemon status` call. The plan does not address whether the trace appears only on failure (ok) or on every invocation (regression).

**Remedy**: Phase 2 must include `test_resolver_is_silent_on_stdout_when_resolution_succeeds` AND `test_resolver_is_silent_on_stderr_when_resolution_succeeds`. The `_cli_resolve_venv` function (paths.py:1233) only prints to stderr on failure, so this is achievable, but the plan must lock it in as a contract.

### F5. Phase 2 Task 2.1 flips the wrong tests

`tests/integration/test_skill_scripts_venv_resolution.py:140-154` (`TestLegacyFallback`) currently tests two cases: (a) NO venv exists at all → returns legacy path; (b) NO `paths.py` symlink (busted install) → returns legacy path. The plan flips both to "non-zero exit, stderr contains directive". But case (b) is genuinely "the daemon source is mangled" — that's a different failure class than "no venv exists". A user whose `paths.py` got corrupted should NOT be told `Run /hooks-daemon install` (that wipes their config). They should be told `Run /hooks-daemon upgrade --force` or `daemon source corrupt: paths.py missing at $DAEMON_DIR/...`. The two tests need DIFFERENT new assertions, not the same one.

**Remedy**: Split Task 2.1 into 2.1a (no venv → install directive) and 2.1b (paths.py missing → reinstall directive, separate error message). Implement two distinct error paths in `_resolve-venv.sh`.

### F6. Phase 4 Task 4.4 misdiagnoses the field report

The field report shows `verify_venv` failing at `upgrade_version.sh:198` (the idempotent fast-path branch) where the call sequence is `ensure_venv → verify_venv`. `ensure_venv` (defined at `scripts/install/venv.sh:300`) is responsible for running `pip install`. If `verify_venv` runs synchronously after `ensure_venv` returns, there is no race — `ensure_venv` returns AFTER pip is done. The actual field-report failure (`✗ Venv version mismatch: have v3.8.2, need v3.9.0` followed by `→ ensure_venv: stamp mismatch — rebuilding`) is `run_pre_install_checks` running BEFORE `ensure_venv` rebuilds, then printing alarming text, then the actual rebuild succeeds. There is no race condition; there is a noisy ordering of pre-check vs rebuild output. "move/await pattern" is the wrong fix. The right fix is to suppress the pre-check noise when `ensure_venv` will rebuild anyway, OR to order: rebuild first, then pre-check.

**Remedy**: Investigate the actual call-graph in `upgrade_version.sh` lines 169-200 before specifying a fix. Phase 4 risk-rating is wrong; the failure mode the plan describes does not match the field report. Either downgrade Phase 4 scope to "improve cosmetic ordering" or expand it to a proper investigation.

---

## RISKY findings

- **R1**. Phase 5 test portability — `importlib.reload` with `sys.modules['tomllib'] = None` does not work as the plan implies. Need either subprocess-spawn Python 3.10 OR `unittest.mock.patch.dict(sys.modules, {'tomllib': None}) + importlib.reload`.
- **R2**. Layer 1 `find_compatible_python` already does PATH probing — needs a clear bootstrap-vs-post-bootstrap classification table.
- **R3**. Decision 3 (no silent stderr) interacts with `set -u`; resolvers sourced under `set -euo pipefail` may cascade. Test under that shell shape.
- **R4**. Phase 7 patch-release scope unjustified given Phase 5 paths.py changes — needs explicit non-breaking justification.
- **R5**. Phase 6 Task 6.4 reproduction mechanism under-specified (Docker python:3.9-slim or fake-python3 shim — pick one).
- **R6**. `HOOKS_DAEMON_PYTHON` post-bootstrap semantics unspecified.
- **R7**. Hostname-slug interaction unaddressed — multi-fingerprint case ambiguous.
- **R8**. CI Python 3.13 only — choose ImportError fixture approach (option a) and lock it.
- **R9**. `set -euo pipefail` source-time behaviour — graceful fail or hard exit; update callers in lockstep.
- **R10**. Dogfooding: this repo IS a self-install. Document recovery path when developer's venv breaks.

---

## CLEAR observations

- Decision 1 framing (existing venv = SSOT, no probing post-bootstrap) is architecturally correct.
- Decision 3 (no silent stderr suppression) is correct in principle.
- The 5-step precedence in `paths.py::resolve_existing_venv_python_with_diagnostics` is well-designed; bug is upstream of it (the wrapper).
- Phase 1 (Opus review gate) before code is the right ordering.
- Risks table correctly identifies legacy-fallback removal compatibility risk.
- Plan correctly decouples idle-window daemon-death issue from v3.9.1 patch scope.

---

## Suggested amendments

- **A1**: Phase 3 — add Tasks 3.5/3.6/3.7: rewrite `venv-include.bash::_resolve_venv_dir`, rewrite `venv_resolver.sh::resolve_existing_venv_python`, add bootstrap-vs-post-bootstrap classification table.
- **A2**: Promote Phase 5 from "defense-in-depth" to "primary". Reorder so Phase 5 lands BEFORE Phase 3 implementation. Update Phase 5 risk rating to High/High. Specify exact test mechanism.
- **A3**: Phase 2 — replace Task 2.1 with 2.1a + 2.1b (different error messages). Add Task 2.7 (resolver under `set -euo pipefail`), 2.8 (broken venv symlink), 2.9 (stderr-silent on success).
- **A4**: Reclassify or rewrite Phase 4 — diagnosis is wrong. Either re-scope to "improve pre-check vs rebuild output ordering in upgrade_version.sh:169-247" or split into a separate plan.
- **A5**: Phase 6 — add Task 6.5: deterministic reproduction using Docker python:3.9-slim OR pinned `/tmp/fake-python3` shim.
- **A6**: Add Decision 4: "HOOKS_DAEMON_PYTHON honored ONLY by bootstrap; IGNORED by resolvers post-bootstrap."
- **A7**: Add risks justification: v3.7.0 retired the legacy path, Plan 00100 added eager cleanup, no supported install can still be on it.
- **A8**: Phase 7 — add Task 7.4: acceptance test on Python-3.9 host (or simulated equivalent).
- **A9**: Phase 5 — add Task 5.4: verify `tomllib.TOMLDecodeError` reference at `paths.py:407` is also deferred.
- **A10**: Phase 7 release notes — mandate explicit transparency about v3.9.0 regression and acceptance-test blind spot.

---

## Reviewer mandate

> Do not write code until the amendments above are applied — particularly A1, A2, A4. After amendments, re-run a second review pass before Phase 1 sign-off.
