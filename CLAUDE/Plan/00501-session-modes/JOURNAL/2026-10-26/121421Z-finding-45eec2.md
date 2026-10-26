## 12:14 · finding · —

Dogfood investigation of the long goal loop, which the owner requested on 2026-10-26 at 12:05Z. The report is in untracked/scratch/goal-loop-dogfood-report.md.

- **Size of the loop.** A stale `/goal` naming 00476 and 00501 was injected at 2026-10-23 20:10:11Z, 7s before 00476 retired. It then produced 1446 unmet evaluations over about 64h with no human prompt. The evaluator kept demanding "human or external confirmation" of the block. Ticks drove the loop in bursts of about 9 evaluations: the watchdog at :38, issue-sdlc at :44 and the stand-in every 3h.
- **Detector in observe mode.** It saw the loop, but because of the latch it logged only one would-enter per fingerprint. Every stand-in commit, which touched only the journal, changed the fingerprint and re-armed it.
- **Defects in our code:**
  - **D1:** `repo_fingerprint` hashes raw HEAD, so a commit that touches only the journal counts as progress.
  - **D2:** the latch hides how long the loop runs and how many cycles it takes.
  - **D3:** there is no escalation, and nothing tells the agent.
  - **D4:** `clear-goal` exists but is never surfaced.
  - **D5:** `Blocked` is not a terminal status, so the goal cannot be satisfied.
  - **D6:** act mode re-enters, and re-queues its notice, on every threshold crossing.
- **Outside this repo:** the `/goal` evaluator (Claude Code) and the supervisor's queueing (ccy).
- **Action:** D1, D6 and D2+D3 are dispatched to a TDD worktree.
- **Owner decisions:**
  - flipping to act mode (Task 7.3);
  - whether an agent may run `clear-goal` itself (D4);
  - the semantics of a goal that contains a Blocked plan (D5);
  - whether this counts as the third organic true positive. It plausibly does, but that is the owner's ruling.
