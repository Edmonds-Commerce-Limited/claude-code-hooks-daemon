# Plan 00431: socket path preflight needs no venv

**Status**: Complete
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Thread

## Overview

`scripts/setup_worktree.sh` refuses to create a worktree whose prospective
daemon socket path would exceed the AF_UNIX cap. The check exists because going
over the cap is SILENT: the daemon still starts, relocates its runtime files to
`/tmp`, and the acceptance gates then report "no live socket found under
`untracked/`" with a restart instruction that cannot fix it.

The guard resolves a venv Python in order to call the daemon's own measurement
helpers, and deliberately fails OPEN when it cannot — a broken checker must not
block worktree creation. That fallback is right, and the route into it is not:
a worktree created from INSIDE another worktree has no venv yet, so the
measurement cannot run and the guard stands down. That is precisely where paths
get long enough to matter. The guard is inert in the case that motivated it and
healthy everywhere else, so it reports `✓ Socket path fits` on every short path
anyone tests it against. Recorded as Plan 00422 niggle N8, with the cost
measured: a sub-agent spent a long run inside a 130-byte-path worktree and
reported four red QA categories that were environmental.

The defect is that arithmetic which is two path joins and a length comparison
needs a virtualenv at all. `daemon/paths.py` is stdlib-only, so loading that
FILE under the system `python3` runs the real helpers against the real constant
with no venv, no editable install and no second copy of the limit.

## Goals

- The pre-flight measures the socket path in a checkout with no venv, and
  REFUSES an over-cap path there.
- The limit keeps coming from `_UNIX_SOCKET_PATH_LIMIT`, never a bash copy.
- Failing open survives for the cases that still deserve it (no `python3`, no
  `paths.py`), and says which one happened.
- A test that fails against the current script, so the fix is demonstrated
  rather than asserted.

## Non-Goals

- Changing what the cap IS, or how the daemon behaves when a path exceeds it.
- The `self_install` detection in the same function, which is a separate
  question about client layouts.
- Any change to venv resolution itself — this plan removes a dependency on it,
  it does not alter it.

## Tasks

### Phase 1: RED

- [x] ✅ **Task 1.1**: A test that drives the measurement the way a venv-less
  checkout does, and fails on the current script.
  `tests/integration/test_worktree_socket_path_preflight.py` — 3 behaviour
  tests failed against the old script, 3 controls passed.

### Phase 2: GREEN

- [x] ✅ **Task 2.1**: Measure by loading `daemon/paths.py` by file location
  under the system `python3`; keep a fail-open branch for a genuinely
  unusable environment, with a reason in the message.
- [x] ✅ **Task 2.2**: Confirm shellcheck and the deployed-asset lint gate stay
  green on the changed script. 66 scripts, 0 issues; asset lint 9 passed.

### Phase 3: Close

- [x] ✅ **Task 3.1**: Release note in the pending-release holding area.
- [x] ✅ **Task 3.2**: Mark N8 remedied in the Plan 00422 ledger, naming this
  plan.

## Success Criteria

- [x] The over-cap refusal fires with no venv present — and the live script
  refuses a 165-byte path, creating nothing.
- [x] `_UNIX_SOCKET_PATH_LIMIT` appears exactly once in the repository as a
  value.
- [x] `plan_qa`, `docs_qa`, shellcheck and
  `tests/integration/test_client_owned_asset_lint.py` all pass.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/09-worktree-socket-path-preflight-needs-no-venv.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00431-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from Plan 00422 niggle N8.
- Delivered at `18a9b01b` + the archiving commit.
