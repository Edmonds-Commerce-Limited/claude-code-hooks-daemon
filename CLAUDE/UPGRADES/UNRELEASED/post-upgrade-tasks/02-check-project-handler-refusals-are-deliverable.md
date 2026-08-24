# Task: Re-check your project handlers for refusals the event cannot deliver

**Type**: audit
**Severity**: recommended
**Applies to**: any project with handlers in `.claude/project-handlers/`
**Idempotent**: yes

## Why

`validate-project-handlers` reports a handler that returns a decision its event
cannot carry — a DENY on `SessionStart`, say, which produces a schema-VALID
response with the refusal quietly removed. The handler believes it blocked;
nothing blocked.

Until now that check recognised the decision only when it was written as
`Decision.DENY`. A handler refusing through the **factory** —
`HookResult.deny(...)`, which names neither the enum nor the member, and is how
most handlers actually refuse — was invisible to it and passed clean.

Measured across the daemon's own 84 built-in handlers before the fix, exactly
one refused this way. It cost nothing there only because that handler sits on
`PreToolUse`, which *can* deny. Project handlers are the population that matters:
no test in the daemon repository can see them, and the runtime log only speaks
after the handler has already misfired in your session.

So this is not a new rule. It is the existing rule finally able to see the
common case, which means it may now report something in your project that has
been wrong since the day it was written.

### One specific handler you may have copied

`examples/project-handlers/session_start/branch_naming_enforcer.py` shipped with
exactly this defect. It refused a non-conforming branch with
`HookResult.deny(...)` on `SessionStart`, an event that cannot carry a refusal —
so if you copied it, **it has never blocked anything**, and its own unit test
asserted `Decision.DENY` and passed while that was true.

Search your handlers for it by name or by its `branch-naming-enforcer` handler
id. The corrected example now reports the branch as context and subclasses
`SessionStartHandlerBase`; copy it again, or apply the same change to your copy.

## How to detect if this applies to you

If you have no `.claude/project-handlers/` directory, skip this task.

Otherwise run the validator (sample — adapt the path to your install):

```bash
.claude/hooks-daemon/bin/hooks-daemon validate-project-handlers
```

Look for lines of the form:

```
    - WARNING: returns 'deny' but SessionStart cannot carry it on the wire,
      so the decision is silently DROPPED and nothing is enforced
```

No warnings means nothing to do here.

## How to handle

A warning means the handler's refusal has never taken effect. There are three
honest fixes, and none of them is silencing the message:

1. **Move the handler to an event that can refuse.** Only `PreToolUse` and
   `PermissionRequest` can deny *and* ask; `PostToolUse`, `Stop` and
   `SubagentStop` can deny but not ask. If the handler is meant to stop
   something, it belongs on one of those. This is usually the right fix when the
   handler was written to block.
2. **Turn the refusal into context.** If the handler is really advisory — it
   wants the agent to know something, not to be stopped — return an allow with
   `context=[...]` instead. The message still reaches Claude; the difference is
   that it now says what it means.
3. **Delete the branch** if it turns out to be unreachable.

**Ask the user before changing behaviour.** Option 1 changes *when* the handler
fires and option 2 changes *what it does*; both are judgement calls about intent
that the code cannot settle on its own. Report what you found and let them
choose.

While you are there, consider subclassing the handler's **event base** so this
class of mistake becomes a compile error rather than a warning (sample):

```python
from claude_code_hooks_daemon.core import AdvisoryResult
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase

class MyHandler(SessionStartHandlerBase):
    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        return AdvisoryResult.allow(context=["..."])
```

Every wired event has a base named after it. Subclassing `Handler` directly
still works and is not deprecated — the base simply moves the check earlier, to
mypy, if your project runs it. See `CLAUDE/PROJECT_HANDLERS.md`.

## How to confirm

```bash
.claude/hooks-daemon/bin/hooks-daemon validate-project-handlers
```

Reports every handler as `Status: OK` with no WARNING lines. If your project
type-checks its handlers, `mypy` on `.claude/project-handlers/` should also be
clean.

## Rollback / if this goes wrong

Every change here is a source edit in your own repository, so `git diff` and
`git checkout` cover it. Restart the daemon after reverting
(`.claude/hooks-daemon/bin/hooks-daemon restart`) — the running daemon holds the
old code until it does.
