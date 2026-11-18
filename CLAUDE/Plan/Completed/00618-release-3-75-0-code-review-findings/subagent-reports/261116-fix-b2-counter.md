# Plan 00618 Task 1.2 final rework: B-2 residual R, the separate capped counter

Branch: `worktree-plan-00618-b1-b2`. It is pushed, not merged. This follows `261116-fix-b2-rework.md` and answers the re-review `untracked/scratch/review-618-b2-rework.md`, which had one blocker, residual R, with fix A recommended.

## Commits

| Commit      | What                                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------------------- |
| `1249b2ae0` | Red tests. 11 failed on `f97374cdb`, each on an assertion, not an error.                                 |
| `938169c8f` | Fix A in `core/branch_stop_gate.py`.                                                                     |
| `d07606150` | Release note 089, the `HANDLER_REFERENCE.md` stop-guard line, and this report.                           |
| (next)      | `handlers/stop/branch_stop_guard.py`: docstring, `get_claude_md` and safety note name the second budget. |

## Fix (`core/branch_stop_gate.py`)

- **One read.** `_owned_branches` is now `_hand_over`, which returns `HandOver(handed, newly_judged)`. Both come from ONE `running_holds` call and ONE `linked_worktree_records` call.
  - A branch is newly judged when origin/main's predicate holds it, the stopping thread touched it (`own`), and no queue record or lock holds it. In practice that means it sits under `.claude/worktrees/` only. `newly_judged` maps such a branch to its worktree path.
  - When the worktrees cannot be listed, `handed` is `holds.branches` and nothing is newly judged. That is origin/main's behaviour.
- **Two counters.** If every blocking finding is on a newly judged branch, the stop counts on `blocks_harness`. Otherwise it counts on `blocks`. Each counter is capped at `MAX_STOP_BLOCKS` (3), so a stopping identity gets at most 3+3 refusals and cannot wedge. The "Block n of 3" text is true for each counter. A sub-agent stop has nothing newly judged, so it is unchanged.
- **Why the main counter matches origin/main.** The handed set here equals origin/main's minus `newly_judged`. So findings on any branch outside `newly_judged` are identical on both trees.
  - A stop counts on `blocks` exactly when it has such a finding, which is exactly when origin/main refuses and counts.
  - So `blocks` equals origin/main's counter after every stop. Whenever origin/main refuses, this tree refuses too.
- **Deny text.** A finding on a newly judged branch has its commands replaced. Instead of `git -C <wt> add -A` / `commit` / `push` / `worktree remove`, it says:
  - `git worktree lock <wt>`;
  - `hooks-daemon work-queue add <agent-name> --worktree <wt> --branch <b> --brief ...`;
  - "if no agent works in it, it is this session's own work: finish it from inside that worktree like any other branch".
  - In a mixed stop, the ordinary branch keeps its commit commands.

**Brief wording slip.** The brief says the separate counter is for branches origin/main "would NOT have handed over". Its own parenthetical and the review's fix A both mean the branches origin/main WOULD have handed over and this tree now judges. That is what is implemented.

## Tests (`tests/unit/core/test_branch_stop_gate.py`)

**Baseline seam.** The origin/main baseline is now `decide_stop` with `judge_stop` wrapped to return `own=frozenset()`. Nothing is then newly judged, so the stop is origin/main's. The existing 54-case differential cross-checks this seam's hand-over set against `_origin_main_owned`, which is origin/main's formula read independently.

**`TestTheMainCounterMatchesOriginMain`.** Every stop asserts that `blocks` equals the baseline's and that a baseline refusal implies a refusal here.

- Reviewer's R1: agent-x is touched by `sub-1` and the main thread, and sits in an unlocked harness worktree.
  - Stops 1-3 are refused, Block 1-3 of 3; the baseline allows them.
  - own-b then joins, and stops 4-6 are refused, Block 1-3 of 3, as on the baseline.
  - Stop 7 is allowed on both.
- Lock after the first refusal: own-b still gets all 3 blocks.
- A never-resolved own harness branch, touched by main only and by both threads: refused at stops 1-3 and allowed from stop 4. The main counter stays 0.
- A session with that branch plus a later own-b: exactly 6 refusals across 12 stops.
- One `linked_worktree_records` call and one `running_holds` call per stop.

**`TestTheNewlyJudgedBranchNamesTheHoldRemedies`.**

- A harness-only stop: no `add -A`, the lock and queue commands are named, and the queue command names `--worktree` and `--branch`.
- A mixed stop: own-b keeps `add -A`, and agent-x does not get it.

**`TestRefusalSequenceMatrix`.** These are the reviewer's 48 rows: touch {sub, main, both} x {harness, plain} x lock x queue x dirty, with 6 stops and own-b added at stop 4. In every row, after every stop, the counters are equal, and no stop the baseline refuses is allowed.

## Independent check: the reviewer's probe

`rev618b/probe_stop2.py` was re-run unchanged on this tree's `src`. The output is in this worktree under `untracked/scratch/p618/`.

- **R1:** `BBB` then `BBB`; own-b gets Block 1-3.
- **R2:** own-b gets 3 blocks.
- **R3:** BLOCK x3, then the stop gives way.
- **R5:** the deny text names the lock and the queue record, with no `add -A`.
- **Matrix against `mx-main.txt`:** the only differing rows are `t=main|both h=1 l=0 q=0` (d=0 and d=1). Those read `BBBBBB` here against `aaaBBB` on origin/main, which is tighter. Every other row is identical. This matches the review's fix A result.

## Known gap, not fixed: equal to origin/main, not a loosening

The consequence: suppose an ordinary own branch uses up `blocks` first and stays unresolved. An own harness branch that shows up later is then never refused, because every later stop is mixed and counts on the spent main counter. origin/main never refuses that branch at all.

Take a mixed stop that comes after `blocks` is spent: a newly judged branch plus an ordinary branch. It counts on `blocks`, so it is allowed, and the newly judged branch is recorded as abandoned without ever drawing on its own counter. origin/main also allows that stop. Falling through to the harness counter would be tighter, but it departs from the specified rule, so it was not done.

## QA

- `./scripts/qa/run_autofix.sh`: clean.
- `llm_qa.py type_check magic_values error_hiding fail_open_inventory lint`: 5/5 passed.
- `llm_qa.py docs_qa format`: 2/2 passed.
- Tests run by path with the worktree venv:
  - `tests/unit/core/test_branch_stop_gate.py`;
  - `tests/unit/core/test_branch_stop_guard.py`;
  - `tests/unit/handlers/stop/test_branch_stop_guard.py`;
  - `tests/unit/handlers/subagent_stop/`;
  - 345 passed.
- `tests/integration/test_claude_md_guidance_coverage.py` and `tests/unit/core/test_agent_ownership.py`: 418 passed.
- Re-run on `d07606150`, after the autofix: the four stop-gate paths above plus `tests/integration/test_declared_behaviour_matches_source.py`, 364 passed. After the handler prose edit: `run_autofix.sh` was clean; the stop handler tests and both integration tests, 432 passed; `llm_qa.py lint type_check magic_values docs_qa`, 4/4 passed.
- Not run: the full suite and `llm_qa.py all`.

A cosmetic point, not changed: a newly judged branch that is both dirty and unpushed prints the same three hold-remedy lines under each of its findings.
