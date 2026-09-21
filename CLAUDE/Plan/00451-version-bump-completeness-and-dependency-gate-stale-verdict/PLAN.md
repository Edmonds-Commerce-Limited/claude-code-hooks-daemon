# Plan 00451: version bump completeness and dependency gate stale verdict

**Status**: Not Started
**Created**: 2026-09-21
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Two defects, one root

Both were found during the v3.66.0 release, and both share a shape: a release
step whose completeness is discovered reactively, by a later gate going red,
rather than asserted up front.

### Defect A — the version-bump list is incomplete

Six tracked files carry the release version:

| File                                      | Found by                                |
| ----------------------------------------- | --------------------------------------- |
| `pyproject.toml`                          | the documented procedure                |
| `src/claude_code_hooks_daemon/version.py` | the documented procedure                |
| `README.md`                               | the documented procedure                |
| `.claude/HOOKS-DAEMON.md`                 | the `docs_qa` gate, after the fact      |
| `.claude/ccy/claude-supervise.py`         | a test, after the fact                  |
| `uv.lock`                                 | the `dependencies` gate, after the fact |

Three of six were caught only because a gate went red. The
`claude-supervise.py` case is a repeat: that test's own docstring records the
identical miss at 3.41.0 vs 3.42.0, so the reactive catch is load-bearing and
the procedure has been incomplete for at least twenty-four releases.

The cost is a restarted FAIL-FAST cycle per miss — for v3.66.0 that meant a
full ~15-minute QA re-run at 33/35, then another.

### Defect B — the dependencies gate leaves a stale verdict on disk

`scripts/qa/run_dependency_check.sh` runs `uv lock --check` before deptry under
`set -euo pipefail`. A stale lockfile therefore exits the script BEFORE
`dependencies.json` is rewritten, so the gate exits non-zero while the JSON on
disk still says `passed: true` from the previous run.

The reported artefact then actively misdirects: reading `dependencies.json`
says the gate is clean, and the real cause (a lockfile one `uv lock` away from
correct) is invisible. During v3.66.0 this cost a wrong-turn investigation into
three unrelated deptry `DEP001` findings from a whole-repo run, which were a
red herring — the gate scopes deptry to `src/`.

Defect B is what makes Defect A expensive: the gate that should have named the
stale `uv.lock` instead pointed somewhere else.

## Goals

- A single authoritative list of version-carrying files, with a check that
  fails when a tracked file declares a version the release is not bumping.
- `dependencies.json` never left holding a verdict from a previous run when the
  gate fails — a failed gate reports the failure it actually hit.

## Non-Goals

- Automating the version bump itself. Asserting completeness is enough; a
  human or the release agent still performs the edit.
- Changing deptry's configuration or its `src/` scope.
- Re-auditing the other QA gates for the same stale-artefact shape. If the fix
  suggests that class is wider, record it as a niggle rather than expanding
  this plan.

## Tasks

### Phase 1: Version-bump completeness

- [ ] ⬜ **Task 1.1**: Enumerate every tracked file declaring the current
  version, excluding historical trees (`CHANGELOG.md`, `RELEASES/`,
  `CLAUDE/UPGRADES/`, `CLAUDE/Plan/`), and confirm the table above is
  complete rather than assuming it.
- [ ] ⬜ **Task 1.2**: RED — a test that fails when a tracked file declares a
  version string not matching `version.py`. Verify it fails by pinning one
  file at an old version, so it is not passing vacuously.
- [ ] ⬜ **Task 1.3**: GREEN — implement, and update the release procedure in
  `CLAUDE/development/RELEASING.md` to name the check rather than restate
  the file list, so the list has one home.

### Phase 2: The stale dependencies verdict

- [ ] ⬜ **Task 2.1**: RED — a test that runs the dependency check against a
  deliberately stale lockfile and asserts `dependencies.json` reports the
  failure. It must fail against the current script.
- [ ] ⬜ **Task 2.2**: GREEN — ensure the script writes a failing
  `dependencies.json` naming the `uv lock --check` failure before exiting.
  Consider writing a `pending`/invalidated verdict at the START of the run
  so an aborted run can never leave a clean one behind — a crash between
  steps has the same consequence and the guard should cover it.

## Success Criteria

- [ ] Adding a new version-carrying file without registering it fails the
  completeness check.
- [ ] A stale `uv.lock` produces a `dependencies.json` that names the lockfile
  as the cause, and the gate's reported reason matches its exit code.
- [ ] Neither check can pass vacuously — each has a test proving it fails when
  the defect is present.
- [ ] Full QA green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00451-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found during the v3.66.0 release, filed after the tag.
