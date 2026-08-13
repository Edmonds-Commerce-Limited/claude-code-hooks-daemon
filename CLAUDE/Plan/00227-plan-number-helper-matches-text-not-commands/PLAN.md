# Plan 00227: plan number helper matches text not commands

**Status**: Not Started
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

`plan_number_helper` denies Bash commands that merely **mention** the plan
directory near certain tokens, rather than commands that actually **scan** it to
discover a plan number. It blocked four consecutive legitimate commands during
routine plan housekeeping, including one that only printed English prose.

The handler exists to stop a real problem — folder scans miss `Completed/` and
disagree across branches, so the git counter is authoritative. That purpose is
sound and is not in question here. What is wrong is the discrimination: it
cannot tell a command that performs the discovery idiom from text that merely
contains its vocabulary.

This is the third instance of one defect class in this repository, after Plan
00222 (`pipe_blocker` read prose containing a truncating pipe as a command) and
Plan 00225 (the language detectors read a MENTIONED phrase as a USED one). Both
established the technique; this plan applies it to the handler that predates
them.

## The evidence (measured 2026-08-13)

All four blocks below were real, hit while doing ordinary plan housekeeping.

| #   | command intent                                                 | why it matched                           |
| --- | -------------------------------------------------------------- | ---------------------------------------- |
| 1   | find the newest `JOURNAL/` day-file for five NAMED plans       | rule #4: dir + sort + truncation present |
| 2   | `find CLAUDE/Plan -maxdepth 1 -name '00163-*'` for known plans | rule #2, firing broadly as designed      |
| 3   | count plan folders per archive dir for a statistics recount    | glob rule: a grep REGEX `[0-9]`          |
| 4   | an `echo` of an ENGLISH SENTENCE describing the bug            | rule #4, on prose                        |

Case 4 is the sharpest and was reproduced deliberately: an `echo` of a plain
English sentence that happens to contain the plan directory name and the two
trigger words is blocked. That command touches no filesystem, lists nothing, and
cannot discover any plan number. The handler currently blocks an agent from
*writing about* the handler.

Case 3 carries an additional irony: the deny reason is *"This command won't find
all plans (misses subdirectories like Completed/)"*, and the command explicitly
enumerated `Completed/` and `Cancelled/`. The handler told the caller something
untrue about their own command — the exact outcome the existing carve-out at
`plan_number_helper.py:146` was written to prevent.

## Root cause — three defects, one cause

The cause is that every rule matches raw command TEXT, with no model of shell
structure (what is quoted, what is a regex, what is prose).

1. **Rule #4 is bare co-occurrence** (`plan_number_helper.py:215`). It requires
   only that the plan dir, the word `sort` and the word `tail` all appear
   somewhere in the command string. Nothing requires the truncation to operate
   on a listing of the plan directory, or requires the text to be a command.

2. **The reconciliation carve-out is too literal** (`:97`). It qualifies a
   command as archive-covering only if `[A-Za-z]` follows the plan dir directly,
   so an alternation naming both archive dirs — which demonstrably does cover
   them — fails to qualify because the next character is `(`.

3. **The glob rule cannot see quoting** (`:202`). A grep regex character class
   `[0-9]`, safely inside single quotes, is read as a shell glob metacharacter.

## Why it recurred — the part that matters

Plan 00138 ("Fix Plan-Number Handler False Positives") already fixed false
positives in this handler and **explicitly cleared rule #4**, in Decision 3
headed *"Patterns #1, #4, #5 are already narrow"*. Its stated reasoning was that
the rule requires both trigger words present alongside the plan dir, so a
specific-folder reference alone does not satisfy it.

That statement is true and the conclusion drawn from it is wrong. The audit
asked which COMMAND SHAPES satisfy the rule and answered correctly; it never
asked whether non-command TEXT could. So the rule was recorded as verified-safe,
with regression tests, and the class survived the plan written to remove it.

Plan 00138 predates Plans 00222 and 00225, which is where this repository
actually learned to ask that question. This plan is not a criticism of 00138 —
it is the later insight being carried back to a handler audited before the
insight existed.

## Goals

- Text that merely mentions the plan directory does not trigger the handler
- A genuine discovery idiom is still blocked, unchanged
- The archive-coverage carve-out recognises a command that genuinely reaches the
  archive dirs even when the path is expressed as a regex alternation
- The handler's own docstring stops contradicting its behaviour

## Non-Goals

- Removing or weakening the handler's purpose. Folder scans really do miss
  `Completed/` and really do disagree across branches; the git counter really is
  authoritative. Precision is the target, not permissiveness
- A full shell parser. Plan 00222 settled for a targeted signal and that was
  right; the same standard applies here
- Touching `validate_plan_number` (the sibling handler 00138 also fixed) unless
  the same defect is measured there

## Context & Background

The transferable finding from Plan 00222 is that the separating signal must be
**linguistic, not superficial**: its first attempt used segment length as a
prose proxy and that was recorded as *"wrong in principle, not merely
mistuned"*. Plan 00225 then produced reusable machinery —
`utils/quoted_spans.blank_quoted_spans()` — which blanks quoted spans and scans
a copy, leaving the detection patterns untouched.

Reuse that machinery rather than reinventing it. Note the limit Plan 00225
recorded: single quotes are deliberately NOT mention markers there, because an
apostrophe in an ordinary contraction reads as an opening quote. That constraint
was chosen for PROSE. Here the input is a shell command, where single quotes
really do quote — so the trade-off must be re-decided for this context rather
than inherited, and that re-decision belongs in a Technical Decision.

Also carry over Plan 00225's Decision 2: its exemption was safe **because a
missed match costs only an advisory line**. That reasoning must be re-derived
here rather than assumed. This handler DENIES, and a missed match costs a wrong
plan number — worse than a missed advisory, far cheaper than a leaked secret.

## Tasks

### Phase 1: Reproduce

- [ ] ⬜ **Task 1.1**: Failing tests for all four measured cases, plus passing
  tests for genuine discovery idioms so a fix that merely disables the handler
  cannot go green
- [ ] ⬜ **Task 1.2**: Check whether the sibling `validate_plan_number` carries
  the same text-vs-command confusion; measure before assuming either way

### Phase 2: Decide and implement

- [ ] ⬜ **Task 2.1**: Decide the separating signal (Decision 1), explicitly
  re-deciding the single-quote question for a shell-command context
- [ ] ⬜ **Task 2.2**: Fix rule #4 so it requires the truncation to consume a
  listing of the plan dir, not merely co-occur with a mention of it
- [ ] ⬜ **Task 2.3**: Widen the archive-coverage carve-out to recognise a
  genuine multi-archive reference
- [ ] ⬜ **Task 2.4**: Make the glob rule ignore quoted regex character classes
- [ ] ⬜ **Task 2.5**: Correct the module docstring, which claims the handler is
  non-blocking and advisory-only while it is `terminal=True` and issues hard
  denials. Decide whether `HandlerTag.ADVISORY` is also wrong, since the
  generated handler table reports this handler as ADVISORY
- [ ] ⬜ **Task 2.6**: Full QA + daemon restart verification

### Phase 3: Make the class detectable (DBF)

- [ ] ⬜ **Task 3.1**: The real DBF question is not "which other handlers have
  this bug" but "why did an audit clear it". Decide whether a shared guard can
  assert that a text-matching handler does not fire on prose — e.g. a fixture of
  innocuous English sentences that merely NAME each handler's trigger
  vocabulary, asserted to produce no denial. Plans 00222, 00225 and this one
  would all have been caught by that one fixture

## Technical Decisions

<!-- Decision 1 (the separating signal) is authored during Task 2.1, once the
     cases are written out. Plan 00225 found that writing the cases out was what
     revealed one option to be unavailable rather than merely risky. -->

## Success Criteria

- [ ] All four measured commands are allowed
- [ ] A genuine discovery idiom that sorts a plan-dir listing and takes the last
  entry is still denied, asserted directly rather than inferred
- [ ] The deny reason never claims a command misses the archive dirs when that
  command demonstrably reaches them
- [ ] The docstring and the handler's actual behaviour agree
- [ ] All QA passing; daemon restart verified RUNNING; dogfooded live

## Risks & Mitigations

| Risk                                                      | Impact | Probability | Mitigation                                                                                                    |
| --------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------------------------------- |
| A loosened rule lets the real discovery idiom through     | High   | Medium      | Keep an explicit discovery-idiom test; prefer the narrowest signal; treat a missed block as the worse failure |
| The fix is superficial and mistuned rather than correct   | Medium | Medium      | Plan 00222 hit exactly this with a length heuristic; validate against real examples of BOTH cases             |
| A third audit clears a rule the way 00138 cleared rule #4 | High   | Medium      | Task 3.1 — turn "does this fire on prose?" into a test rather than a question each auditor must think to ask  |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00227-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found by dogfooding during the Plan 00226 closure and the stale-plan sweep;
  all four blocks were real, and case 4 was reproduced deliberately afterwards
