# Callout: the plan fact-check feed now names an agent that clients actually have

**Plan**: 00474
**Audience**: client projects

The opt-in `plan_fact_check_feed` handler tells the session to dispatch a plan fact-checker agent, but no client project had one: the only definition lived in the daemon's own repository. The daemon now ships it as `hooks-daemon-plan-fact-checker`, a project-neutral template deployed into `.claude/agents/` like the other daemon-owned agents. A project with `handlers.post_tool_use.plan_fact_check_feed.enabled: true` gets the agent deployed at install or upgrade; with the feed off nothing is deployed. The delivered instruction now names the new agent and says how to deploy it (`hooks-daemon agents install hooks-daemon-plan-fact-checker`) when the session cannot dispatch it yet, which is until a later session. A project that dispatched the old `plan-fact-checker` name by hand should switch to the new one.
