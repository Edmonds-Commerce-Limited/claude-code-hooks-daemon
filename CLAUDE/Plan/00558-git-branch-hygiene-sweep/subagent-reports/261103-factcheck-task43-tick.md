# Fact-check: Task 4.3 tick (PLAN.md line 94)

Diff: `untracked/plan-fact-check/00558-git-branch-hygiene-sweep.diff`. Only the added line (PLAN.md:94, Task 4.3 text and tick) was checked. Context lines were not.
Searches excluded `tests/fixtures/cyber-flag`.

## Claims

| #   | Quoted claim                                                               | Verdict              | Evidence                                                                                                                                                                                          |
| --- | -------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | "Add the dormancy limit"                                                   | VERIFIED             | `src/claude_code_hooks_daemon/core/branch_creation.py:289-316` (`_dormant_work` reads block and noisy stages)                                                                                     |
| 2   | "the `standard` and `strict` presets"                                      | VERIFIED             | `src/claude_code_hooks_daemon/config/models.py:2254-2256`: `"standard": (7, 14, 30)`, `"strict": (3, 3, 7)`; `:2293` `preset: Literal["standard", "strict"]`                                      |
| 3   | "the parked marker (Goal 5)"                                               | VERIFIED             | `src/claude_code_hooks_daemon/core/branch_park.py:43-46` writes `Parked-Reason:` and `Parked-By:` trailers                                                                                        |
| 4   | "`R-BRANCH-DORMANT` in the creation verdict"                               | VERIFIED             | `src/claude_code_hooks_daemon/constants/rule_ids.py:75`; `handlers/pre_tool_use/branch_creation_guard.py:78`; `core/branch_creation.py:324`                                                       |
| 5   | "`hooks-daemon branch-park [--clear]`"                                     | VERIFIED             | `src/claude_code_hooks_daemon/daemon/cli.py:6524` (`cmd_branch_park`); `:13036-13048` registers `branch-park` with `--reason` and `--clear` (`:13044`)                                            |
| 6   | "the optimiser's non-scoring strict suggestion"                            | VERIFIED             | `src/claude_code_hooks_daemon/config_optimisation/checklist.py:251-269` (`optional_suggestions`, documented as never counted in the score)                                                        |
| 7   | "The creation guard reads the stage from the SessionStart labels snapshot" | VERIFIED             | `core/branch_creation.py:289-316` (stage taken from `labels[name]["stage"]`); snapshot written by `handlers/session_start/branch_sweep.py:104` via `write_labels` (`core/branch_creation.py:126`) |
| 8   | "so a branch's stage is as of the last session start"                      | VERIFIED             | `core/branch_creation.py:294-295` docstring: no age computed at creation time; stages come from the snapshot written at session start                                                             |
| 9   | "`branch-park` clears its label at once"                                   | VERIFIED (park only) | `daemon/cli.py:6551-6552` calls `clear_label_stage` when `not args.clear`; `core/branch_creation.py:150-163` sets `group: parked, stage: None`.                                                   |

Counts: 9 claims, 9 verified, 0 refuted, 0 unverifiable.

## REFUTED claims

None.

## Notes (not claims in the diff)

- Claim 9 is true only for a park. `branch-park --clear` does not touch the labels snapshot (`cli.py:6551`), so after an unpark the snapshot keeps its `parked` group until the next SessionStart. Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/031-branch-dormancy-and-park.md` line 10 says `branch-park` updates the snapshot, which matches the park path only.
- `clear_label_stage` returns silently when the branch is not in the snapshot, so a park of a branch the snapshot never saw leaves no label. Not claimed in the plan.
