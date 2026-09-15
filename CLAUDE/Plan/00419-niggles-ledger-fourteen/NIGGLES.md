# Plan 00419 — Niggles

The full write-up for each entry in ledger fourteen. `PLAN.md` carries the
status and the tasks; the reasoning, evidence and candidate remedies live
here, because they are findings rather than plan state.


### N1 — `debug_hooks.sh` cannot work in the repository that dogfoods it

Found by a sub-agent following Plan 00418 Task 1.1, which names
`scripts/debug_hooks.sh` as the way to capture real hook payloads.
`CLAUDE/DEBUGGING_HOOKS.md` says the same, and `CLAUDE/HANDLER_DEVELOPMENT.md`
tells handler authors to debug first rather than guess at `hook_input`'s shape.
The script fails on this repository, and has two independent defects.

**Defect 1 — it looks in the wrong place for a self-install.**
`scripts/debug_hooks.sh:32` searches
`$PROJECT_ROOT/.claude/hooks-daemon/untracked/`. That directory **does not
exist here**: in self-install mode the daemon IS the project, and its sockets
live at `$PROJECT_ROOT/untracked/` — verified, two are there now
(`untracked/daemon-*.sock`). The comment above the line says it "supports both
suffixed (container) and unsuffixed (desktop) paths", which is true and beside
the point: it handles two socket NAMES and only one LAYOUT.

**Defect 2 — it dies before reaching its own fallback.** The line is

```bash
SOCKET_PATH=$(find "$PROJECT_ROOT/.claude/hooks-daemon/untracked/" -name "daemon*.sock" 2>/dev/null | head -n1)
```

under `set -euo pipefail`. `find` on a missing directory exits 1; `pipefail`
carries that through `head`'s success; the assignment therefore fails and
`set -e` kills the script — **before** the `CLAUDE_HOOKS_SOCKET_PATH` fallback
five lines below. So the env-var escape hatch is unreachable on exactly the
layout that needs it, and the failure is silent: no message, no non-zero
explanation, just nothing.

Reproduced directly rather than reasoned about, and the first attempt to
reproduce it was WRONG in an instructive way: running the pipeline bare in a
subshell reaches the next line and exits 0. It only dies in the ASSIGNMENT form,
because that is what makes the pipeline's status the statement's status. A
reproduction that drops the assignment concludes there is no bug.

**Why it matters more than a broken script.** Three documents route an agent
here as the sanctioned alternative to guessing at payload shapes. An agent that
follows that instruction gets silence, concludes the tool is unavailable, and
falls back to inference — which is precisely the failure mode Plan 00418 exists
to avoid, since the handler it is rebuilding was deleted the first time because
the project reasoned about a hook field from documentation instead of capture.

### N2 — archiving a plan silently breaks every link it makes to a sibling

Archiving moves `CLAUDE/Plan/NNNNN-x/` to `CLAUDE/Plan/Completed/NNNNN-x/`, one
level deeper. Every `](../00NNN-y/PLAN.md)` the plan contains then resolves to
`Completed/00NNN-y/...`, which does not exist — so a plan's OUTBOUND links all
break at the moment it is archived.

Found the day 00413 was archived: eight dead links across its `PLAN.md` and
`NIGGLES.md`, every one pointing at a plan that had graduated out of it
(00414, 00415, 00416). Those pointers are the entire reason a reader opens an
archived ledger, so the links that break are the load-bearing ones.

**Two separate gaps, and the second is the more interesting:**

1. **The archival procedure does not repoint outbound links.** The Plan
   Completion Checklist covers the `git mv`, the index row, the statistics and
   the retention window — all of which are about the plan's INBOUND references
   and the index. Nothing addresses the links pointing the other way.

2. **`plan-qa --sweep` reports the tree CLEAN with eight dead links in it.**
   Verified: the sweep was run immediately after the archival and again after
   this was found, and reported `0 findings` both times. Only docs-QA notices,
   as an ADVISORY — which is how it reached a sub-agent's QA run as unexplained
   noise in an unrelated worktree rather than reaching the person who broke it.

The inbound direction is already handled better, which is what makes the gap
easy to miss: links pointing AT an archived plan were caught the same day by a
docs-QA block on an edit. Direction determines whether you find out.

**Remedy is not yet decided** and it is a real fork: repoint links during
archival (mechanical, but rewrites an archived document), or teach `plan_qa` to
resolve links so the sweep stops reporting clean when it is not. The second is
the better guard — it catches the case regardless of how the links broke — but
it does not fix the eight that already broke, and it is the sweep's own
credibility at stake: a sweep that says "clean" while a tree is not is worse
than no sweep, because it is believed.

**New evidence, and it narrows the fork to one option.** Archiving 00409 broke
two inbound links in Plan 00408 — one in `PLAN.md`, one in a `JOURNAL/`
day-file. Repointing the `PLAN.md` one was uneventful. Repointing the JOURNAL
one tripped `journal-append-only`, because a journal is append-only and a
repoint is by definition a rewrite of an earlier entry. Leaving it dead tripped
`pointer-resolves` at BLOCK. Both were observed as real handler output, in that
order, rather than reasoned about.

So the two rules genuinely contradict each other on a journal link, and no
archival procedure can satisfy both: **"repoint outbound links at archival
time" is not a remedy a JOURNAL can accept.** That leaves teaching the resolver
that a plan may have moved to `Completed/` as the only option which fixes the
class without rewriting an append-only record — and it is independently the
better guard. The fork this ledger recorded as open is closed by the
constraint, not by preference.

### N3 — the two plan-close gates are mutually exclusive on the legal close path

Closing a plan legitimately requires two changes to `PLAN.md`: a ticked
holding-area success criterion, and a terminal status header. Each gate refuses
the other's change when it arrives first:

- `plan_done_requires_holding_area` refuses the status flip while no
  holding-area criterion is present.
- `header-body-coherence` refuses a fully-ticked body under a non-terminal
  header — which is exactly what adding the criterion first produces.

So neither order works. Both gates are individually correct and neither is
wrong about the state it refuses; the defect is that no sequence of single
edits satisfies both, because each is judging an intermediate state that only
exists on the way to a valid one.

The escape is a single whole-file `Write` carrying both changes, so the content
is judged once in its final shape. That works, but nothing says so — an agent
discovers it by being blocked twice and inferring it. This happened three times
in one session (00409, 00417, and once more before that), each time costing two
blocked calls and a re-read of the file.

**Candidate remedies**, none chosen:

1. Have `header-body-coherence` ignore the holding-area criterion specifically
   when judging "the body claims completion" — it is a step TOWARDS closing,
   not a claim of being closed.
2. Have `plan_done_requires_holding_area` accept a status flip when the
   criterion is being added in the same write (it already sees whole content).
3. Document the whole-file `Write` as the sanctioned close move, and have
   whichever gate fires second say so in its remediation.

(3) is the cheapest and the weakest: it makes the workflow learnable without
making it sound. (1) looks most correct — the criterion is a precondition of
closing, so reading it as a completion claim is the actual category error.

### N4 — `cron_stop_enforcer` wedged this session on the day it merged

The handler blocked every Stop reporting the `issue-sdlc` job missing, while
`CronList` showed that job present at the declared schedule. Diagnosed from a
real `Stop` payload captured with `payload_capture`, not from inference:

- `schedule` arrived byte-identical: `23 * * * *`.
- the DECLARED prompt is 576 characters, paragraphs separated by one `\n`.
- the DELIVERED prompt is 580 characters — the same words, with blank lines
  inserted between most paragraphs.

Nothing truncated it (580 is far below the 1000-char cap), so the cap
normalisation the module was built around could not help. The prompt is
re-rendered somewhere between the advisory an agent READS and the `CronCreate`
that agent makes, and `cron_is_asserted` compared the two byte for byte.

**This is severe, not untidy, and it compounds.** The match can never succeed,
so the block is permanent; and an agent obeying the block's own instruction
creates a SECOND cron from the same re-rendered text, which also never
matches, and which then costs an hourly model turn of its own. Following the
guidance makes it strictly worse. Any client project that declares a cron
would have hit this on first use.

**The evidence that fixed it also settled how to fix it.** The same capture
showed the three live crons disagreeing with EACH OTHER — the failsafe job
kept single newlines, the other two did not. Delivered whitespace is not a
stable property of the wire, so it cannot be part of an identity test.
Matching now normalises layout away (strip each line, drop blank lines) and
compares the WORDS; `schedule` stays an exact comparison, because that is a
five-field expression where any difference is a real one.

**The lesson worth keeping.** The module's docstring names three contract
constraints, each carefully established, and the code honours all three — the
defect is in a fourth nobody thought to ask about. Every constraint was about
what the WIRE does to a field. None was about what the round trip through a
rendered advisory and an agent's own retyping does to it, and that round trip
is the only way this field is ever populated. Reasoning about a delivery
mechanism is not the same as reasoning about a delivery PATH.

**It also argues the guard was too sharp for its first outing.** A handler
whose failure mode is "no stop is ever possible again" should not have shipped
straight to blocking. A warn-first period — the shape Plan 00418 was
deliberately given — would have surfaced this at zero cost.

### N5 — the supervisor's goal check reads `background_tasks` as live when they are finished

The ccy supervisor's stop-condition evaluation refused three consecutive
legitimate stops, each time citing "7 background_tasks with status 'running'"
and concluding work was in flight.

Nothing was in flight. Established four independent ways, none agreeing with
the field:

- `bin/hooks-daemon harvest-background`: `NO RUNAWAYS DETECTED` (twice, minutes
  apart).
- `ps`: zero `sleep`/`pytest`/`llm_qa` workers; **10 processes total** in the
  container, which is the daemon, its listeners and the probing shell.
- `ListAgents`: all 7 teammates `idle`, not running.
- The session's own notification history: all seven Bash background tasks had
  already delivered terminal notifications (five completed, two exit-144 from
  kills I issued deliberately).

So the field reports a task as `running` after it has finished. The count
matches the number of background tasks STARTED this session, which is the shape
of a list that is appended to and never reconciled on completion.

**The entries are IDLE TEAMMATES, not stale bash tasks, and that changes the
diagnosis.** The first version of this entry concluded no action available to
the agent could clear the flag. That was wrong, and it was wrong because the
claim was asserted rather than tested. The seven are in-process teammates that
had finished their work and gone idle; `TaskStop` on each terminated it
cleanly, and `ListAgents` then reported no agents at all. The flag cleared.

So the field is not lying about existence — those tasks were genuinely still
registered. It is conflating **idle** with **running**. `ListAgents` reports
the distinction correctly and the goal check does not consume it.

**Why it still matters.** An agent that spawns teammates and harvests all their
work is left with registered idle teammates and no prompt to reap them. Nothing
in the worktree or dispatch guidance says a teammate must be `TaskStop`ped once
its branch is merged — the worktree reap is documented, the teammate reap is
not. So the natural end state of a correct parallel workflow is a session that
cannot satisfy its own stop condition, which took four refused stops to
discover here.

**Two candidate remedies**, neither chosen:

1. Have the goal check treat `idle` as not-in-flight, which is what
   `ListAgents` already reports and what the words mean.
2. Document teammate reaping as the counterpart to `worktree-reap`, so the
   registered set empties as work completes rather than accumulating for the
   life of the session.

(1) is the fix; (2) is worth doing anyway, because an idle teammate holds
context anyone can still message by name.

**The lesson is mine, not the tool's.** I asserted "no action available to the
agent can clear this" across three turns and then found the action on the
fourth by trying it. Re-verifying the same four read-only checks felt like
diligence and was not — the untested claim was the one load-bearing statement
in the entry, and it was the one I never checked.

Worth pairing with N4: two guards in one evening able to block a stop on a
false positive. But N4 was a genuine defect in a shipped comparison, and this
is a reporting mismatch plus a missing convention, so they want different
fixes.

