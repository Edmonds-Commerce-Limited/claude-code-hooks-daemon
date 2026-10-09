# Fact check: Plan 00470 Task 4.1 diff

## REFUTED (most consequential first)

R1. "The supervisor's `decision.log` is unbounded, though `cli.py:3170` says it is bounded on daemon start."

- The supervisor front-caps it itself. `.claude/ccy/claude-supervise.py:246-254` sets `_DECISION_LOG_MAX_BYTES = 4 MiB` and `_DECISION_LOG_RETAIN_BYTES = 2 MiB` (Plan 00181).
- `.claude/ccy/claude-supervise.py:1085-1098` applies the cap after writes.
- The live file is 959,590 bytes, under the cap.
- What is true: the cap runs at write time inside the supervisor, not "on daemon start". `cli.py:3170` is loosely worded, and `cli.py:3169-3170` does list `decision.log` among auto-reaped writers.
- Plan change: delete the "unbounded" claim and the "bound it there" option. At most, correct the cli.py wording to say the supervisor caps it at 4 MiB on write.

## Claims table

| #   | Claim                                                                     | Verdict            | Evidence                                                                                                                                                                                          |
| --- | ------------------------------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Report exists at subagent-reports/261009-task-4.1-growth-sonnet.md        | VERIFIED           | `ls` finds it                                                                                                                                                                                     |
| 2   | Transcripts at `~/.claude/projects/<project>/` total 2.9 GB               | VERIFIED           | `du`: 2919 MB (`-workspace`)                                                                                                                                                                      |
| 3   | Sub-agent transcripts are 2.3 GB                                          | VERIFIED           | sum of `*/subagents` dirs is 2378 MB                                                                                                                                                              |
| 4   | `cleanupPeriodDays` is a Claude Code user setting that bounds transcripts | VERIFIED           | `remote-docs/.../settings-reference.md:647,5856`: "how many days Claude Code keeps transcripts before deleting them"                                                                              |
| 5   | `untracked/scratch/` is 329 MB                                            | VERIFIED (approx.) | `du -sm` gives 321 MB now; the figure drifts                                                                                                                                                      |
| 6   | `untracked/scratch/` holds 34,669 files                                   | VERIFIED (approx.) | `find` now gives 34,675                                                                                                                                                                           |
| 7   | `idle_housekeeping_advisor` exists                                        | VERIFIED           | `src/.../handlers/user_prompt_submit/idle_housekeeping_advisor.py`                                                                                                                                |
| 8   | The advisor reports old scratch files today                               | N/A                | This is a plan intention, not a claim about current state. No scratch reporting exists yet: grep for "scratch" in the advisor shows none.                                                         |
| 9   | `decision.log` is unbounded                                               | REFUTED            | see R1                                                                                                                                                                                            |
| 10  | `cli.py:3170` says it is bounded on daemon start                          | VERIFIED           | `cli.py:3169-3170`: "Auto-reaped writers (... decision.log) are bounded on daemon start."                                                                                                         |
| 11  | `refs/integration/changed-green/*` has 60 refs                            | VERIFIED           | `git for-each-ref` gives 60                                                                                                                                                                       |
| 12  | Those refs have no sweep                                                  | VERIFIED           | The only references are writers and readers: `merge_qa_advisor.py:52` and `scripts/qa/llm_qa.py:2015`. A grep of src, scripts and bin found no `update-ref -d` or other prune for this namespace. |
| 13  | `untracked/qa-interpreters/` is 1.0 GB                                    | VERIFIED           | `du`: 987 MB                                                                                                                                                                                      |
| 14  | `qa-interpreters/` is a reused cache filled once                          | UNVERIFIABLE-HERE  | Needs the owner's or the report's growth history. Not checked against the tree.                                                                                                                   |
| 15  | "Every daemon-written store is bounded except those below"                | UNVERIFIABLE-HERE  | Needs a full inventory. The cited report lists the stores, which I did not audit. The `decision.log` exception is wrong, since the supervisor caps it.                                            |
