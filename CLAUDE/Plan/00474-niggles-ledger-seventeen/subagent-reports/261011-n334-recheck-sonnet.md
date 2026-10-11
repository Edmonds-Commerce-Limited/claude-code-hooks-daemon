# N334 re-check: supervisor post-compaction /goal and continue vs the Claude Code 2.1.274 fix

Verdict: **UNDETERMINED WITHOUT A LIVE COMPACTION** for `/goal` (leaning STILL NEEDED); **STILL NEEDED** for `continue`. The fix covers a different scenario from either injection. Installed version: `claude --version` printed `2.1.296 (Claude Code)`, so the fix is present.

## 1. What the supervisor does (`.claude/ccy/claude-supervise.py`, read only)

- `continue`: lines 4762-4775 (docstring): "when a compaction is under way ... decide WOULD_CONTINUE exactly once per episode to resume the post-compact session." Decision emitted at 5987: `"{detected} -> would inject continue"`. Body at 6271: `_CONTINUE_BODY = "continue"`. This is an in-session nudge to restart the turn the compaction interrupted. It is not a restore of any state.
- `/goal`: not a post-compaction re-injection. Lines 23-25: "a `/goal` typed from a daemon-written goal-intent signal (Plan 00269)". The branch at about 7240-7262 skips the type when "goal signal identical to last injection" (thrash guard, `last_goal_text`). Nothing in the file links `/goal` to a compaction. A grep for lines mentioning both compact and goal found only generic comments (1445, 7400, 7413).
- The daemon side, `src/claude_code_hooks_daemon/handlers/post_tool_use/goal_injection.py` lines 48-56, re-asserts a goal on a plan touch: "A resumed session still gets its goal back ... a SAME-session-id resume (Claude Code's `--resume`/`--continue`) gets answered". It is keyed to plan touches and resumes, not to the PreCompact signal.

## 2. What 2.1.274 fixed

Exact entry, quoted from `CLAUDE/Plan/Completed/00486-claude-code-version-tracking/subagent-reports/261003-task-1.4-backfill-review-sonnet.md:35`:

> 2.1.274: "Fixed an active `/goal` being lost when resuming (`--continue` / `--resume`) a session that had compacted"

The same row only flags it "R" (redundancy candidate): "Check whether the goal re-injection after compaction is still needed". No vendored raw changelog was found under `CLAUDE/remote-docs`. The reviewer report is the only source, and no other report analyses it.

## 3. What the docs say the re-injection is for

`CLAUDE/development/CcySupervisor.md` has no statement that `/goal` or `continue` compensates for a Claude Code compaction bug. Line 26 only lists `/compact`, `continue`, `/goal` and `/model` as injection decisions. Lines 57-58 and 426 describe ordering and compaction origin. The `/goal` family is described only as goal-intent signal driven (code lines 23-25).

## 4. Evidence of post-compaction behaviour

None found. No plan journal or report under `CLAUDE/Plan/*/JOURNAL` or `CLAUDE/development` records a `/goal` surviving or being lost after a compaction on 2.1.274 or later. The only file with relevant text is the 00486 backfill report quoted above.

## Reasoning

- The fix is scoped to quitting and then resuming (`--continue` / `--resume`) a compacted session. The supervisor's `continue` runs inside a live session right after a compaction, and its `/goal` runs on a plan-start or plan-touch signal. Neither scenario is named in the fix.
- `continue` restores turn momentum, not goal state, so the fix cannot make it redundant.
- `/goal` re-injection after a resume overlaps the fixed scenario only partly. The daemon's `--resume` re-assertion (goal_injection.py 48-56) is the part that could be redundant.
- The idle `/compact` then `continue` flow keeps the same session, and the fix text does not say whether an active `/goal` survives an in-session compaction. The supervisor's `/goal` is duplicate-guarded by text hash only, so a surviving goal would be re-typed only on a new signal. A lost goal would not be restored unless a signal re-fires.

## What a live observation must show before removing anything

1. On 2.1.274 or later, with a `/goal` active and set by the supervisor or a human, run a real compaction (human, auto or supervisor origin) with no goal-intent signal pending. Check whether the goal is still active afterwards (for example the goal indicator, or a stop-condition check on the next turn).
2. Separately, quit and `--resume` a compacted session that had an active `/goal`. Check whether it survives with no `goal_injection` re-assertion. The re-assertion could be disabled to test this, but that edit is not made here.
3. If the goal survives in both cases, the daemon's resume re-assertion is redundant. The `continue` injection is not redundant in either case.

Recommendation: remove nothing; this agrees with the owner-question sheet (section 4, option A for the check only).
