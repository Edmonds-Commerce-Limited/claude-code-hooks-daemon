# N526 recurrence: the perf sweep fails again on main

Branch `worktree-n526-perf-again`, commit `e397c50e3` (on top of `dd42db411`).

## Is it a regression? No

`git diff ac24e09b6 a7adea3eb` touches nothing in `subagent_full_qa_blocker.py`, its test file, `tests/load_scaling.py`
or `.claude/hooks-daemon.yaml`. The commits in between (Plan 00501 session modes, the doc-write jail fix, the skill_scan
import fix) live in other modules. Measured with a detached `ac24e09b6` checkout, interleaved with HEAD on the same
host (load 5-10 on 8 cores), 2000 lines, `process_time` best/median of 5:

| shape              | ac24e09b6 min/med | HEAD a7adea3eb min/med |
| ------------------ | ----------------- | ---------------------- |
| a.insert(0,'x{i}') | 0.202 / 0.234     | 0.171 / 0.240          |
| a.insert(1,'x{i}') | 0.166 / 0.242     | 0.168 / 0.275          |
| a.pop()            | 0.124 / 0.179     | 0.114 / 0.176          |
| a=a+['x{i}']       | 0.249 / 0.366     | 0.211 / 0.318          |
| a=['y']+a          | 0.196 / 0.326     | 0.231 / 0.330          |

The two are the same within noise. Note that `_timed` measures WALL time (`perf_counter`), not CPU.

## What actually fails: a full garbage collection inside the timed window

The median-vs-min spread pointed at the collector. A `gc.callbacks` probe run INSIDE pytest (same file collected,
about 310k live objects) showed that one judgement makes 130-146 gen0 and 11-13 gen1 collections, so it trips a gen2.
Each gen2 walks the whole test-process heap: 0.13-0.18 s here per collection, and 1-2 land in each judgement. That
is 25-40% of the measured time. The cost scales with the host process heap and CPU, not with the script. CI's
slower runner and different heap turn it into the 1.6 s miss. Per stage (gen0/gen1 collections): `ast.parse` 68/6, the
tree index 29/2, `_grown_argvs` 44/4, `_process_arguments` 7/0.

## What changed (`e397c50e3`, behaviour-preserving, bound still 1.5)

- `_TreeIndex` stores each node's children as an int span of the BFS `nodes` list (`first`/`end` dicts). Before,
  it held one list per node. Ints are not GC-tracked, so the index now adds 0 gen0 collections, down from 29.
  `_child_lister` returns the slice.
- `ast.iter_child_nodes` is inlined in the index sweep, which drops two generator layers per node.
- `_operands_run_in_process` returns `[]` at once when the tree holds no `<exec>(...)` builtin call and no
  `run_path` call. Only those calls ever produced an operand, so the result is identical. The check is on the AST,
  so an NFKC-normalised identifier still matches. The new `_runs_in_process` predicate is shared by the pre-check and
  the walk.
- `_Reading` is `slots=True`.
- Test `_timed` calls `gc.collect()` before starting the clock. That keeps GC debt left by EARLIER tests out of this
  window. Collections that the judgement's own allocations cause still count. This is hygiene, not a looser bound.

Fail-closed behaviour is untouched: the parse meter, `_OVER_BUDGET` and `_scanned_verdict` are not modified.

## Timings after (inside pytest, gc.collect first, wall s, two interleaved rounds)

| shape              | ac24e09b6 (g2 count) | after (g2 count) |
| ------------------ | -------------------- | ---------------- |
| a.insert(0,'x{i}') | 0.475, 0.547 (1)     | 0.461, 0.368 (0) |
| a.insert(1,'x{i}') | 0.582, 0.564 (1)     | 0.422, 0.359 (0) |
| a.pop()            | 0.377, 0.391 (0)     | 0.281, 0.207 (0) |
| a=a+['x{i}']       | 0.684, 0.707 (1)     | 0.476, 0.430 (0) |
| a=['y']+a          | 0.626, 0.678 (1)     | 0.494, 0.312 (0) |

Gen1 collections per judgement went from 11-13 to 8-10, so no shape trips a gen2 now. The worst case is at a third
of the bound (0.49 against 1.5) on a host at load 5. The margin is thin for two shapes, which sit at exactly 10 gen1
against a threshold of more than 10. The next lever is `_grown_argvs`. Its per-change tuples, `_splicing` closures
and per-reading `_ListState` copies are about 44 gen0 collections, and cutting them needs restructuring, which I did
not do.

## QA

- `pytest tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py`: 1476 passed.
- `pytest -m perf_sweep` on that file: 11 passed.
- `mypy --strict` on the module: clean.
- Targeted QA (one run, on `e397c50e3`): `QA: 38/41 PASSED, 2/41 FAILED, 1/41 NOT MEANINGFUL (detector failed: lint)`.
  - lint: F402. The loop variable `field` in the index sweep shadowed the dataclass `field` import. Renamed to
    `attribute` in the follow-up commit. ruff and mypy strict are clean, the file passes 1476 and perf_sweep passes 11.
  - changed_tests: 4501 passed, 2 failed. The failures are
    `test_safety_handlers_hostile_input_performance.py::TestCombinatorialSmallInputShapesStayLinear::test_bash_command[double_star_glob]`
    and `[letter_sequences]`. They are wall-clock bounds, and they failed under the full run on a host at load 5-10.
    Re-run alone 3 times on this branch (load 2.4): 18/18 passed each time. This change makes the scan cheaper, not
    dearer. I did not re-run the whole targeted QA (the brief says once). The coordinator's gate should confirm those two.

Head sha: see the follow-up commit after `e397c50e3` on `worktree-n526-perf-again`.
