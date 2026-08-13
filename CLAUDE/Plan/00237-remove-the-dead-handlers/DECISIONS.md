# Plan 00237 — Technical Decisions

Supporting document for [PLAN.md](PLAN.md). Decisions and their reasoning live
here rather than in the plan body, so the plan stays lean enough to be read in
full every session while the reasoning stays available on demand.

## Decision 1: an event with no handlers keeps its config section

**Context**: removing `cleanup` emptied SessionEnd, removing
`notification_logger` emptied Notification, and removing both SubagentStop
handlers emptied that too. A dogfooding guard (`test_config_has_all_event_types`)
failed on the first of these.

**Options**: drop the event from the expected set, or keep an empty section.

**Decision**: keep `session_end: {}`, `notification: {}`, `subagent_stop: {}`.
All three events remain registered and dispatchable — probed live against the
running daemon, each returns `{}` on a valid payload — they simply ship no
handlers today. Dropping them from the expected set would weaken an invariant
to make a symptom go away, and would leave a project-level handler for those
events with no documented place to live. An empty section also keeps "no
handlers" distinguishable from "event not supported".

## Decision 2: six handlers retired before the registry existed were still rejected

**Context**: the manifest/registry guard added in Task 1.7 failed on its first
run, naming `eslint_disable`, `python_qa_suppression_blocker`,
`php_qa_suppression_blocker`, `go_qa_suppression_blocker` (all v2.9.0) and
`validate_sitemap`, `remind_validator` (v2.11.0).

Verified rather than assumed: a config naming any of the six was still REJECTED
by `ConfigValidator.validate_and_raise` today. `RETIRED_HANDLERS` arrived in
Plan 00233, so every handler removed before it had its documented removal on one
side and nothing on the other — an unedited v2.x config has been tipping client
daemons into DEGRADED MODE for every release since v2.9.0, over removals we
performed deliberately.

**Decision**: add all six to the registry. Not scope creep from this plan's
remit — the registry IS this plan's mechanism, and the bug is the exact failure
mode the plan exists to prevent. It was found by the guard, not by hand, which
is the argument for building the guard first.

## Decision 3: a staged manifest not matching `v*.yaml` is silently stranded

**Context**: `UNRELEASED/config-changes/` held `transcript-archiver-removal.yaml`.
`RELEASING.md` Step 6 moves `UNRELEASED/config-changes/v*.yaml`, so that file
would never have been moved — Plan 00233's entire client-facing removal note was
set to sit in staging forever, with no error at any point to say so.

**Decision**: merge its content into `v3.53.0.yaml` (alongside this plan's
removals), delete the mis-named file, and add a guard asserting every staged
`*.yaml` also matches `v*.yaml`. The filename is the contract, and nothing else
enforced it.

## Decision 4: `bash_error_detector` is removed, not narrowed

**Context**: Task 2.5 was written as an open question — REMOVE, or narrow the
keyword list and rate-limit it?

**Evidence** (verdict log, retained window, 606 behavioural records): 274 fires,
45.2% of ALL behavioural handler activity, 2.7x the next handler, and
`allow=274` — it never restricted anything. The next most active handler,
`lint_on_edit`, denies 13 times out of 103, which is work being done.

**Decision**: REMOVE. Narrowing and rate-limiting would reduce the VOLUME of an
advisory whose content is "review the output you just requested and can see" —
but volume is not the defect. A command's exit status and stderr are already in
front of the agent, so there is no smaller version of this handler that adds
information. Corroborated first-hand throughout this plan's own execution: it
fired on `git status`, on every `grep` whose output contained the substring
"error", and on the very command that produced the measurement above.

## Decision 5: Phase 3 is a dependency inversion, not a deletion

**Context**: Plan 00236 established that `hedging_language_detector` and
`dismissive_language_detector` are unreachable on an ordinary Stop, while their
`nitpick` twins run. The obvious move is to delete the Stop pair.

Checking what each leg actually owns inverted the picture three times over:

| Asset                      | Stop leg (shadowed) | nitpick leg (runs) |
| -------------------------- | ------------------- | ------------------ |
| `get_claude_md()` guidance | full section        | `None`             |
| Compiled pattern constants | defines them        | imports them       |
| Fires on an ordinary Stop  | no                  | yes                |

Each nitpick module opens with
`from claude_code_hooks_daemon.handlers.stop.<detector> import ...`, under a
comment naming the Stop handler the "single source of truth".

**Decision**: move the pattern constants and the `get_claude_md()` bodies into
the nitpick modules first, so the running code owns its own definitions, then
delete the Stop modules. Deleting first would break the working detectors at
import time.

**Rejected**: re-prioritising the Stop pair below 10. That band is the safety
range, and putting an advisory ahead of a terminal safety handler to win a race
is the wrong fix for the wrong problem.

**Worth naming**: "which one runs" and "which one is authoritative" had drifted
completely apart, and nothing in the type system or the test suite could see it
— both modules import cleanly and both are unit-tested in isolation. It took a
live chain trace to notice at all.
