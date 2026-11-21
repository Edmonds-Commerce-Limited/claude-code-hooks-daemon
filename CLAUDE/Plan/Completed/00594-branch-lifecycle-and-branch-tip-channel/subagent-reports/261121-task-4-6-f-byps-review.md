STOPPING BECAUSE: review complete, findings below.

**F-BYPS, Plan 00594 Task 4.6 (c5d70ed1c): 1 finding, 0 blocking. Verdict: safe to merge.**

Only the open count and the sweep's rendering use the grouping (`branch_creation.py:917-993,1034`, `branch_sweep.py:207-221,547`). Merged detection, carried and parked classification, dormancy, `delete-branch` and `--clean` never read it, so no path deletes a branch differently. Only OPEN units can join a stack, so the parked, merged and kept pools can't be stacked to cut their counts.

**Things I tried that held:**
- **Cycles:** a single commit history can't form one. A cross between two units' tips is dropped as related in neither direction (`branch_stacks.py:142-145`). A leftover cycle still counts at least 1 and the depth rule still applies.
- **Unrelated branches:** a branch only joins a stack if its tip is a strict ancestor of the next. A fork splits into separate streams.
- **Unreadable ancestry:** nothing is grouped and every branch counts alone, which over-counts (`branch_stacks.py:95,107`).

**F1 (low, design limit, confidence high):** `branch_stacks.py:113-121` treats "is an ancestor of" as "depends on". An agent that runs `git checkout -b new` while sitting on a work branch, which is the default, makes unrelated new work part of that branch's stack. Up to `stack_max_depth` 5 links then count as 1, so the cap can effectively stretch about 5 times. It's in scope: an ordinary command a careless agent types, not a parser trick. The tests don't catch it because they build stacks only from intended dependencies.
- **Possible detector:** a stack link whose commits touch files the link below didn't. Expect it to be noisy.
- **Possible fix:** lower the default `stack_max_depth` to 2 or 3.

Read-only; I wrote no report file.