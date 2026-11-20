# Plan 00607: unblock the Dependabot-held packages

**Status**: Complete (2026-11-15)
**Created**: 2026-11-15
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Main has 19 open Dependabot alerts in `uv.lock` (1 high, 15 moderate, 3 low). Plan 00593 bumped everything it could and
left three packages held by upstream pins in two dev-only QA tools. Those pins have not moved since:

| Package           | Alerts | Patched at | Held by                                                         |
| ----------------- | ------ | ---------- | --------------------------------------------------------------- |
| filelock          | 13     | 4.2.1      | `safety` 3.8.1 (latest) requires `filelock<4.0`                 |
| mcp               | 4      | 1.30.0     | `semgrep` 1.185.0 (latest) requires `mcp==1.29.0`               |
| opentelemetry-api | 2      | 1.45.2     | `semgrep` 1.185.0 (latest) requires `opentelemetry-api~=1.37.0` |

Waiting for upstream does not work, and the owner's standing rule is that dependencies are updated as a matter of
course. The fix is to stop these tools from pinning the project's lock:

- `safety` is listed in the `dev` extra, but nothing in the repository runs it: no script, workflow, hook or import.
  Removing it lets `filelock` move to a patched 4.x.
- `semgrep` is a real QA gate (`scripts/qa/run_semgrep_check.sh`, Plan 00231), but it is a standalone CLI that the
  project never imports. Running it from its own isolated tool environment, pinned exactly the way pyright is, takes
  `mcp` and OpenTelemetry out of `uv.lock`.

## Goals

- No open Dependabot alert on main for `filelock`, `mcp` or `opentelemetry-api`.
- The semgrep QA gate still runs, locally and in CI, at a pinned version, and fails closed when semgrep is missing,
  as it does now.
- `uv.lock` resolves with no package held below its patched version by a dev tool.

## Non-Goals

- No change to the semgrep rules or to what the gate checks.
- No replacement vulnerability scanner for `safety`, because nothing ran it. If one is wanted, `pip-audit` is a
  separate decision.

## Tasks

### Phase 1: remove the pins

- [x] ✅ **Task 1.1**: Prove that `safety` is unused (search scripts, workflows, pre-commit, docs that tell people to run
  it), remove it from the `dev` extra, and re-lock with `filelock` at a patched 4.x. Update any doc that lists it.
- [x] ✅ **Task 1.2**: Move semgrep to an isolated, exactly pinned tool environment. The gate runs `uv tool run --from semgrep==<pin>`, with the pin only in `scripts/qa/semgrep-version.txt`. It fails closed and its error names the real
  cause. The rule tests use the shared helper `tests/support/semgrep_tool.py`.
- [x] ✅ **Task 1.3**: Update CI (cache key), `CLAUDE/QA.md` (including a note that the pin does not lock semgrep's
  transitive dependencies) and the tests that assumed semgrep was in the venv.
- [x] ✅ **Task 1.4**: Re-lock everything else that has a newer patched version and record what moved
  (`subagent-reports/261115-python-developer-sonnet.md`). Two regressions from the lock change were fixed forward on
  main:
  - `8d82b3069` declares `anyio` directly. Its pytest plugin runs the async daemon tests, and it had only ever arrived
    through semgrep.
  - `55d78799c` holds `coverage` at 7.13.5. Version 7.17.3 ran the forwarder socket tests about 3x slower under
    coverage (28.4s against 9.5s) and failed two tests on the py3.13 coverage shard.

## Success Criteria

- [x] `uv tree --invert` shows no `safety`, `mcp` or `opentelemetry-api`, and `filelock` is at 4.2.10.
- [x] The semgrep gate passes locally (alone, and with three scans running at once) and in main CI from its isolated
  environment.
- [x] Targeted QA passes on the branch and over the merged range on main (`QA: 43/43 PASSED`). Main CI run
  43766285856 is green, after runs 43759794234 and 43763172628 failed on the two regressions above.
- [x] Open Dependabot alerts on main fell from 19 to 0.
- [x] The pending-release holding area has no release note, and none is needed: the change is dev-only.
  `scripts/install/venv.sh` adds `--extra dev` only for a self-install, never for a client install.

## Follow-ups

- Lift the `coverage` hold once a newer release is measured no slower on
  `tests/integration/test_forwarder_socket_stdin.py` under coverage.
- Plan 00608's session recorded "Failed to find semgrep-core" from the pinned uv semgrep. It did not reproduce
  afterwards, with scans run alone or three at once. If it returns, capture `env`, `uv cache dir` and the stderr.
  Those details are recorded in Plan 00608's journal.
- Cause found and fixed: semgrep 1.185.0's `semgrep-core` does not install under uv on Python 3.10-3.12; the
  interpreter is now pinned to 3.13 in `scripts/qa/semgrep-python.txt` (fix commit: see branch
  `worktree-semgrep-python-pin`, report `subagent-reports/261115-python-developer-sonnet-python-pin.md`).

## Delivery & Milestones

- Implementation `f4f390f1d` and review fixes `3076e216c`, fast-forwarded to main. Follow-up fixes on main:
  `8d82b3069` (anyio) and `55d78799c` (coverage hold).
- Reports: `subagent-reports/261115-python-developer-sonnet.md`.
