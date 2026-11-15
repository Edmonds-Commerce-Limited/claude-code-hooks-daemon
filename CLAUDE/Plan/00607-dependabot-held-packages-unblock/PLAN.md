# Plan 00607: unblock the Dependabot-held packages

**Status**: In Progress
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

- [ ] ⬜ **Task 1.1**: Prove that `safety` is unused (search scripts, workflows, pre-commit, docs that tell people to run
  it), remove it from the `dev` extra, and re-lock with `filelock` at a patched 4.x. Update any doc that lists it.
- [ ] ⬜ **Task 1.2**: Move semgrep to an isolated, exactly pinned tool environment (for example `uv tool run --from semgrep==<ver>` or a dedicated venv that `run_semgrep_check.sh` resolves). Remove it from the `dev` extra and re-lock
  so `mcp` and OpenTelemetry leave `uv.lock`. Keep the gate's fail-closed behaviour, and test the resolution path.
- [ ] ⬜ **Task 1.3**: Update CI, pre-commit, `CONTRIBUTING.md` / QA docs and any install script that assumes semgrep is in
  the project venv.
- [ ] ⬜ **Task 1.4**: Re-lock everything else that has a newer patched version (`uv lock --upgrade`), run the full test
  tier that the dependency change touches, and record what moved.

## Success Criteria

- [ ] `uv tree --invert` shows no `safety` and no `semgrep`, `mcp` or `opentelemetry-api` from the dev extra, and
  `filelock` is at 4.2.1 or later.
- [ ] The semgrep gate passes locally and in main CI from its isolated environment.
- [ ] Targeted QA passes on the branch and over the merged range on main, and main CI is green.
- [ ] Open Dependabot alerts on main fall from 19 to 0, or every remaining one is recorded with the constraint that
  holds it.
- [ ] The pending-release holding area: no release note, because the change is dev-only. The client installer never
  installs the `dev` extra (`scripts/install/venv.sh`), so nothing ships to clients. Confirm this before closing.

## Delivery & Milestones

- Pending.
