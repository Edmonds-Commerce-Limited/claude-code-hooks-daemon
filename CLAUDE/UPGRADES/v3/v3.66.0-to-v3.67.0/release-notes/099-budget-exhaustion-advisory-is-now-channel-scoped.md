# Callout: the budget-exhaustion advisory is now channel-scoped, and a dead sub-agent surfaces too

**Plan**: 00466
**Audience**: operators

`budget_exhaustion_detector` matched a generic "budget exhausted"/"quota
exceeded" wording family against any non-excluded tool's response, so
reading a diff, log or file whose SOURCE CODE merely quoted that wording
(e.g. an error-message string literal) raised a false BUDGET EXHAUSTED
alert. It now matches only two channel-scoped signals, each against the one
tool it can genuinely arrive from: the WebSearch tool's own budget-refusal
text, and a dispatched sub-agent (Task/Agent) cut off mid-task by a harness
usage-limit rejection ("Agent terminated early due to an API error..."),
anchored so a sub-agent's own prose merely quoting that phrase does not
match. The generic keyword family is removed entirely, and Bash (whose
response is the model's own invoked command output, never a
harness-populated field) joins the default excluded tools outright — while
Task/Agent, previously excluded, no longer are, since they now carry a real
signal of their own. When a sub-agent dies on its usage limit, the advisory
names which dispatch died (preferring its `name`) and tells you to
re-brief it once the limit resets. This covers FOREGROUND dispatches only:
a background/teammate dispatch returns before any later limit hits, so its
death never reaches this signal — Plan 00470 Tasks 3.1/3.2 cover that
separately, through the StopFailure and Notification handlers. A project
that has confirmed its own CLI reports a genuine quota signal through Bash
can set `excluded_tools` explicitly to a list WITHOUT `Bash` and pair it
with a specific `extra_patterns` regex of its own (adding `Bash` to
`excluded_tools` excludes it — the opposite).

A new sibling handler, `agent_terminated_early_failure_detector`
(PostToolUseFailure, on by default), closes the other half of the gap: a
foreground dispatch that dies with `is_error: true` delivers its death
through PostToolUseFailure's `error` field, an event `budget_exhaustion_detector`
never receives at all, so that occurrence previously went unsurfaced
regardless of this fix. It matches the same harness text, anchored and
tail-gated the same way, channel-scoped to Task/Agent, and gives the same
re-brief advisory.
