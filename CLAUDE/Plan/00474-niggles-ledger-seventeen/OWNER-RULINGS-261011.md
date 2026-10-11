# Owner rulings, 2026-10-11 (Plan 00474)

These are the owner's answers to [OWNER-QUESTIONS-261011.md](OWNER-QUESTIONS-261011.md). The owner dictated them, so each
ruling is paraphrased closely, and the owner's own words are quoted where the wording matters. The coordinator's later
choices are labelled as the coordinator's.

## Standing guidance given with these rulings

- **Clear winners are decided by the coordinator, not put to the owner.** "If there's a clear winner that's clearly
  better, then it wins and we implement it." Low-level technical questions the code can answer must not be bubbled up.
- **No other coordinator is coming.** The session that is running is the coordinator. It must not defer to one. For a
  hard question it may dispatch a `fable` sub-agent, briefed narrowly so the token cost stays small.
- **Questions put to the owner must carry context.** A bare plan number, row id or option letter gives the owner
  nothing to go on. Every question must say what the thing is, why it matters, and what each choice does, in plain
  terms. The owner found this sheet's letter-and-number shape "not human friendly at all".
- **Claude Code changelog realignment has a standing approval.** If recent Claude Code versions have made daemon
  behaviour redundant, or changed what the daemon must do, investigating and realigning needs no further approval.
  Each release should check how the latest Claude Code has moved the goalposts.

## Rulings

| Row  | Ruling                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N280 | A test run must never change the main checkout's tracked files: "Test runs shouldn't cause side effects that cause the main project stuff to be updated. Definitely not." Find the cause and make it impossible. The owner suggested running tests in a worktree so side effects are visible. The fixture change (A) is not the answer.                                                                       |
| N330 | Adopt `spend_limit`: "yeah, we should be able to use it, obviously."                                                                                                                                                                                                                                                                                                                                          |
| N333 | A, leave Claude Code's auto-continue alone: "Hooks daemon should not be trying to fight Claude Code", and where Claude Code config can do something, the daemon should not get involved unless it is enhancing it.                                                                                                                                                                                            |
| N334 | Check whether Claude Code has made it redundant, and remove it if so; this falls under the changelog-realignment approval. New feature, filed separately: a manual `/goal clear` turns automated goal injection off, with a status-line indicator, a way to re-enable it, and a control-panel mod.                                                                                                            |
| N336 | A variant: a daemon or supervisor compact threshold set above Claude Code's autocompact window is invalid configuration and should be rejected as such. The owner does not see how a double compaction could happen.                                                                                                                                                                                          |
| N337 | The inverse of the proposal. When the cache is cold, compacting is right, and waiting for a warm cache is wrong. With a large context, compact before the cache goes cold, unless the session is expected to die. Open research: what compaction costs and which model runs it, whether Claude Code has an idle-compact setting, idle cron ticks versus cache warmth, and session statistics for auto-tuning. |
| N342 | Require a git version that supports relative worktrees, rather than any of A, B or C, and establish minimum versions for the tools the daemon needs (warn or error). Worktrees as subdirectories of the repository should be the default. Relative worktrees also fix the container and desktop path mismatch.                                                                                                |
| N361 | A, BLOCK at commit.                                                                                                                                                                                                                                                                                                                                                                                           |
| N373 | No question; the coordinator's change stands.                                                                                                                                                                                                                                                                                                                                                                 |
| N376 | None of A, B or C as posed. Do not run or re-run the full suite on the loaded host. Move routine QA to diff-based checks, with the full suite at release time only. Investigate a release strategy that runs the expensive QA in GitHub Actions on a pull request into a release branch, with parallel jobs if possible, followed by local acceptance testing.                                                |
| N389 | A: fix the two journal lines surgically; the owner is content to run a command if one is needed. B: the host names can go on the blocked word list (a human edits it). New design, filed separately: a controlled process for agents to make small, safe journal corrections.                                                                                                                                 |
| N396 | Do the optimal thing; A is the clear winner.                                                                                                                                                                                                                                                                                                                                                                  |
| N397 | Go with the recommendation, B.                                                                                                                                                                                                                                                                                                                                                                                |
| N402 | B, stay fail-closed, and add guidance to the deny that names the canonical way to reach the project root.                                                                                                                                                                                                                                                                                                     |
| N411 | A, on the coordinator's recommendation.                                                                                                                                                                                                                                                                                                                                                                       |
| N419 | Not addressed by name. The clear-winner rule covers it, so the coordinator implements B.                                                                                                                                                                                                                                                                                                                      |

The deliberate limits are confirmed ("that's fine").

## Not answered

The owner did not rule on Plans 00470, 00479, 00484 and 00500. The owner's comment was that a plan number alone gives no
context. Those questions are to be re-put with full context, after the clear winners among them are settled by the
coordinator.
