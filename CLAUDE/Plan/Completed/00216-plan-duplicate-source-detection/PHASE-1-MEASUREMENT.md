# Plan 00216 Phase 1: measured signal quality

Measured over the whole plan tree: **215 `PLAN.md` files, 44 non-terminal,
168 terminal.** Method follows Plan 00214 — run the candidate rule over real
data and inspect every hit by hand BEFORE writing the check.

## Signal A — GitHub issue citations

Two spellings exist, and they behave completely differently.

### A1: the reliable spelling, `**GitHub Issue**: #N`

| measure                                 | value |
| --------------------------------------- | ----- |
| plans carrying the header               | 11    |
| distinct issues referenced              | 11    |
| issues referenced by more than one plan | **0** |
| non-terminal plans carrying the header  | 1     |

Every issue is cited by exactly one plan. Ten of the eleven plans are
Complete; only 00129 (issue #33) is live. **The check has nothing to detect
in this repository, and no dogfooding surface** — it could ship only as
untested-in-anger code, which this project's own standards treat as a
liability rather than a feature.

### A2: the loose spelling, a bare `#N`

35 plans match. Inspected by hand, **34 of 35 are false positives** and they
are not marginal — they are ordinary technical prose:

```
resolver #1 (install-time bash)          ← ordinal
**Review #2** returned NO-GO as written  ← ordinal
### Bug #3: injected compact did not…    ← ordinal
Confirmed Truths #1–#3, plus the…        ← intra-plan cross-reference
the #1 correctness risk                  ← English idiom
```

Only 00022's `**GitHub Issue**: #11` is a real citation. A rule using this
spelling would fire on `#1` and `#2` constantly, and the five "shared issue"
pairs it produced (#1, #2, #3, #4, #11) are **all** artefacts of the above.

## Signal B — supporting-document citations

115 plans name at least one `UPPERCASE.md` document. Five documents are named
by more than one non-terminal plan, and every one is a false positive:

| document                 | live plans citing it | why it is noise                          |
| ------------------------ | -------------------- | ---------------------------------------- |
| `HOOKS-DAEMON.md`        | 10                   | project-wide generated config doc        |
| `RELEASING.md`           | 9                    | project-wide process doc                 |
| `YY-MM-DD.md`            | 6                    | the literal journal-template placeholder |
| `CONTRIBUTING.md`        | 2                    | project-wide process doc                 |
| `RESEARCH-2026-02-23.md` | 2                    | see below — a CORRECT citation           |

The last is the instructive one. Plan 00106 cites Plan 00032's research
document as prior art:

```
| `CLAUDE/Plan/00032-.../RESEARCH-2026-02-23.md` | 96-100, 148 | Prior daemon r…
```

That is exactly the behaviour the plan system wants — a later plan grounding
itself in earlier findings. A duplicate-detector that flags it is punishing
good practice, and this is the single strongest hit the signal produced.

## The decisive result: the motivating pair

Plan 00216 exists because Plan 00213 duplicated Plan 00199. Measured:

| plan  | status     | issues cited | docs cited                                                        |
| ----- | ---------- | ------------ | ----------------------------------------------------------------- |
| 00199 | Superseded | **none**     | PROPOSAL.md, PROPOSAL-ASSESSMENT.md, SUPERSEDED.md, YY-MM-DD.md   |
| 00213 | Complete   | **none**     | PROPOSAL.md, PROPOSAL-ASSESSMENT.md, SUPERSEDED.md, EVALUATION.md |

- **Shared GitHub issues: NONE.** The narrowed issue-only signal would not
  have caught the case that motivated this plan.
- Shared documents: four — but `SUPPORTING`/`YY-MM-DD.md` are scaffold
  artefacts, and `PROPOSAL.md` / `PROPOSAL-ASSESSMENT.md` are **generic
  filenames**. They do not identify the same proposal; they identify that both
  folders contain a file conventionally named `PROPOSAL.md`. Any two unrelated
  proposal plans would collide identically.

## Conclusion

The duplication between 00199 and 00213 was **semantic** — two plans about
"planlib tooling in the daemon" — and no literal citation distinguishes it
from two unrelated plans that each happen to carry a `PROPOSAL.md`. A
deterministic citation rule cannot see the thing that made them duplicates.

The narrowing to GitHub issues does not rescue it: it is the most reliable
signal available (34/35 precision failure disappears), but it has **zero
matches to find here** and would have missed the motivating case anyway. It
is precise and useless in this tree.

**Recommendation: cancel the deterministic check.** The remedy for a semantic
duplicate is a semantic reader, which is the sub-agent/skill route — recorded
in `PLAN.md` under Technical Decisions.
