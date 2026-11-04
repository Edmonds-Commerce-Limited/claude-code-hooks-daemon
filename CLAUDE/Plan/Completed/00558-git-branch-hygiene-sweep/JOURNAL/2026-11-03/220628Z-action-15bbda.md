## 22:06 · action · —

Merged `worktree-558-sameturn` (the same-turn half of Task 4.5) at af58052d0. The agent's QA was 41/42, with the only failure the accepted "too-broad" notice: 4131 tests passed. On main after the merge, ruff and black pass on all touched Python, 580 touched and related tests pass, and the daemon restarted and is running.

Design note: no main-thread turn counter existed, so the agent added a UserPromptSubmit handler, `evacuation_turn_marker` (priority 43), which counts prompts. The main thread's turn key is that count; a sub-agent's key is its `agent_id`. Records are bounded to 50 per identity.

The worktree held only captures, already-committed commit messages and runtime state. I inspected them, deleted them deliberately, and removed the worktree and the branch locally (bundle) and remotely.

Also recorded from the Task 4.3 fact-check: `branch-park --clear` does not refresh the labels snapshot. Until the next SessionStart, an unparked branch still reads as parked, so the dormancy block can only be late, never wrong.
