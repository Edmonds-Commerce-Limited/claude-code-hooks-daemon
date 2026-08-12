# Phase 1: which injection point actually lands

Measured against this session's own transcript (37,475 records / 56 MB, 18
compactions). Everything below is counted from the transcript or read from the
source, not inferred.

## Task 1.1 — the baseline, captured verbatim

The restriction as it appears in the current session's system prompt:

```
Do not call the AgentTool unless the user requested it
Do not use workflows or deep-research unless the user requested it
```

Two corrections to what PLAN.md recorded when it was opened:

1. It is **`AgentTool`**, one word, not "Agent tool". A config default that
   quotes the instruction must quote it correctly or it will read as answering
   something that is not there.
2. There are **two** restrictions, not one. The second covers workflows and
   deep-research and was not captured at all. Any authorisation surface that
   addresses only the first leaves the second in force — which is the correct
   outcome unless the project has separately authorised the second, and that
   is exactly the sort of thing the config surface has to be able to express
   independently.

Neither line terminates with a full stop, and both sit near the END of the
system prompt, after the "Delivering work" and "Corrections" sections. So
within its own document the restriction already occupies a recency position.

## Tasks 1.2 / 1.3 — the two channels are not comparable in the way the plan assumed

PLAN.md listed SessionStart and UserPromptSubmit as adjacent middle rows of the
lever table, differing mainly in repetition. They are not adjacent. They do not
even use the same delivery channel.

|                                          | SessionStart          | UserPromptSubmit          |
| ---------------------------------------- | --------------------- | ------------------------- |
| attachment subtype                       | `hook_system_message` | `hook_additional_context` |
| `content` shape                          | plain string          | array of strings          |
| deliveries this session                  | **18**                | **198**                   |
| of which carried the full daemon payload | **1**                 | 198                       |

`SessionStart` never appears in `hook_additional_context` at all — zero of
1,557. It is a different transport.

### The decisive number: the full SessionStart payload fired exactly ONCE

Broken down by `hookName`:

| hookName               | deliveries | content size              |
| ---------------------- | ---------- | ------------------------- |
| `SessionStart:startup` | 1          | 1,223 chars               |
| `SessionStart:compact` | 17         | 173 chars each, identical |

The 173-char compact payload is only the dogfooding plugin reminder. The
1,223-char startup payload — the plan-QA drift report and its siblings — was
delivered once, at the very beginning, and never again across 18 compactions.

### Why, mechanically

`plan_qa_sweep.matches()` (and the same pattern in
`plan_workflow_asset_checker`, `project_handler_load_checker`) opens with:

```python
if is_resume_session(hook_input):
    return False
```

and `utils/session_helpers.is_resume_session` is a transcript-size heuristic:

```python
return path.stat().st_size > RESUME_SESSION_MIN_TRANSCRIPT_BYTES  # 100
```

At `SessionStart:compact` the transcript is 56 MB. So the check returns True,
`matches()` returns False, and the handler is silent for the entire remaining
life of the session. It fires only in the opening moments when the transcript
is still the sub-100-byte stub.

That is correct behaviour for a *drift report* — nobody wants the plan-QA sweep
re-printed after every compaction. It is disqualifying for a *standing
authorisation*, which must hold for as long as the session does.

## Task 1.4 — the finding

**UserPromptSubmit, decisively. SessionStart is close to unusable for this.**

The reasoning is a cadence argument, and it is the same argument Plan 00216
arrived at from the other direction (position beat emphasis):

- The restriction is in the **system prompt**, which is re-sent on **every
  single request**. It never decays, never gets compacted away, and is never
  more than one turn old.
- A SessionStart injection is delivered **once**, then compacted away, and —
  by the daemon's own prevailing convention — does not come back.
- A UserPromptSubmit injection is delivered **on every prompt**, adjacent to
  the freshest user turn, and is structurally immune to compaction loss
  because the next prompt re-delivers it.

Only UserPromptSubmit matches the re-delivery cadence of the thing it is
answering. Anything delivered once loses to something delivered every turn —
not on wording, on arithmetic.

This makes Task 3.3 (rate limiting) load-bearing rather than optional, and it
should be a decay rather than a hard cooldown: the value of this injection is
precisely that it keeps pace with the system prompt, so a cooldown long enough
to span a compaction would reintroduce the SessionStart failure it exists to
avoid.

## What this phase did NOT measure, and must not be read as measuring

**Whether the injected text changes delegation behaviour.** That is the
question that actually matters, and it cannot be answered honestly here.
Measuring it means running the injection against a main-thread session and
observing whether delegation follows — N=1, on the same agent that knows what
the experiment is. This session already recorded the lesson that single-sample
results on a high-variance system are not evidence (Plan 00216's scout coverage
measured 34 / 32 / 17 / absent / absent on an unchanged tree of 34).

So Phase 1 establishes **which channel can carry a standing instruction at all**
— a deterministic, mechanical question with a deterministic answer. It does not
establish that carrying it works.

### One honest observation of the failure mode

Not a measurement of the fix, but worth recording because it is live evidence
that the problem is real rather than theoretical.

The user's standing authorisations for delegation ("fix all the things - sub
agent orchestration", "use worktrees ffs dont just fire agents on the same git
index") were granted in this session, before several compactions. The
compaction summariser **did** preserve them — they appear in the summary under
standing intents. Despite that, no sub-agent was dispatched in the segment
following the compaction; all work continued single-threaded.

The authorisation survived, and still lost. It survived as a *quoted historical
user message inside a summary*, competing with a system-prompt line that is
structurally fresh on every request. That asymmetry — preserved-but-demoted
versus permanently-fresh — is exactly the gap this plan exists to close, and it
is a stronger argument for the config surface than the original framing of
"the request is gone by the next session". The request is often still there.
It has just been relegated to history.

## Consequences for Decision 1

Decision 1 said "config declares, hooks deliver, CLAUDE.md documents", with the
delivery hook left as "SessionStart/UserPromptSubmit" pending this phase.

Resolved: **UserPromptSubmit only**. A SessionStart variant should not be built
even as a belt-and-braces companion — it would fire once, be compacted away,
and its absence for the rest of the session would be invisible, which is the
worst shape of failure this codebase keeps rediscovering.
