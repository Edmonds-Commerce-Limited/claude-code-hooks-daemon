# Task: Tune the plan fact-checker for this project

**Type**: workflow-change
**Severity**: optional
**Applies to**: all
**Idempotent**: yes

## Why

The shipped `hooks-daemon-plan-fact-checker` is deliberately generic. A checker that knows where this project's code lives, how to search it and which directories to avoid verifies plan claims better. The feed can now dispatch a project-owned tuned copy (`plan_fact_check_feed` option `tuned_agent`), and the copy records the shipped version it started from so the daemon reports when the template improves.

## How to detect if this applies to you

It applies when `handlers.post_tool_use.plan_fact_check_feed.enabled` is `true` in `.claude/hooks-daemon.yaml` and `options.tuned_agent` is not set. If the feed is disabled, skip this task.

## How to handle

Sample steps, adapt to the project:

1. Copy `.claude/agents/hooks-daemon-plan-fact-checker.md` to `.claude/agents/<project>-plan-fact-checker.md` and change its `name:` to match.
2. Add to the copy what the checker should know about this codebase: where code lives, how to search it, the test and QA commands, directories that are off-limits, project vocabulary. Ask the user if unsure.
3. Replace the copy's `hooks-daemon-agent-version` line with an HTML comment holding `hooks-daemon-derived-from: hooks-daemon-plan-fact-checker 1.1.0`.
4. Set `handlers.post_tool_use.plan_fact_check_feed.options.tuned_agent: <project>-plan-fact-checker` in `.claude/hooks-daemon.yaml` and restart the daemon.

## How to confirm

The next owed fact-check instruction names the tuned agent, and `.claude/agents/<project>-plan-fact-checker.md` carries the derived-from marker.

## Rollback / if this goes wrong

Remove the `tuned_agent` option; the feed returns to the generic agent. The tuned file is the project's own and can be deleted at will.
