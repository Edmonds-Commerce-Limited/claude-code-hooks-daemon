# Plan 00560: decisions needed from you

This page explains the plan in plain terms and lists the seven questions it needs answered. The full plan is in [PLAN.md](PLAN.md); you do not need to read it to answer these.

## Your answers so far (4 November)

- **Q1, decided:** there is no separate store for reports. An agent asked for a report with no plan folder stops and asks for one, and the coordinator either makes the plan or tells the agent to make it.
- **Scope, decided (80/20):** the usage tracking in points 2 and 3 below is dropped as over-engineering. That makes Q2 and Q7 moot.
- **New, decided:** any command that uses a scratch file (for example `git commit -F`, `gh --body-file`, `mkplan.bash --journal`) must chain `&& rm <file>`, so the file is deleted only when the command succeeds. The unchained form is blocked.
- **Still open:** a whitelist of file names for the scratch directory (you were leaning towards it), plus Q3, Q4, Q5 and Q6.

## The problem in one paragraph

Agents keep valuable work (research, reviews, design notes, sub-agent reports) in `untracked/scratch/`. That directory is gitignored, so the work never reaches GitHub, and it is lost when the container goes or someone tidies up. Issue #155 counted about 237 such files in one project and three near-losses in one week. The daemon makes it worse: several of its own messages tell agents that scratch is a good place to keep things.

## What the plan does

1. **Stops the bad advice.** The daemon's messages and docs will say that scratch is only for throwaway files used in the same session (commit message bodies, issue bodies, agent briefs, test output). Anything worth keeping goes to a plan folder, a journal entry, a pushed commit or an issue.
2. **Tracks use.** The daemon notes each file an agent creates in scratch, and whether a later command used it (for example, `git commit -F file` uses a commit-message file).
3. **Checks at stop.** If a session tries to stop while it still has scratch files that nothing used, the stop is refused. The message lists each file and three choices: use it, move it somewhere tracked, or delete it.
4. **Allows only known throwaway shapes.** Creating a file in scratch that does not match a known throwaway pattern is refused, and the message says where that kind of file should go instead.
5. **Reports leftovers at session start.** A new session lists old leftovers with the same three choices. Nothing is ever deleted automatically.

This works alongside Plan 00558, the branch-hygiene work you have already seen. Both add a check at stop, and they share one design.

## The seven questions

Each has my recommendation. Reply with the number and "yes", or with your own answer.

| #   | Question                                                                                          | Options                                                                                                                          | Recommendation                                                                                                                                                                     |
| --- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | When an agent is dispatched for work that belongs to no plan, where must its report go?           | A tracked report folder (e.g. `CLAUDE/AgentReports/`); a GitHub issue or PR comment; or nowhere, so it must name a plan or issue | Allow a tracked report folder as a project option, off by default. Until a project sets one, plan-less work must name a plan or an issue.                                          |
| Q2  | Does an agent reading a scratch file count as "using" it?                                         | Yes / no                                                                                                                         | Yes. Test output is written to be read back. This is safe because point 4 above stops other kinds of file being created there.                                                     |
| Q3  | Which directories count as scratch?                                                               | Only `untracked/`; or every gitignored path                                                                                      | `untracked/` by default, configurable. Widen it later if reports show work lost elsewhere.                                                                                         |
| Q4  | This repository already has about 90,000 files (1.4 GB) under `untracked/`. What happens to them? | Triage them all; or record a baseline and only judge new files                                                                   | Record a baseline list on the first run and only judge files after it. You go through the `*-report.md` files once, by hand, and move anything worth keeping into a plan or issue. |
| Q5  | Should the new checks warn or block at first?                                                     | Warn first, block later; or block at once                                                                                        | Clients get warnings for one release, then blocks. This repository blocks from day one so we find the rough edges first, which is how Plan 00558 rolled out.                       |
| Q6  | How old must a leftover be before the session-start report lists it?                              | 14 days (today's setting); or 24 hours (what #155 asks for)                                                                      | 24 hours. The old 14-day setting is retired and mapped onto the new one automatically.                                                                                             |
| Q7  | When the main session stops, whose unused files does it answer for?                               | Only its own; or its own plus those its sub-agents left behind                                                                   | Its own plus anything its sub-agents left unused. A sub-agent answers only for its own files. This matches Plan 00558.                                                             |

## What happens next

Once these are answered, the plan moves to a short design phase and then builds in small pieces, each with tests first. Plan 00558's check at stop is already built, so this plan reuses its design rather than adding a second one.
