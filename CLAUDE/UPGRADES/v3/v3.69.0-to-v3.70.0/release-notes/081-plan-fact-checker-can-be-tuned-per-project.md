# Callout: tune the plan fact-checker for your project, and be told when the template moves

**Plan**: 00531
**Audience**: client projects

The generic `hooks-daemon-plan-fact-checker` knows nothing of your codebase's layout, test commands or vocabulary, so it checks less well than it could. It can now be tuned the way the daemon's other deployed Claude Code config is managed: the daemon ships the generic agent, you keep a tuned copy, and the copy records which shipped version it started from.

- **The feed dispatches your tuned copy.** Set `handlers.post_tool_use.plan_fact_check_feed.options.tuned_agent` to the name of an agent under `.claude/agents/`. While it is set and the file exists, the feed's instruction names it and a dispatch of it counts as the check being taken up. Unset, or naming an agent that is not deployed (a warning is logged), the generic agent is used.
- **You are told once how to tune it.** While the generic agent is in use, the first fact-check instruction also says how: copy the shipped file to a name of your own, add what the checker should know, set `tuned_agent`. The shipped template's header says the same. Template version 1.1.0; a pristine 1.0.0 deployment is refreshed on upgrade.
- **A copy records where it started.** Replace the copy's `hooks-daemon-agent-version` line with an HTML comment holding `hooks-daemon-derived-from: hooks-daemon-plan-fact-checker 1.1.0`. When a newer template ships, `deployed_artefact_drift` reports the copy at session start, names the shipped file to compare with, and says to update the marker once you have ported what helps. The daemon never edits your copy.
