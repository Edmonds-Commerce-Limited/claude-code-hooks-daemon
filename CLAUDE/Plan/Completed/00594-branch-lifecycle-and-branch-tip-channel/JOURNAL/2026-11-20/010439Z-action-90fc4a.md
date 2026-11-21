## 01:04 · action · — — Task 4.6 stack grouping built

Task 4.6 (stack grouping) built per the DESIGN 7.1 ruling on branch
agent-ab8590f82ee261d91-c14c8267. RED tests committed first (bdb18c137),
implementation in 2fa237f93.

- New `core/branch_stacks.py`: `read_tip_ancestry` (one `git rev-list --topo-order --parents <tips> --not <default refs>`; no exclusion or a git
  failure returns None), `group_stacks` (nearest-ancestor chains; a fork ends
  the chain and the base goes with the first arm by name; crossing two-tip
  units are related in neither direction), `stack_charge` /
  `open_work_charge` (1 up to `branches.wip.stack_max_depth`, default 5, then
  1 per extra link).
- One count: the sweep's `pool_count(OPEN)` (and so the stop guard's
  `open_work_count`) and the creation guard / preflight / ladder
  (`branch_creation.read_pools`, `creation_report`) all call
  `branch_stacks.open_work_charge`. Unknown ancestry groups nothing, which
  over-counts (fail closed).
- Classification before grouping: only OPEN-pool units are passed in, so
  parked, merged, park-carried and foreign branches never join a stack.
- The sweep prints a "Stacks" section and the cap deny / preflight print one
  line per stream; a stack line names depth and bottom with "land the bottom
  first".
- Tests compare sweep, stop, guard and ladder counts on real repositories
  (five-deep stack plus singles, pushed remote-only stack, seven-deep past
  the depth cap, fork, merged bottom link).
- Release note 007 and a `branches.wip.stack_max_depth` config-change entry.

Seen while testing, not caused by this change:
`test_branch_pressure.py::TestStopJudgesOwnOpenBranches::test_over_cap_with_nothing_touched_by_this_session_allows`
fails on the base commit too (the stop decision carries ladder WARN lines
the test expects to be absent).
