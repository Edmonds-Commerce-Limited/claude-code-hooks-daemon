# Plan 00619 implementation report (Tasks 1.1 to 1.3, 1.2a, 1.5, 2.1)

Branch: `agent-aa5b3e19f48a28f06-f164c7f6` (pushed). Not merged. Task 1.4 (independent review, CI, merge) is left unticked for the coordinator.

## Commits

1. `a58cd5b58` Task 1.1: failing table test, committed red (collection failed on the missing module).
2. `a58bca572` Tasks 1.2 and 1.2a: `BranchLadderConfig` (60/80/90, ordered), `core/branch_ladder.py`.
3. `48c311873` Tasks 1.3, 1.5, 2.1: handlers, session start and stop surfaces, docs, manifest, release note.

## What was built

- `core/branch_ladder.py`: `ladder_level(count, base, thresholds)` (integer ceiling, block at `count >= base`), `pool_base` (open = `wip.cap + wip.creation_grace`, parked and merged = their cap), `LadderThrottle` (warn and strong once per session per pool and level; very strong and block never limited), `pool_pressures`, `pressure_lines`, `ladder_notice`, a 10 second `PressureCache`.
- Config: `ladder: {warn, strong, very_strong}` on `branches.wip`, `branches.parked`, `branches.merged`.
- `branch_pool_pressure_advisor` (PreToolUse, priority 20) and `branch_pool_pressure_prompt` (UserPromptSubmit, priority 44): both non-terminal, context only, project root, silent on git failure.
- Session start (`branch_sweep`) and the main-thread stop (`decide_stop`) append the same ladder as context. Stop hold condition and `refuses` in the creation report untouched.
- From strong up the named branch is the oldest unfinished one (not merged or patch-equivalent) and the text says merge, or the no-value verdict route of Plan 00620 once it ships. No `--allow-unproven`, no archive refs.

## Task decisions

- 1.5: no `--allow-unproven` mention remains in `docs/guides/HANDLER_REFERENCE.md` on this tree (searched); nothing to correct. Added entries for the two new handlers there.
- 2.1: stop guard stays on the project root (it judges branches this session touched). Test `test_judges_the_project_root_whatever_directory_the_payload_names` pins it; docstring in `handlers/utils/branch_stop_guard_base.py` records why.
- Journal entry written with `mkplan.bash --journal 619 decision`.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/001-branch-pool-warning-ladder.md`; config manifest `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.76.0.yaml` (next version number is a guess, adjust at release).
- PLAN.md status set In Progress (README row synced).

## Verification

- Targeted pytest green: ladder (37), both new handlers, session start sweep, stop gate, stop handlers, user prompt handlers, guidance and evasion classification tests, constants.
- `llm_qa.py changed` first run: only format, pyright (test annotation) and generated-doc drift failed, plus changed_tests unmapped (`[too-broad]`, needs `--allow-unmapped`). All fixed (autofix, annotation, `generate-docs`). The re-run waited on the host-wide QA lock held by another run; see the final reply line for whether it completed.

## For the coordinator

- Run the full QA gate and the independent review (Task 1.4).
- Loosening and tightening review: no guard denies or allows anything new; the only new code paths add context.
- Open choice: very strong at the block level shows "AT THE LIMIT" lines in addition to the deny report at session start (short duplicate, deliberate).
