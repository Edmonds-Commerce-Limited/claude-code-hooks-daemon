# Plan 00225: dismissive hedging detectors use mention false positive

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

The dismissive-language and hedging-language detectors match their trigger
phrases by plain substring. They therefore cannot distinguish a phrase being
**used** (deflecting: "that is out of scope") from one being **mentioned**
(acknowledging: "the hook flagged my 'out of scope' and it was right").

The advisory the detector emits says *"acknowledge and offer to fix instead of
deflecting"*. Naming the phrase is the natural way to acknowledge it — so
following the instruction re-triggers the advisory. The instruction is
unsatisfiable as written while the phrase is named.

This is the same failure class as Plan 00224: a guard that cries wolf gets
switched off. It is worth fixing for the same reason and no more — both
detectors are ADVISORY, so the harm is eroded signal, not a blocked tool call.
The fix should be proportionate to that.

## The evidence (measured 2026-08-13)

Probed `DismissiveLanguageNitpickHandler.handle()` directly. `matches()` only
gates on event shape, so the detection is entirely in `handle()`:

| message                                                       | fires | correct?           |
| ------------------------------------------------------------- | ----- | ------------------ |
| `That is out of scope for this change.`                       | yes   | ✅ genuine deflect |
| Acknowledging the advisory, quoting the phrase                | yes   | ❌ false positive  |
| `I called it out of scope; that was wrong, I will fix it ...` | yes   | ❌ false positive  |
| `The registry gate covers one entry today.`                   | no    | ✅                 |

Row 3 is the sharpest: that message does exactly what the advisory asks —
acknowledges AND commits to fixing — and is still flagged.

Both surfaces share one pattern set:
`handlers/stop/dismissive_language_detector.py` owns the lists and
`handlers/nitpick/dismissive_language.py` imports them, so a fix at the
matching layer covers both. `hedging_language` is built the same way.

## Goals

- A phrase that is MENTIONED rather than USED does not raise the advisory
- Genuine deflection still raises it, unchanged
- One fix covers both the Stop and nitpick surfaces (they share the patterns)

## Non-Goals

- Changing WHICH phrases either detector matches — the pattern lists stay as
  they are, exactly as Plan 00222 left `pipe_blocker`'s detection untouched
- Sentiment analysis, or any attempt to judge whether an acknowledgement is
  sincere
- Touching the Stop handler's `_last_advisory_key` dedupe state — Plan 00224
  Decision 2 classified it as a counter, so a restart costs one extra advisory

## Context & Background

Plan 00222 solved the structurally identical problem for `pipe_blocker`: agent
prose containing the literal characters `| tail` was treated as a command. Two
of its findings transfer directly:

1. **Detection was not changed** — only whether the verbose remediation
   template was built from what matched. Presentation adapted, matching did not.
2. **The signal must be linguistic, not superficial.** Its first attempt used
   segment length (>80 chars ⇒ prose) and that was recorded as "wrong in
   principle, not merely mistuned", because in this repository an 80-character
   command is ordinary. What worked was function-word density.

The lesson to carry over: pick a signal that actually separates the two cases,
and verify it against real examples of BOTH before trusting it.

## Tasks

### Phase 1: Reproduce

- [x] ✅ **Task 1.1**: Failing tests for the mention cases, plus a passing test
  for genuine deflection so a fix that merely disabled the detector cannot go
  green. 11 helper tests + handler tests on all four surfaces
- [x] ✅ **Task 1.2**: Confirmed by direct probe that the hedging detector has
  the identical defect, and that both Stop handlers share the nitpick pattern
  lists — one bug across four scan sites

### Phase 2: Decide and implement

- [x] ✅ **Task 2.1**: Option 1 chosen; options 2 and 3 rejected with reasons
  (Decision 1). Writing the cases out is what showed option 2 was unavailable
  rather than merely risky
- [x] ✅ **Task 2.2**: `utils/quoted_spans.blank_quoted_spans()` applied at all
  four scan sites; pattern lists untouched
- [x] ✅ **Task 2.3**: Daemon restarted RUNNING on the fixed code; full QA

### Phase 3: Make the class detectable (DBF)

- [x] ✅ **Task 3.1**: Surveyed the other content scanners. The answer is that
  the exemption must NOT be generalised — see Decision 2. `sensitive_content`
  and `security_antipattern` would gain a trivial bypass, because their
  miss-cost is a leaked secret or a shipped exploit rather than a missing
  advisory line

## Technical Decisions

### Decision 1: What separates a use from a mention

**Context**: The detector sees only the agent's message text.

**Options Considered**:

1. **Skip matches inside a quoted span** (single, double or backtick). High
   precision, mechanical, and it is exactly how the repo already treats shell
   quoting in `pipe_blocker` and git message values. Fixes the loop case, since
   quoting is how the advisory gets acknowledged. Does NOT fix row 3, which has
   no quotes.

2. **Detect a reporting or correction context** near the match — "the hook
   flagged", "I called it", "that was wrong". Fixes row 3 too, but risks false
   NEGATIVES: a genuine deflection can contain "I will fix", and the guard's
   whole value is catching deflection.

3. **Suppress when the message is plainly ABOUT the advisory** — it names the
   handler, the daemon, or the advisory itself. Narrower than option 2 and
   aimed squarely at the dogfooding loop.

4. **Do nothing.** The advisory is non-blocking, so the cost is one noisy line.

**Decision**: **Option 1 alone.** Options 2 and 3 are rejected, and option 2
was rejected for a reason that only became clear once the cases were written
out side by side.

**Why option 2 is not merely risky but unavailable**: the row-3 case is
genuinely ambiguous in English, not just hard to detect.

- `I called it out of scope because the release is tomorrow.` — a deflection
- `I called it out of scope; that was wrong.` — an acknowledgement

Identical up to the clause that follows. Any reporting-verb heuristic fires on
both or neither, so it cannot separate them; it can only trade noise for
silence. This plan's own risk table says silence is the worse failure, and the
handler's entire value is catching deflection.

**Why option 3 is rejected**: `The hook flagged the test failure, but that is out of scope.` names the daemon AND deflects. Suppressing on "is this message
about the advisory?" would silence exactly that.

**What option 1 costs, stated plainly**: row 3 still raises the advisory. The
loop is broken, because quoting is how the advisory gets acknowledged and
quoting is now exempt — but an unquoted mention is still flagged. That is
accepted, not overlooked.

**Implementation**: `utils/quoted_spans.blank_quoted_spans()`, applied at all
four scan sites (dismissive and hedging × Stop and nitpick). The pattern lists
are untouched, exactly as Plan 00222 left `pipe_blocker`'s detection alone and
changed only what it scanned.

**Single quotes are deliberately NOT mention markers**: an apostrophe inside an
ordinary word ("doesn't", "it's") reads as an opening quote, so pairing on them
would blank arbitrary spans of real sentences — and a blanked span is one the
detector can no longer see. `pipe_blocker` records the same constraint. Double
quotes and backticks only.

**Date**: 2026-08-13

### Decision 2: The exemption must NOT be generalised to every content scanner

**Context**: Task 3.1 — the defect class is "a scanner that cannot tell a
mentioned phrase from a used one". Several handlers scan agent-authored text,
so the obvious move is to apply `blank_quoted_spans` to all of them.

**That would be a security regression.** `sensitive_content` scans writes for
secret terms. A secret inside quotation marks is still a secret being written
to disk, and blanking quoted spans there would create a trivial bypass: quote
the term and the guard goes blind. The same holds for `security_antipattern`,
where a dangerous construct in a quoted string can still execute.

**What actually separates the two groups** is not the scanner but the
consequence of a miss:

| scanner group                          | a MISSED match costs             | quoted-span exemption |
| -------------------------------------- | -------------------------------- | --------------------- |
| language advisories (dismissive/hedge) | one advisory line not shown      | correct               |
| `sensitive_content`                    | a secret committed to a repo     | **never**             |
| `security_antipattern`                 | an exploitable construct shipped | **never**             |

**Decision**: apply the exemption only to the two language advisories. Recorded
so the next person who spots the duplication does not "helpfully" extend it.

**Adjacent, not fixed here**: `comment_changelog` has the same shape — it fired
twice during this plan's own implementation on comments that EXPLAIN a rule
rather than record history. Its miss-cost is advisory, so it is a legitimate
candidate, but its trigger is a phrasing pattern rather than a fixed phrase and
quoting is not how one writes an explanatory comment. Left alone deliberately;
noted so it is not rediscovered as new.

**Date**: 2026-08-13

## Success Criteria

- [x] A message that QUOTES a trigger phrase without deflecting raises no
  advisory. An unquoted mention still does — accepted, see Decision 1
- [x] A message that genuinely deflects still raises it, including when a
  quotation sits elsewhere in the same message
- [x] Both the Stop and nitpick surfaces are covered by one shared helper, each
  asserted directly rather than inferred from the other
- [x] All QA passing (20/20, 12,528 tests, 95.3% coverage); daemon restart
  verified RUNNING; dogfooded live — a message quoting both trigger phrases
  raised neither advisory, where the pre-fix code raised both

## Risks & Mitigations

| Risk                                                                | Impact | Probability | Mitigation                                                                                          |
| ------------------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------------------------- |
| An exemption lets genuine deflection through (false negative)       | High   | Medium      | Keep a deflection test in the suite; prefer the narrowest signal; treat silence as worse than noise |
| The signal is superficial and mistuned rather than actually correct | Medium | Medium      | Plan 00222 hit exactly this with its length heuristic; validate against real examples of both cases |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00225-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Found by dogfooding during Plan 00224 closure; evidence measured and recorded
  above before any fix was designed
