# Plan 00228: prose guard for text matching handlers

**Status**: Not Started
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

- Changing safety-class handlers. See Decision 1 — their prose matching is
  DELIBERATE and CLAUDE.md forbids removing it
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

- [ ] ⬜ **Task 1.1**: Decide how scope is expressed (Decision 1). Prefer the
  priority bands `CLAUDE.md` already documents (10–20 safety, 25–35 quality,
  36–55 workflow) over a hand-listed set, which would drift
- [ ] ⬜ **Task 1.2**: A fixture of non-executing text that names guardrail
  vocabulary — English sentences about the daemon, and literals inside quoted
  heredocs. Assert no in-scope handler denies. Include an EXEMPTIONS map with a
  stated reason per entry, following `test_pseudo_event_restart_safety.py`, so a
  legitimate firing is recorded rather than silently tolerated
- [ ] ⬜ **Task 1.3**: Vacuity and teeth. The fixture must be non-empty, the
  in-scope handler set must be non-empty, and an inverse test must prove the
  guard fails when a handler really does over-match. A guard that cannot fail is
  the thing this plan exists to replace

### Phase 2: Fix what the guard surfaces

- [ ] ⬜ **Task 2.1**: The quoted-heredoc instance — widen `pipe_blocker`'s
  existing quoted-delimiter reasoning from the one git-message shape to the
  general case
- [ ] ⬜ **Task 2.2**: Triage anything else the guard surfaces. Each is either
  fixed or recorded as an exemption WITH its reason; neither silently ignored
- [ ] ⬜ **Task 2.3**: Full QA + daemon restart + dogfood the reproduction above

## Success Criteria

- [ ] The reproduction in this plan runs instead of being denied
- [ ] A genuine truncating pipe on an expensive producer is still denied,
  asserted directly rather than inferred
- [ ] `destructive_git` still matches a dangerous command embedded in a string —
  asserted explicitly, because the acceptance suite depends on it and this plan
  must not quietly weaken it
- [ ] The guard fails when a handler over-matches (proven, not assumed)
- [ ] All QA passing; daemon restart verified RUNNING; dogfooded live

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
