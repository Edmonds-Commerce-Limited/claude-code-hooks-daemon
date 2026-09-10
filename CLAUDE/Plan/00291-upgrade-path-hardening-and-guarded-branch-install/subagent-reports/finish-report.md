# Plan 00291 finish-report — worktree-plan-00291

**Commit**: `7f0e7ae5` (pushed to `origin/worktree-plan-00291`)

## What was reviewed

Read the full staged diff (PLAN.md ticks, journal day-file, release-notes
callout 15) and the whole `PLAN.md`. Every task except Task 4.2 was already
ticked with a real, verifiable commit cited (`af8dc453`, `4b77b327`,
`03eef02f`, all present in `git log`). Task 4.2 ("Full QA green; daemon
restart verified; UPGRADES manifests updated for any config surface added")
was the only remaining item.

## Work done

- Restarted the worktree's hooks daemon (it was NOT RUNNING at session
  start); `bin/hooks-daemon status` now reports RUNNING (PID 7110).
- Ran `./scripts/qa/llm_qa.py all`: **22/26 PASSED** on the first pass, with
  four real findings, all traced to this plan's own earlier commits (not
  pre-existing repo state):
  1. **magic_values** — `tests/integration/test_init_sh_discovery_pid_path.py`
     used a bare `timeout=60`; changed to `Timeout.REQUEST_LONG`.
  2. **error_hiding** — three `scripts/qa/error_hiding_exclusions.json`
     entries for `scripts/upgrade.sh` / `scripts/upgrade_version.sh` had
     drifted off their target lines (438→531, 450→511, 812→873) because this
     plan's own edits added code above them; realigned in place (same code,
     same rationale). The new `install/install_stamp.py::read_install_stamp`
     had no exclusion entry for its documented return-None-on-error
     contract; added one, matching the shape of the existing
     `daemon/metadata.py::read_daemon_metadata` entry.
  3. **capture_corruption** — `print_branch_install_banner` in
     `scripts/install/branch_install.sh` wrote its warning banner to stdout
     instead of stderr, the documented v3.10.0 SEV-1 log-helper-stdout
     pattern. Fixed (all 11 lines routed to `>&2`); updated the two tests
     that asserted the banner text against `stdout`
     (`tests/integration/test_branch_install_gate.py`,
     `tests/acceptance/test_guarded_branch_install.py`) to assert `stderr`
     instead, and confirmed none of the three real call sites in
     `upgrade_version.sh` capture the function's output via `$(...)`.
  4. **tests** — the three failing tests were exactly the self-scan tests
     mirroring findings 2 and 3 above
     (`test_audit_capture_corruption::TestRealRepoIsClean`,
     `test_audit_error_hiding::TestRealRepoSelfScan`,
     `test_audit_error_hiding::TestStaleExclusionsAreReported`).
- Re-ran the full suite after fixes: **`llm_qa.py all` is 26/26 PASSED**
  (21655 passed, 0 failed, 21 skipped, coverage 95.4%).
- Ticked Task 4.2 and every substantive Success Criterion in `PLAN.md`, and
  added the holding-area criterion required by the project-level
  `plan-done-requires-holding-area` handler, citing release-notes callouts
  14 and 15 (both already staged under
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`).

## A conflict found and how it was resolved

Flipping `**Status**` to `Complete` (per the instruction "a fully completed
plan can be closed without human approval") while leaving
`CLAUDE/Plan/README.md` untouched (per the instruction "the coordinator does
the archive on main") turned out to be **structurally incompatible** with
this repo's own enforced plan-QA gates:

- `terminal-state-atomic` and `location-status-coherence` **BLOCK** a staged
  terminal-status flip whose plan folder has not also moved into
  `Completed/` (with the README row updated) in the **same commit** —
  `CLAUDE/Plan/CLAUDE.md` documents this as one atomic unit, not two
  independently-committable steps.
- Reverting the header to `In Progress` with every checkbox ticked is
  equally blocked by `header-body-coherence` (header contradicts a
  fully-ticked body).

There is no valid intermediate state that satisfies both instructions
literally. Resolution: the header stays `In Progress`; every substantive
Success Criterion is ticked and true; one new, deliberately **unticked**
Success Criterion names the remaining atomic step (folder move + README +
status flip to `Complete`) as the coordinating session's job on `main`. This
is the only state that is both factually honest and passes every
staged/edit-time plan-QA gate — verified with `plan-qa --check-staged`
(0 findings) and `plan-qa --lint PLAN.md` (0 findings) before committing.

**Action needed from the coordinator on `main`**: when merging this branch,
perform the atomic terminal-status flip yourself — `git mv` the plan folder
to `Completed/`, update the `CLAUDE/Plan/README.md` row and statistics, and
flip `**Status**` to `Complete`, all in one commit, per the Plan Completion
Checklist.

## QA result

`llm_qa.py all`: **26/26 PASSED** (22/26 → fixed 4 → 26/26). No handlers
were disabled or suppressed to reach this result; every finding was a real
defect this plan's own commits introduced, fixed properly.

## Outstanding / unresolved

Nothing left in this worktree except the coordinator-owned atomic archive
step described above (deliberately deferred, tracked as the one unticked
Success Criterion). No other work was left incomplete.
