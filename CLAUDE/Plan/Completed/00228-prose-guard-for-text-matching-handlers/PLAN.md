# Plan 00228: prose guard for text matching handlers

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded (TDD)

## Overview

One defect has now recurred four times: a handler matches text that merely
NAMES its trigger vocabulary, instead of a command that does the thing. Each
instance was found the same way — an agent hit it mid-task — and each was fixed
in isolation, in the handler where it surfaced.

Fixing the fourth instance the same way would be the exact failure Core
Standard 15 names: a defect fixed by hand recurs, a defect fixed by making the
guard see it cannot. So this plan builds the GUARD first. The fourth instance
is then expected to fall out of it as a failing test, and is fixed second.

## The four instances

| plan  | handler                    | text read as a command                                      |
| ----- | -------------------------- | ----------------------------------------------------------- |
| 00222 | `pipe_blocker`             | journal prose containing a truncating pipe                  |
| 00225 | dismissive / hedging       | a phrase MENTIONED while acknowledging, not USED to deflect |
| 00227 | `plan_number_helper`       | a plain `echo` of an English sentence                       |
| —     | `pipe_blocker` (this plan) | a Python string literal inside a quoted heredoc             |

Nothing in the suite asks the question that would have caught any of them.
Worse, Plan 00138 was written to fix false positives in `plan_number_helper`
and explicitly cleared the rule that later produced instance three, reasoning
about which command SHAPES satisfy it and never asking whether non-command TEXT
could. The verdict was recorded where a test was needed.

## The fourth instance (reproduced minimally)

```bash
cat > untracked/_hd.py <<'PYEOF'
CASES = [("alternation", "ls CLAUDE/Plan | sort | tail -1")]
print(CASES[0][0])
PYEOF
```

Denied by `pipe_blocker`. The heredoc delimiter is QUOTED, so the shell expands
nothing and writes the body verbatim to a file; that pipe is never executed.

Two details worth keeping:

- The remediation offered is incoherent — it suggests whitelisting `^CASES\b`
  as if it were a command name, and prints a syntactically broken alternative.
  A wrong parse produces wrong advice, not just a wrong verdict.
- `pipe_blocker` ALREADY states the governing principle. Its guidance says the
  `"$(cat <<'EOF' ... EOF)"` idiom is exempt precisely because a QUOTED
  delimiter makes the body literal. The implementation binds that principle to
  one syntactic shape (a command substitution capturing `cat`, used as a git
  message value); a heredoc feeding an interpreter's stdin is the same
  principle and is not covered. Its other escape route — prose detection by
  function-word density — does not apply either, because a Python string
  literal is not prose.

So the fix is to let a principle the handler already holds cover the general
case, not to invent a new exemption.

## Goals

- A guard that fails when a workflow- or advisory-class handler denies text
  that merely names its trigger vocabulary
- The fourth instance fixed, with the guard as its failing test
- The guard's scope is explicit and reasoned, not a blanket assertion

## Non-Goals

- Changing the handlers that match text DELIBERATELY. See Decision 1 — they are
  named explicitly with reasons rather than inferred from a priority band, and
  CLAUDE.md forbids removing `destructive_git`'s string matching
- A shell parser. Plan 00222 and Plan 00227 both settled for targeted signals;
  the same standard applies
- Re-auditing the three already-fixed instances. They have their own regression
  tests; this guard is about the ones not yet found

## Context & Background

Plan 00227's Decision 3 established the scoping rule this plan implements, and
established it by rejecting the obvious version:

> "no handler fires on prose" would demand a regression in the safety layer,
> because `destructive_git` matches prose deliberately and CLAUDE.md forbids
> changing it — the acceptance suite embeds dangerous commands in strings to
> verify blocking handlers.

The separator is the cost of a miss, the same test Plan 00225 used to decide
where its exemption belonged:

| handler class                             | over-block costs | under-block costs       | prose matching |
| ----------------------------------------- | ---------------- | ----------------------- | -------------- |
| safety (`destructive_git`, `sed_blocker`) | one retry        | unrecoverable data loss | **deliberate** |
| workflow (`plan_number_helper`)           | a blocked agent  | a wrong plan number     | a bug          |
| advisory (language detectors)             | noise            | a missed advisory line  | a bug          |

## Tasks

### Phase 1: Build the guard

- [x] ✅ **Task 1.1**: Decided, and the answer REJECTS the mechanism this plan
  was filed proposing — see Decision 1. Priority bands do not express
  cost-of-a-miss and would exempt three of the four instances
- [x] ✅ **Task 1.2**: `tests/integration/test_handlers_do_not_match_prose.py` —
  5 fixture cases seeded from text that ACTUALLY provoked a denial here,
  handlers discovered rather than hardcoded, exemptions carrying a reason each.
  Scoped to the PreToolUse package after the first draft asked Stop handlers
  about a Bash payload (Decision 2)
- [x] ✅ **Task 1.3**: Vacuity and teeth — the fixture, the discovery and the
  in-scope set are each asserted non-empty; every exemption must name a real
  handler and state a reason; and an inverse test asserts `destructive_git`
  STILL denies a dangerous command embedded in a string, so this plan cannot
  quietly weaken the safety layer

### Phase 2: Fix what the guard surfaces

- [x] ✅ **Task 2.1**: `pipe_blocker._strip_quoted_heredoc_bodies()` blanks the
  body of a heredoc whose DELIMITER IS QUOTED, at both scan sites. An UNQUOTED
  `<<EOF` is deliberately left alone, because bash expands inside it and its
  body can genuinely run a command
- [x] ✅ **Task 2.2**: Two surfaced beyond the predicted one.
  `AutoContinueStopHandler` was a bug in the guard (fixed by event scoping);
  `GitStashHandler` is a DELIBERATE matcher whose behaviour existing tests
  specify — exempted with that reasoning rather than "fixed" (Decision 2)
- [x] ✅ **Task 2.3**: Daemon restarted RUNNING; the reproduction now writes
  the file instead of being denied, and a non-whitelisted producer piped to a
  truncating consumer is still denied
- [x] ✅ **Task 2.4**: Full QA surfaced seven `test_pipe_blocker_prose_ remediation.py` failures a narrower selection had missed. Fixtures retargeted
  onto unquoted heredocs (where the prose heuristic is still reachable, verified
  by probe), `TestQuotedDelimiterBodiesAreInert` added to pin the replacing
  behaviour, and the stale `get_claude_md()` guidance plus the now-unreachable
  `get_acceptance_tests()` premise both corrected — see Decision 3

## Technical Decisions

### Decision 1: Scope by explicit exemption, NOT by priority band

**Context**: this plan was filed proposing that scope be expressed through the
priority bands `CLAUDE.md` documents (10–20 safety, 25–35 quality, 36–55
workflow), on the reasoning that safety handlers match prose deliberately and
everything above them should not. Plan 00227's Decision 3 proposed the same.

**Measured before building, and it is wrong.** The actual priorities:

| handler              | priority | band    | instance  |
| -------------------- | -------- | ------- | --------- |
| `pipe_blocker`       | 15       | safety  | 00222, #4 |
| `nitpick_dismissive` | 10       | safety  | 00225     |
| `nitpick_hedging`    | 20       | safety  | 00225     |
| `plan_number_helper` | 30       | quality | 00227     |

A band-scoped guard would exempt **three of the four instances it exists to
catch**. The proposal was not merely imprecise; it was inverted for most of the
evidence.

**Why the proxy fails**: priority encodes DISPATCH ORDER, not consequence.
`pipe_blocker` runs at 15 so it short-circuits before expensive handlers get a
turn — a performance and precedence concern. Nothing about 15 says a miss is
unrecoverable. Reading a dispatch-order number as a severity classification is
the same category error as reading `HandlerTag.ADVISORY` as "cannot block"
(Plan 00227, Decision 2), in the same week.

**Decision**: invert the default. EVERY text-matching handler is in scope, and
the handlers that match text deliberately are named in an explicit exemption
map with a stated reason each — `destructive_git` and `sed_blocker` (CLAUDE.md
mandates their string matching, and the acceptance suite depends on it),
`security_antipattern` and `sensitive_content` (Plan 00225 Decision 2: a secret
or an exploit inside quotes is still a secret or an exploit).

**Why the inversion matters more than the tidiness**: with default-in-scope, a
NEWLY ADDED handler is covered automatically. Under band-scoping a new handler
placed at priority 15 would be silently exempt — which is exactly how this
class keeps escaping. A guard must fail closed for things nobody has thought
about yet.

**Date**: 2026-08-13

### Decision 2: A guard finding is a CANDIDATE, not a verdict

**Context**: on its first run the guard surfaced two handlers beyond the
predicted one. Both were instructive, and only one was a bug.

**`GitStashHandler` — surfaced, investigated, exempted.** Prose describing the
stash policy (`echo "this project blocks git stash because ..."`) is denied,
which looks exactly like the defect. I implemented the quoted-span fix for it —
and the existing suite failed:
`tests/unit/handlers/test_git_stash.py::test_matches_git_stash_in_echo_quotes`
asserts that `echo "git stash"` MUST be blocked, and
`test_blocks_all_creation_variants` repeats it.

That is the CLAUDE.md-prescribed mechanism by which the acceptance suite
verifies a blocking handler: embed the command in a string. The tests are the
specification. My "fix" would have broken acceptance testing while looking like
a false-positive repair, and the only thing that stopped it was running the
existing tests before believing my own diagnosis. Reverted, and recorded in the
exemption map with that reasoning.

**`AutoContinueStopHandler` — a bug in the GUARD, not the handler.** It was
reported against all five fixtures because the first draft fed a Bash
PreToolUse payload to every discovered handler, including Stop handlers. Asking
a Stop handler about a Bash tool call is a category error and its answer is
meaningless. The guard now restricts itself to the PreToolUse package.

**Decision**: the exemption map is the designed outcome for a surfaced-but-
legitimate handler, not an escape hatch to be embarrassed about. What the guard
must never permit is an UNEXPLAINED exemption, which is why a test asserts every
entry carries a reason and another asserts no entry names a handler that no
longer exists.

**Date**: 2026-08-13

### Decision 3: Retarget the Plan 00209 fixtures, do NOT weaken the fix

**Context**: the fix broke seven tests in
`test_pipe_blocker_prose_remediation.py`, all using the same vehicle — a
QUOTED heredoc — to put prose in front of the matcher. They were not in the
targeted selection I ran first; the full QA run is what surfaced them.

**This is the same shape as Decision 2 and the answer is the opposite**, so
the distinction matters more than either verdict. For `git_stash`, the tests
asserted a denial that CLAUDE.md MANDATES and the acceptance suite depends on
— the denial was the deliverable. Here the tests say the opposite in their own
words: the class is named `TestProseFalseTriggerGetsNoRemediationTemplate`, and
the docstring of the failing sanity test reads "the detection itself is correct
and out of scope per Non-Goals". Plan 00209 called the trigger FALSE and
explicitly DEFERRED the detection, shipping only the reason-shape fix. Its
deliverable was the reason, not the block.

So Plan 00228 delivers the half 00209 deferred, and the two plans compose. The
test evidence separating "specification" from "premise" is the plan's own
scoping language, not my reading of the code.

**Decision**: retarget every affected fixture from `<<'EOF'` to `<<EOF`, delete
no assertion, and add `TestQuotedDelimiterBodiesAreInert` pinning the behaviour
that REPLACED the old premise. Verified by probe first — an unquoted heredoc
still reaches the matcher and still yields the prose reason — so the retarget
keeps every 00209/00218 guarantee live rather than quietly parking it.

**Two consequences that would otherwise have shipped silently:**

- `get_claude_md()` still told users a heredoc body "can false-trigger this
  handler". Resident guidance that contradicts the handler is its own defect,
  so it now states the quoted/unquoted split and why the boundary is there.
- The handler's own `get_acceptance_tests()` carried a `<<'EOF'` case expecting
  DENY. That premise is now unreachable, so the next release's acceptance run
  would have failed on it — the exact failure Plan 00196 closed for acceptance
  tests generally. Retargeted to `<<EOF` with the reason recorded inline.

**Date**: 2026-08-13

## Success Criteria

- [x] The reproduction in this plan runs instead of being denied — dogfooded
  against the live daemon, the heredoc wrote its file
- [x] A genuine truncating pipe on an expensive producer is still denied,
  asserted directly rather than inferred —
  `test_unquoted_delimiter_with_substitution_is_still_denied` asserts DENY on
  `$(pytest | tail -1)` inside an unquoted heredoc AND that it gets the real
  remediation, not the prose reason; confirmed live as well
- [x] `destructive_git` still matches a dangerous command embedded in a string —
  `TestTheGuardHasTeeth::test_a_deliberate_text_matcher_really_does_fire_on_text`
- [x] The guard fails when a handler over-matches — proven empirically, not
  assumed: its first run failed on three handlers, one of which was the real
  `pipe_blocker` defect
- [x] All QA passing (20/20, 12578 tests, coverage 95.3%); daemon restart
  verified RUNNING; dogfooded live in both directions

## Risks & Mitigations

| Risk                                                            | Impact | Probability | Mitigation                                                                                                       |
| --------------------------------------------------------------- | ------ | ----------- | ---------------------------------------------------------------------------------------------------------------- |
| The guard weakens the safety layer                              | High   | Low         | Safety band exempt by design; an explicit test asserts `destructive_git` still matches a string-embedded command |
| The guard is brittle and gets disabled                          | High   | Medium      | Exemptions map with reasons, so a legitimate firing is recorded rather than forcing a blanket suppression        |
| The fixture is unrealistic, so it passes while real prose fails | Medium | Medium      | Seed it from text that ACTUALLY triggered denials in this repo, starting with the four instances above           |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00228-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed after the fourth instance of the class was hit live and reproduced
  minimally; the guard is built before the instance is fixed, per Core
  Standard 15
