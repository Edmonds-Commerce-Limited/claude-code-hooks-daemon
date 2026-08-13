# Plan 00227: plan number helper matches text not commands

**Status**: Complete
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

   **Corrected during Phase 1: this one is LATENT, not live.** The original
   write-up above implied all three defects were measured. Probing each shape
   showed the alternation command is allowed because *no rule matches it*, not
   because the carve-out recognises it — and the carve-out only applies when the
   command is not also extracting a single highest value, which is very nearly
   the sort-and-truncate rule's own trigger. So no currently-reachable denial
   depends on it. Fixed and guarded anyway, because a future rule could make it
   live silently; recorded as latent so the plan does not overstate its evidence.

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

- [x] ✅ **Task 1.1**: 11 tests — the four measured cases, four genuine-discovery
  cases that must still be denied, and two direct assertions on the
  archive-coverage helper. One of the four initially passed VACUOUSLY and was
  rewritten to assert the helper directly (see Root cause, defect 2)
- [x] ✅ **Task 1.2**: Measured, and the answer is NO. `validate_plan_number`
  anchors on a syntactic construct — a `file_path` parameter, or the literal
  `mkdir` verb — rather than co-occurrence, and already skips heredocs. Probed
  live: prose naming the plan dir, and prose naming a specific plan folder, both
  pass. The single shape that fires is prose quoting a COMPLETE literal
  `mkdir CLAUDE/Plan/NNNNN-x`, and that is judged correct rather than a defect:
  the handler is advisory, and prose instructing someone to run a
  wrong-numbered `mkdir` is precisely what it exists to flag. Left unchanged

### Phase 2: Decide and implement

- [x] ✅ **Task 2.1**: Decision 1 — blank shell LITERALS, scoped to the two rules
  that misread them. The global version broke three existing tests, which is
  what proved the scoping necessary rather than merely tidy
- [x] ✅ **Task 2.2**: `_sweeps_the_plan_directory()` — the reduction must
  consume a listing of the directory, and a reference naming one specific plan
  no longer arms the rule
- [x] ✅ **Task 2.3**: carve-out admits a regex alternation naming the archives
- [x] ✅ **Task 2.4**: glob rule reads the literal-blanked copy
- [x] ✅ **Task 2.5**: docstring corrected; `HandlerTag.ADVISORY` KEPT, with the
  reason recorded (Decision 2) — the tag describes the response's content, not
  its force
- [x] ✅ **Task 2.6**: QA 20/20, 12,564 tests, 95.3% coverage; daemon restarted
  RUNNING and all four measured commands dogfooded live against it. The first
  QA run came back 19/20 on a transient format failure while its task
  notification reported success — read the artifact, fixed, re-ran the whole
  gate rather than accepting a green retry

### Phase 3: Make the class detectable (DBF)

- [x] ✅ **Task 3.1**: Decided (Decision 3), and the decision overturned the
  obvious version of the guard. "No handler fires on prose" would demand a
  regression in the safety layer, because `destructive_git` matches prose
  DELIBERATELY and CLAUDE.md forbids changing it. The guard must be scoped by
  cost-of-a-miss, expressed through the documented priority bands. Building it
  needs a per-handler notion of trigger vocabulary that does not exist yet, so
  it is carried forward as a named follow-up — explicitly not left as a verdict,
  which is the mistake this plan exists to correct

## Technical Decisions

### Decision 1: Blank shell LITERALS, and only for the rules that misread them

**Context**: the separating signal between a command that scans the plan
directory and text that merely names it.

**Signal chosen**: what the shell will EXECUTE. A single-quoted span is fully
literal, so it can never be the discovery idiom; a double-quoted span is
literal *unless* it contains a command substitution, which really does run.
Implemented as `utils.quoted_spans.blank_shell_literal_spans()`, a sibling of
Plan 00225's `blank_quoted_spans()` rather than a reuse of it.

**Why a sibling and not a reuse**: Plan 00225 deliberately excludes single
quotes, because an apostrophe in an ordinary contraction reads as an opening
quote. That hazard is a property of PROSE. In a shell command single quotes are
the strongest quoting there is, so the exclusion inverts — exactly the
"re-decide, do not inherit" note this plan was filed with.

**One left-to-right scan, not two regex passes.** Two independent passes
mis-pair an apostrophe sitting inside a double-quoted span. Tracking quote state
is what a shell itself does.

**Scoped to two rules, NOT applied globally — and this was forced by
evidence.** The first implementation blanked literals for every rule and broke
three existing tests. This handler inspects quoted arguments *on purpose*
elsewhere: the numeric grep pattern in `ls CLAUDE/Plan | grep '[0-9]'` is the
signal for one rule, and `-name "00036-*"` is what distinguishes a targeted find
from a sweep. Blanking those blinded rules that were working correctly.

So the exemption is applied where a misread costs a FALSE POSITIVE (the
echo/printf glob rule, the sort-and-truncate rule) and withheld where the
literal IS the signal. This is Plan 00225's Decision 2 in a new setting: place
the exemption by consequence-of-a-miss, never by uniformity.

**Second fix, independent of quoting**: the journal case
`git ls-files CLAUDE/Plan/00163-x/JOURNAL | sort | tail -1` has no quotes at
all, so blanking cannot help it. It is a real command that legitimately sorts
and truncates — but over ONE named plan. `_sweeps_the_plan_directory()` now
requires a plan-dir reference that is not a specific plan folder (two or more
literal digits). The discovery globs `0*` and `[0-9]*` carry at most one literal
digit, so the real idiom still arms the rule.

**Date**: 2026-08-13

### Decision 2: The docstring was the bug a reader would hit second

**Context**: the module docstring asserted the handler was non-blocking and
advisory-only, while it is `terminal=True` and issues hard denials. The
`HandlerTag.ADVISORY` tag says the same thing to the generated handler table.

**Decision**: correct the docstring; KEEP the tag. The tag describes the CONTENT
of the response — guidance rather than a safety veto — which is accurate and is
how sibling handlers use it. What was wrong was reading it as a statement about
FORCE. The docstring now says so explicitly, because the failure mode is a
reader who cannot explain a denial they just received and concludes the daemon
is broken.

**Not restated as history**: the corrected docstring describes current behaviour
only; what it previously claimed lives in git and in this plan.

**Date**: 2026-08-13

### Decision 3: A prose guard must be scoped to WORKFLOW handlers, never safety ones

**Context**: Task 3.1. The obvious DBF fix is a shared fixture of innocuous
English sentences that merely NAME each handler's trigger vocabulary, asserted
to produce no denial. Plans 00222, 00225 and 00227 would all have been caught by
one such fixture, and 00138's audit would have been unable to clear rule #4 by
reasoning alone.

**The obvious version of that guard is WRONG, and it is important to say why.**
`destructive_git` matches its patterns in prose *deliberately*. CLAUDE.md states
this explicitly and forbids "fixing" it: the same full-command-string matching
is what lets the acceptance suite verify blocking handlers by embedding a
dangerous command inside a string. A fixture asserting "no handler fires on
prose" would therefore demand a regression in the safety layer.

**What separates the two groups is the cost of a miss — the same test Plan
00225 used to decide where its exemption belonged:**

| handler class                             | over-block costs | under-block costs       | prose matching |
| ----------------------------------------- | ---------------- | ----------------------- | -------------- |
| safety (`destructive_git`, `sed_blocker`) | one retry        | unrecoverable data loss | **deliberate** |
| workflow (`plan_number_helper`)           | a blocked agent  | a wrong plan number     | a bug          |
| advisory (language detectors)             | noise            | a missed advisory line  | a bug          |

**Decision**: scope the guard to workflow- and advisory-class handlers, and
express that scope through the priority bands `CLAUDE.md` already documents
(10–20 safety, 25–35 quality, 36–55 workflow) rather than a hand-listed set that
would drift. Safety handlers are exempt BY DESIGN, and the exemption must carry
that reason inline so nobody later "fixes" the gap.

**Not implemented in this plan.** The scoping rule above is the hard part and is
now settled; building it needs a per-handler notion of "trigger vocabulary" that
does not exist yet, and inventing one under this plan would exceed its scope.
Carried forward as a named follow-up rather than silently dropped — the whole
reason this plan exists is that Plan 00138 recorded a verdict where a test was
needed.

**Date**: 2026-08-13

## Success Criteria

- [x] All four measured commands are allowed — re-run live against the restarted
  daemon, not merely asserted in unit tests
- [x] A genuine discovery idiom that sorts a plan-dir listing and takes the last
  entry is still denied, asserted directly rather than inferred. This is the
  criterion that makes the one above mean anything: a fix that simply disabled
  the handler would satisfy all four allowances and fail only here
- [x] The deny reason never claims a command misses the archive dirs when that
  command demonstrably reaches them — guarded by a direct assertion on the
  carve-out plus an inverse test, after the first version passed vacuously
- [x] The docstring and the handler's actual behaviour agree
- [x] All QA passing (20/20, 12,564 tests, 95.3% coverage); daemon restart
  verified RUNNING; dogfooded live

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
