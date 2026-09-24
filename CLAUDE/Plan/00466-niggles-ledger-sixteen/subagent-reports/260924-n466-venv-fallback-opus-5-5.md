# Plan 00466 N1 delivery report — venv fallback runnability probe

**Branch/worktree**: `worktree-n466-venv-fallback` (from main at `fd8c7dc9`)
**HEAD after delivery**: `7115db98c3da35f02a233cd8b2a8ef0d9b204d40`

## The defect

`resolve_venv_python`'s fallback accepted an `untracked/venv-*` candidate
interpreter on its executable bit alone (`[ -x ]` in bash,
`os.access(X_OK)` in Python), never proving the candidate could actually
run. A venv built inside a container can be present and `+x` and still
fail at exec time on the host — wrong architecture/libc, or a symlink into
a container-only path (first observed in issue #55, recorded as a Plan
00457 JOURNAL finding). The fallback reported such a candidate "resolved",
so `bin/hooks-daemon` never reached its venv-free path
(`_run_venv_free_verb`, the `repair`/`signal` arms from Plans 00456/00457)
and crashed on a raw exec error instead of the clean venv-missing message.

## Every implementation site found

- **Bash canonical library**: `scripts/lib/resolve_venv.sh::_rv_pick_python`
  — the two glob loops over `untracked/venv-*/bin/python` and
  `.../bin/python3`. This is the ONLY bash site permitted to glob
  `untracked/venv-*` directly (`scripts/qa/check_canonical_callers.sh`
  denies every other shell script that does, and confirmed zero violations
  in the targeted QA run below) — every other bash caller
  (`_resolve-venv.sh`, `venv_resolver.sh`, `venv-include.bash`, `init.sh`,
  `bin/hooks-daemon`) delegates to it, so fixing this one site fixes all
  of them.
- **Python SSOT**:
  `resolve_existing_venv_python_with_diagnostics` in
  `src/claude_code_hooks_daemon/daemon/paths.py` — step 2 (metadata
  `python_path`), and steps 3/4/5 (fingerprint-keyed, scan-fallback,
  legacy) via a shared `_pick_interpreter` closure. This is the function
  `paths.py resolve-venv` (the CLI bash delegates to) calls.
- **Deliberately left un-probed, documented why**:
  `resolve_existing_venv_python` (the simpler, no-diagnostics function).
  It runs fresh on every user turn inside `daemon_upgrade_detector`
  (per-turn hot path), and neither of its current callers executes the
  returned interpreter — `daemon_upgrade_detector` only reads
  `.daemon-metadata.json` next to it, and
  `client_validator.py::validate_daemon_can_start` (the other caller, which
  DOES execute the result) already ran its own
  `subprocess.run(..., timeout=Timeout.VALIDATION_CHECK)` probe before
  doing so. Its docstring now states this explicitly so a future reader
  does not "fix" it into a hot-path regression.

## RED evidence (TDD)

Both new/extended test files were run against the pre-fix code first and
confirmed failing for the right reason before any implementation change:

- `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py::TestRunnabilityProbe`
  (7 new tests): 7 failed / 2 passed (the 2 passing cases — a dangling
  symlink, and the working-fingerprint-keyed regression check — were
  already correct by construction and not expected to fail).
- `tests/integration/test_resolve_venv_runnability_probe.py` (new file,
  7 tests exercising `_rv_pick_python`/`resolve_venv_python` directly in
  bash): 5 failed / 2 passed (same shape — the dangling-symlink case was
  already caught by bash's own `[ -x ]` semantics on a broken symlink).

Coverage in both: a fake executable that exits non-zero, a dangling
symlink, a hanging candidate (bound respected), fall-through to a good
second candidate after a bad first, all-candidates-bad reaching the
venv-free path / `None`, and the slug-exact (fingerprint-keyed) venv
unaffected when it genuinely works.

After the fix, both files are fully green, and the wider existing
venv-resolution regression surface (239 tests: parity matrix, hot-path
latency/cache-ratio gate, pipefail cascade, bin-wrapper + anchoring, skill
scripts, install resolver, client validator, daemon_upgrade_detector,
multi-host NFS fail-fast) also passes unchanged.

## Probe cost measured

An early draft polled `kill -0 "$pid"` in a `sleep 1` loop. Measured
against this worktree's own real venv `bin/python`: **~1005ms per
candidate**, regardless of how fast the candidate actually exits — the
loop's first check almost always lands before a subprocess has exited
(fork+exec takes a few ms, not zero), so it always sleeps a full second
before the second check.

Replaced with a watchdog subprocess (`( sleep N; kill -KILL "$pid" ) &`
paired with a blocking `wait "$pid"`, no polling at all): **~15-40ms per
candidate**, measured the same way (5 samples, real interpreter).

Both designs are reached only on a resolver-cache MISS — the bash
hot-path cache in `_rv_resolve_python_impl` (`untracked/.python-cmd-cache`,
keyed on `untracked/`'s mtime) is checked and can return BEFORE
`_rv_pick_python` is ever called — so neither adds cost to the
steady-state per-hook path.
`tests/integration/test_venv_resolver_hot_path_latency.py`'s existing
cache-speedup-ratio gate (â‰¥3x) still passes unchanged, confirming the cache
path is untouched.

## `set -e` safety (verified empirically, not just reasoned about)

`_rv_candidate_runs` is always invoked as the condition of an `if` inside
`_rv_pick_python` (`if _rv_candidate_runs "$candidate"; then ...`). Bash
suspends `errexit` for the ENTIRE body of a function called in that
position, not just its own top-level return — verified directly:

- A bare top-level call to `_rv_candidate_runs` under `set -euo pipefail`
  DOES abort (as expected — it is not in an exempt position there).
- The SAME call wrapped as an `if` condition does not abort, and neither
  does the full nested production chain
  `resolve_venv_python` → `( set -euo pipefail; ... )` →
  `python_cmd="$(_rv_pick_python ...)"` → `if _rv_candidate_runs ...; then`.

A candidate's stdout/stderr are captured to a private `mktemp` file, not
`/dev/null` and not the caller's inherited fds — this script has no job
control (`set -m` off), so `kill -KILL "$pid"` on timeout reaches only the
immediate candidate process, and a descendant it spawned survives as an
orphan. If that orphan inherited the CALLER's own stdout/stderr, it could
hold that fd open past the probe's bound, and a caller reading our output
via a pipe (command substitution, or `subprocess.run(capture_output=True)`
in the integration test harness) would block until the orphan eventually
exited on its own — reproduced this exact hang with an earlier
`/dev/null`-for-stdout-only draft (a fake venv script backgrounding
`sleep 100`, run through a bash-test-fixture whose failing test surfaced a
30s `subprocess.TimeoutExpired` instead of the intended near-instant
timeout).

## Sibling audit

- `scripts/qa/check_canonical_callers.sh` is the existing static backstop
  for the bash side: it denies any shell script (outside
  `scripts/lib/resolve_venv.sh` itself and one exempted self-bootstrap
  upgrade-template file) that iterates `untracked/venv-*` directly. Ran it
  as part of targeted QA below with 0 violations, confirming `_rv_pick_python`
  really is the only bash acceptance site.
- Python: grepped every caller of `resolve_existing_venv_python` (no
  diagnostics) and `resolve_existing_venv_python_with_diagnostics` across
  `src/`. Findings folded into the "every implementation site" section
  above; no other Python site trusts a venv interpreter's executable bit
  without either delegating to the now-fixed diagnostics resolver or
  already probing it itself (`client_validator.py`).

## Targeted QA (Plan 00463 policy — no full-suite run)

- Touched tests: `tests/unit/daemon/test_paths_resolve_venv_diagnostics.py`,
  `tests/integration/test_resolve_venv_runnability_probe.py` — full pass.
- Related regression surface (not required by policy, run anyway given the
  blast radius of a canonical resolver change): 239 tests across parity
  matrix, hot-path latency, pipefail cascade, bin-wrapper (+anchoring),
  skill-scripts venv resolution, install venv resolver, worktree socket
  preflight, `resolve_existing_venv_python` unit tests, `paths.py resolve-venv` CLI integration, `client_validator`,
  `daemon_upgrade_detector`, multi-host NFS fail-fast — all pass.
- `./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding shell_check docs_qa plan_qa` — **9/9 PASSED** (0 findings
  in every check, including `shell_check` over the modified
  `resolve_venv.sh` and `error_hiding` over both the bash and Python
  changes).
- `llm_qa.py all` / `run_all.sh` were NOT run, per Plan 00463's sub-agent
  QA policy.

## Worktree daemon

Restarted (`./bin/hooks-daemon restart`) and verified running before
committing.

## Commits

Single commit, `7115db98c3da35f02a233cd8b2a8ef0d9b204d40`:
`scripts/lib/resolve_venv.sh`, `src/claude_code_hooks_daemon/daemon/paths.py`,
both test files, the NIGGLES.md/PLAN.md updates for N1, the journal entry,
and the release-notes callout
(`CLAUDE/UPGRADES/UNRELEASED/release-notes/13-a-venv-that-cannot-run-no-longer-reports-itself-resolved.md`).
