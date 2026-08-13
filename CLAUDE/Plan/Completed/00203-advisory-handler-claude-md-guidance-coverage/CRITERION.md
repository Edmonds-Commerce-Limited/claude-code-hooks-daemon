# When does a handler earn a section in the resident `CLAUDE.md`?

Supporting document for Plan 00203, Task 1.1. Derived from what the codebase
already does, not invented — every test below is stated with the covered and
uncovered handlers that demonstrate it.

## Why there has to be a bar at all

Measured on this project (2026-08-13):

| measure             | value                              |
| ------------------- | ---------------------------------- |
| `CLAUDE.md` total   | 106,910 chars                      |
| auto-injected block | 73,239 chars — **68% of the file** |
| sections            | 53                                 |
| mean section        | 1,381 chars (~345 tokens)          |
| cost per session    | ~18,300 tokens, every session      |

Two thirds of the resident instruction file is handler guidance, and it is
re-read in full on every session in every client project. A section is not
"free documentation" — it is a standing charge on every future session,
whether or not the handler ever fires. That is what the tests below are
rationing.

`get_claude_md()` is already `@abstractmethod` on `Handler`, so every one of
the 107 handler classes on disk implements it. Nothing can escape the
*method*. What escapes is the *reasoning*: `return None` satisfies the ABC in
five seconds and records nothing.

## The tests

Apply in order. The first YES earns a section; reaching the end means `None`.

### Test 1 — Can this handler DENY a tool call?

A denial is not a free message. The turn is spent, and Claude Code cancels
every sibling tool call batched with the denied one, so an `Edit` issued
alongside a blocked `Bash` is silently lost. Guidance that prevents one
denial has already paid for itself many times.

**YES ⇒ earns a section.**

- Demonstrated by: `destructive_git`, `sed_blocker`, `pipe_blocker`,
  `qa_suppression` — all blocking, all covered.
- Live evidence, this session: `post_tool_use/lint_on_edit` denied a Python
  write over one unsorted import block. It has **no** resident section, so the
  denial was the first notice. Cost: a full round trip on a rule that one
  sentence would have prevented.

### Test 2 — Is the advice already too late for the call it fires on?

An advisory handler allows the action. The question is whether the agent can
still act on what it just read.

Too late ⇒ the choice being advised about is already baked into the allowed
call, so following the advice means redoing work.
In time ⇒ the advice governs what happens next, and arrives before it.

**TOO LATE ⇒ earns a section.**

- `agent_isolation_advisor` (covered): fires as the Agent is spawned; the
  `isolation` argument is already set. Reading it afterwards cannot un-spawn
  the agent.
- `plan_number_helper` (covered): fires on the folder-scan the agent should
  never have run. The right way (`mkplan.bash`) has to be known first.
- `daemon_restart_verifier` (covered): fires on `git commit`, advising a
  restart that should have happened before it.

**IN TIME ⇒ does not earn a section.**

- `task_tdd_advisor` (None, correct): fires as a Task agent is spawned, and
  its ~1,400-char fire-time message states the whole RED/GREEN/REFACTOR cycle
  the agent is about to perform. The advice precedes the work it governs. A
  resident copy would pre-announce a message that already arrives complete and
  on time.
- `bash_error_detector` (None, correct): reports errors in output that has
  just been read. Nothing precedes it.
- `git_context_injector` (None, correct): the injected text *is* the content;
  there is nothing to say about it in advance.

### Test 3 — Is it a standing policy rather than a one-shot correction?

Some advice has to be held across many later decisions. A single fire-time
delivery decays; the resident copy is what keeps it in force.

**YES ⇒ earns a section.**

- `recovery_cron_advisor` (covered): "never treat the recovery cron as a
  heartbeat" governs pacing for the rest of the session, not the one edit
  that triggered it.
- `background_process_tracker` (covered): the watchdog/harvest protocol
  outlives the command that backgrounded a process.
- `standing_authorisations`, `idle_housekeeping_advisory` (covered): both are
  policy by definition.

### Test 4 — Would a reader who already has the fire-time message *and the rest of the block* learn anything?

The final filter, and it overrides the others. If the section would restate
the fire-time message, the message is the better home — it is delivered only
when relevant. If it would restate a section another handler already
contributes, it is worse than duplication: the same fact is now billed twice
to every session, and the two copies drift apart independently.

**NO ⇒ does not earn a section**, even if an earlier test said yes.

- `git_hooks_executable_fixer` (covered) passes this: the fire-time note says
  which hooks were fixed; the section explains that the daemon changes file
  permissions on your behalf at all, which the note never says.
- `web_search_year` (None) fails on the message: it already names the current
  year, the offending query and three alternatives.
- `plan_completion_advisor` (None) fails on the block: its three steps are
  already resident under `plan_qa_commit_gate`, whose `terminal-state-atomic`
  invariant states the same requirement and enforces it.

## Handlers exempt by kind, not by test

Three groups never reach the tests, because they emit nothing an agent acts on:

| kind                     | count | examples                                                |
| ------------------------ | ----- | ------------------------------------------------------- |
| status-line renderers    | 14    | `git_branch`, `usage_tracking`, `model_context`         |
| loggers / lifecycle      | ~8    | `notification_logger`, `cleanup`, `transcript_archiver` |
| `hello_world` test stubs | 11    | one per event type                                      |

## Verdicts — the six PreToolUse advisories from the v3.52.0 audit

| handler                   | verdict | test | reason                                                                                                                 |
| ------------------------- | ------- | ---- | ---------------------------------------------------------------------------------------------------------------------- |
| `task_tdd_advisor`        | None    | 2    | Advice precedes the work it governs; its ~1,400-char fire-time message is complete and in time                         |
| `plan_completion_advisor` | None    | 4    | Its three steps are already resident under `plan_qa_commit_gate` (`terminal-state-atomic`) — a second copy would drift |
| `daemon_docs_guard`       | None    | 4    | One sentence at fire time ("read project docs, not daemon internals") says all of it                                   |
| `global_npm_advisor`      | None    | 4    | Never denies; the fire-time note is the whole advice                                                                   |
| `web_search_year`         | None    | 4    | Fire-time message already carries the year, the query and the alternatives                                             |
| `british_english`         | None    | 4    | Names the exact spelling and its replacement at fire time; a section cannot pre-empt every word                        |

**All six are correctly `None`.** The v3.52.0 audit's six findings needed
recording, not fixing — which is the finding that matters, because the same
audit missed both handlers that *do* have a real gap.

## The two real gaps, found by the criterion rather than by the audit

### `post_tool_use/lint_on_edit` — EARNS, Test 1

It DENIES writes, it fires on edits to source files in nine languages, and
v3.52.0 made it actually run where it had previously been silently inert — so
its denial rate rose precisely when no client had ever been told it exists.

Live evidence: it denied a Python write during this very plan's work, over a
single unsorted import block, with the denial as first notice.

### `stop/hedging_language_detector` — EARNS, Test 3

Its twin `stop/dismissive_language_detector` is covered. Both are
non-terminal Stop-time advisories that scan the last assistant message for
phrase families and inject a correction. No test separates them.

Test 3 settles which of the two is wrong: both are standing behavioural norms
("verify instead of guessing", "don't deflect work") that apply to every
future message. A Stop-time advisory is inherently reactive — it can only ever
arrive *after* the message that broke the norm — so a resident section is the
only form in which either can be preventive. `hedging_language_detector` is
the one that is wrong.

## Why the audit missed both

The v3.52.0 gate scanned **PreToolUse advisory** handlers. One real gap is a
**PostToolUse blocking** handler; the other is a **Stop** handler whose defect
is only visible by comparison with a sibling. Neither axis was in the scan.
That is the DBF case for Task 3.1: the replacement gate must enumerate every
handler and force a reasoned verdict, not sample one event type.
