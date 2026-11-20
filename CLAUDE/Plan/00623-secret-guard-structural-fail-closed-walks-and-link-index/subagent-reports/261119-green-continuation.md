# Plan 00623: GREEN continuation report

Branch `agent-a13d7c8504105d4c9-aeae03b4`, commits `95c70fe58` and `cb6c25fea` on top of the WIP commit `2ff2bac99`. Pushed, not merged.

## What was checked in the WIP

- The RED file `test_secret_file_guard_bounded_walks.py` differs from `66f2f855f` by formatting only, and all 47 of its tests pass. The edits to `test_secret_file_guard_cwd_fail_closed.py` and `test_secret_file_matching.py` move to the `Bounded` API and keep the same verdicts.
- `utils/bounded_walk.py`, `utils/link_index.py` (memory only, verified by `(st_dev, st_ino, st_ctime_ns)`, link kinds reclassified on every use, and every bound stops the result), `resolution_failure.fail_closed_finding` (secret, quarantine and flaggable guards, plus payload capture), depth raises (N664), the `lstat` placement (N663) and `refuse_process_view` (N668): all read and kept.

## Holes found and fixed (each pinned by a test, RED then GREEN)

1. `place_outside_project` placed `cd "~"`, `cd '$HOME'` and `cd \$TMPDIR`, where bash moves to a literal directory instead. It now refuses a quoted or escaped spelling.
2. It also placed a move that follows `source`, `.`, `eval`, `declare`, `read`, `printf -v` or a similar builtin, any of which can set the variable without spelling its name. Placement is now refused after such a builtin in command position.
3. `cd -P "$TMPDIR/x/.."`, with `x` a link into the project, was placed outside because only the normalised path was checked. The spelled path is now resolved physically too, and the place is checked against both forms of the project root.
4. `toplevel_relocated` matched the text "worktree" anywhere in the config. This repository's own config contains it as a branch route value, so the idiom was always demoted here. It now matches only a `worktree` key, and an include `path` that names a directory is skipped.
5. `_could_read` treated a `-c` body that was no shorter than its command as harmless. It now treats that body as a possible reader.
6. The error_hiding check flagged a `ValueError -> None` branch in `_realpath_if_resolvable`. A predicate now does that check before the stat.
7. `cd "$(mktemp -d)" && ls` was added to the usability list. It is allowed once the index is built.

## Tests and QA

- 1,376 tests pass across `test_secret_file_matching`, bounded walks, link index (handler and util), cwd fail-closed, bounded_walk and resolution_failure.
- An earlier run covered the 85 test files that touch the guards and walkers, on the WIP tree: 6,227 pass and 2 fail.
  - The `polluter/victim` child-pytest pair (`test_project_containment` with `test_absolute_path`) exits 3. These tests have nothing to do with this change.
  - `test_safety_handlers_hostile_input_performance.py::TestSweepVerdictIsHostIndependent` expects an expired deadline on a glob command to ALLOW with an advisory, but the guard denies it. This is pre-existing: at `66f2f855f`, before the WIP, 3 tests in that class fail. The test and the branch's deny-on-glob rule conflict, and the coordinator should decide which is right.
- Targeted QA (format, lint, type_check, pyright, error_hiding, fail_open_inventory, magic_values) is clean after `cb6c25fea`. pyright ran on the tree before that commit.

## Left

- Task 3.2: the DENY-to-ALLOW comparison against main. It must run twice, with the link index cold (`link_scan_for` returning None) and built.
- The independent adversarial review.
- PLAN.md task boxes and status are not updated. The release note `004-...` from the WIP has not been reviewed: its file name matches a protected glob, so this agent could not read it.
- Residuals are listed in ledger N669, including an alias or function named `cd` defined in an earlier call, and `bash -ec` bodies, which neither walk enters.
