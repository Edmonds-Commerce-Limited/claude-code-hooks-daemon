# Task 4.2 report: pressure moves to session start, stop and merge; creation is a backstop

Branch: `plan-00594-task-4-2-pressure` (from main). DESIGN section 2.3.

## What changed

- `config/models.py`: `branches.wip.creation_grace` (int >= 0, default 2). `daemon/init_config.py` default config template and `docs/guides/CONFIGURATION.md` document it.
- `core/branch_creation.py`: the cap section in `creation_report` refuses only at `cap + creation_grace` open work groups (and only in `wip.mode: block`). Between `cap` and that it still appears in the report as a warning, so `branch-preflight` exits 0 there and lists it. Other pools (dormant, parked, merged) are untouched.
- `core/branch_stop_guard.py`: two new checks, `StopCheck.DORMANT` ("dormant past the block stage") and `StopCheck.OVER_CAP` ("open pool over cap"), applied only to the stopping main thread's OWN touched open branches (touch records), never to untouched or foreign ones. Fix commands are finish (merge) or `branch-park <name> --reason ...`; no rename, no deletion of another owner's branch. `stop_guard.mode: warn` makes them context only via the existing gate path; `wip.mode: off` / `dormancy.mode: off` switch the matching check off; sub-agent stops and hard-context handoffs skip them. `core/branch_stop_gate.py` needed no change.
- `handlers/session_start/branch_sweep.py`: after the summary, a `BRANCH POOLS` block renders every full pool via `creation_report` / `render_creation_report` (same report as `branch-preflight`).
- `handlers/post_tool_use/cleanup_after_merge.py`: after a merge, when the merged pool is full, the advisory names the exact `branch-sweep --clean` command (taken from the merged section's `fixes[0]`).
- `handlers/pre_tool_use/branch_creation_guard.py`: CLAUDE.md guidance updated.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/049-branch-pressure-moves-to-stop-and-session-start.md`.

## Tests (seen failing first)

- New `tests/unit/core/test_branch_pressure.py` (19 tests): 9 failed before the implementation (grace option missing, cap still denying, no stop checks, no warn context), 19 pass after.
- `TestPoolPressureReport` (session start, 4 tests) and `TestPoolClearCommandAfterMerge` (2 tests) added; 3 failed first, pass after.
- Existing tests that assert the deny AT the cap (about 30 across creation, pools, preflight, guard, CLI preflight, worktree-create, event-budget tests) now set `creation_grace=0`, which is the documented way to keep the old behaviour. No assertion was weakened.

## QA

`run_autofix.sh`, then `llm_qa.py changed --base main`: first run 41/42, the failure being two cap-deny tests (fixed, above) plus 5 "too-broad" unmapped source files, which `changed` fails on by design for widely imported modules (config models, branch_creation, init_config, the guard, branch_sweep). Re-run with `--allow-unmapped`: QA 42/42 PASSED.

## Open items

- Not done: the DESIGN 2.3 "ignored stop report" grace variant (journal note) is not implemented; grace is the fixed option.
- Stop checks use the open-pool record count (not same-tip group dedup), so a stack of same-tip branches counts per link; relates to Task 4.6.
- The "too-broad" unmapped files need either a `changed_tests_map.yaml` rule or `--allow-unmapped` for the coordinator's gate.
