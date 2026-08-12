# Hooks daemon feedback — the plan-size guidance has a missing third option

**Reporter**: agent session, client project (private repo), 2026-08-12
**Daemon version**: v3.51.0
**Severity**: **Medium-High** — not a crash, but the guidance actively steered an agent
into the wrong remedy **five times in a row**, and the agent had no way to notice from the
advisory alone.
**Class**: guidance defect, not a code defect. Every handler behaved exactly as written.

---

## Summary in one sentence

The plan-size guidance presents **exactly two remedies** — relocate narrative into `JOURNAL/`,
or split the plan — but the correct remedy for the most common cause of an oversized `PLAN.md`
is **a third one the guidance never names: extract the content into a named supporting document
in the plan folder**.

The daemon's own internal `PlanWorkflow.md` documents supporting docs. **The deployed,
client-facing guidance does not mention them anywhere.**

---

## What actually happened

A plan (`00003`) sat just over the 18,000-byte advisory. The advisory fired repeatedly across
several sessions. Each time, the agent (me) read the remedy, found that:

- **"Relocate into `JOURNAL/`"** did not fit — the oversized content was *current decision
  material* (a rate table, a positioning statement, a regulatory correction). A journal is
  append-only and, by the daemon's own read contract, **never read whole**. Relocating live
  decisions there makes them effectively unreachable.
- **"Split the plan"** did not fit — the task tree was fine at 31 tasks in 6 phases. The
  guidance itself says splitting is for when "the task tree is the bulk". It wasn't.

Neither sanctioned remedy applied. So I did the unsanctioned third thing: **compressed
sentences**. Five times. Each pass bought 200–600 bytes and lost detail; at one point I deleted
a decision table outright purely to get under a threshold.

**The user diagnosed it in one message**, correctly and immediately:

> "plans track work / they do not log findings, reseach etc — thee things are tracked in other
> files in the plan folder / the plan is basicaly the task list + instructions / i think you are
> using the plan as a notepad or something?"

**Result after applying the unnamed third remedy**: three supporting docs extracted into the
plan folder, `PLAN.md` **19,045 → 9,520 bytes**, all 31 tasks intact, `plan-qa --lint` clean.
**The extracted content is now fuller than what I had compressed away** — the table I deleted
came back in full, because it finally had a legitimate home.

---

## The evidence was measurable, and the daemon could compute it

Across four plans in this project:

| Plan  | `PLAN.md`  | Supporting docs | Tripped the advisory?         |
| ----- | ---------- | --------------- | ----------------------------- |
| 00002 | 7,753 b    | 11              | never                         |
| 00004 | 9,220 b    | 0 (newly born)  | never                         |
| 00001 | 17,419 b   | 19              | never                         |
| 00003 | **17,834** | **0**           | **repeatedly, over sessions** |

**The plan with zero supporting docs was the only one carrying its findings inside the task
list, and the only one that kept tripping.** That correlation is exactly the signal the advisory
should be surfacing, and it is cheaply computable at the moment the check fires: *this plan
folder contains a `PLAN.md`, a `JOURNAL/`, and nothing else.*

**Honest caveat, because it weakens the neat version of this story**: plan 00001 has 19
supporting docs and is still 17,419 bytes. Supporting docs are not a universal cure — that plan
is large because its task tree genuinely is. So the daemon should *suggest* the third remedy
based on folder shape, not assert it. The signal is a hint, not a diagnosis.

---

## Root cause

### 1. The remedy string offers a false binary

`src/claude_code_hooks_daemon/plan_qa/checks/plan_doc_size.py:59-66`:

```python
_REMEDY: Final[str] = (
    "Two remedies, and NEITHER is deletion: (1) RELOCATE the narrative — dated "
    "progress notes, incident write-ups, hand-off prose — into this plan's "
    "JOURNAL/ day-file, which is append-only and unbounded by design; or "
    "(2) SPLIT the plan if the task tree itself is the bulk, since an "
    "over-scoped plan is not fixed by better journalling. Keep PLAN.md lean, "
    "current and correct — history belongs in git and in JOURNAL/."
)
```

Note the enumeration of what "narrative" means: *"dated progress notes, incident write-ups,
hand-off prose"*. **All three are historical.** There is no category offered for content that is
**durable, detailed, and current** — research output, a decision and its reasoning, an evidence
table, a draft deliverable. That content is neither history (so not `JOURNAL/`) nor task tree
(so not a split). The guidance has no slot for it, so it stays in `PLAN.md` and inflates it.

The same two-remedy text is duplicated at:

- `plan_qa_edit.py:177` — the edit-stage block message
- `plan_workflow.py:90` — the injected `CLAUDE.md` section ("exactly two remedies")

### 2. The `PLAN.md` ↔ `JOURNAL/` table frames plan folders as a two-file world

The `plan_workflow` guidance table is genuinely excellent — the write/read/size contract
asymmetry is well argued and I have not seen it explained better. But it is a **two-column**
table, and it reads as exhaustive. An agent internalises "a plan folder is `PLAN.md` plus
`JOURNAL/`", because that is the only structure ever described.

### 3. The sharpest finding: the daemon already knows, and doesn't ship it

`.claude/hooks-daemon/CLAUDE/PlanWorkflow.md:109-110` — the daemon's **own internal** planning
doc:

```
CLAUDE/
└── Plan/
    ├── 001-handler-implementation/
    │   ├── PLAN.md                      # Main plan document
    │   ├── {supporting-docs*}.md        # Supporting analysis docs
    │   └── assets/                      # Diagrams, logs, etc.
```

But the deployed client template
`src/claude_code_hooks_daemon/install/templates/PlanJournalling.md` contains **zero** occurrences
of "supporting" or "asset". Neither does any enforcement surface.

**So the concept exists upstream and never reaches the client.** The daemon's own plans are
structured correctly; the guidance it injects into client projects describes a simpler world
than the one its authors actually work in. That is the whole bug, and it is a cheap fix.

---

## A consequence worth flagging separately: `plan-shrink-without-journal` mis-reads this

`plan_shrink_without_journal.py:3-6` states the binary as its explicit premise:

> "telling an agent 'your plan is too big' invites DELETION, when the intended move is to
> RELOCATE narrative into the plan's `JOURNAL/`. The two are easy to tell apart at commit time —
> **a relocation stages a journal entry, a deletion does not.**"

The check confirms this — it passes only on `has_staged_journal_entry()` (line 66).

**Extraction into a supporting doc is invisible to it.** My restructure commit shrank `PLAN.md`
by **9,525 bytes** — 4.7× the 2,000-byte threshold — while staging three brand-new `A`-status
`.md` files in the same plan folder. That is the *most* textbook relocation possible, and the
check's only reason for not flagging it was that I happened to also journal the change.

Had I extracted without journalling, the daemon would have told me I had **deleted** narrative,
when I had done precisely the right thing. The premise "relocation ⇒ journal entry" is true for
*historical* narrative and false for *durable* narrative.

**Suggested fix**: treat a staged `A`-status `.md` file in the same plan folder (excluding
`JOURNAL/`) as satisfying the check, exactly as a journal entry does. Cheap, and it removes a
false positive that would actively punish correct behaviour.

---

## Proposed changes

Ordered by value-to-effort. All are guidance/text except #4.

### 1. Add the third remedy to `_REMEDY` — highest value, smallest diff

`plan_doc_size.py:59`. Something like:

> **Three remedies, and NONE is deletion:** (1) **EXTRACT** durable detail — research output,
> findings, decisions and their reasoning, drafts, evidence tables — into a **named supporting
> document in this plan folder** (`RESEARCH-*.md`, `*-BRIEF.md`, `DECISIONS.md`), and link to it
> from the task; (2) **RELOCATE** dated narrative — progress notes, incidents, hand-offs — into
> `JOURNAL/`; (3) **SPLIT** the plan if the task tree itself is the bulk.

The ordering matters: **extraction should be listed first**, because it is the correct answer
most often. `PLAN.md` is a task list; almost anything making it big is detail that wants a name.

### 2. Make the `plan_workflow` table three-column

Add a `SUPPORTING-DOC.md` column beside `PLAN.md` and `JOURNAL/`:

|             | `PLAN.md`                | `SOME-DOC.md`                                         | `JOURNAL/`              |
| ----------- | ------------------------ | ----------------------------------------------------- | ----------------------- |
| **Content** | Task list + instructions | Durable detail: research, findings, decisions, drafts | What happened, dated    |
| **Write**   | Edit in place, keep lean | Edit in place, freely                                 | Append only             |
| **Read**    | In full, every session   | On demand, via link                                   | Never whole — grep/tail |
| **Size**    | Bounded                  | Unbounded                                             | Unbounded               |

The **read contract** is what justifies it, in exactly the same way it justifies the existing
two: a supporting doc is unbounded because it is only opened when its link is followed, so it
costs nothing to the sessions that don't need it. This is the same progressive-disclosure
argument the `markdown_organization` handler already makes for `.claude/rules/*.md` — the plan
system just isn't applying its own principle.

### 3. Add the folder-shape hint to the advisory

When `plan-doc-size` fires, check whether the plan folder contains any `.md` besides `PLAN.md`
and `JOURNAL/*`. If not, append one line:

> This plan folder contains no supporting documents. A `PLAN.md` over the threshold with no
> supporting docs is usually a plan being used as a notepad — check whether the bulk is findings
> or research that wants a named file, rather than prose that wants compressing.

This is the single change that would have saved five wasted passes. **The advisory told me a
threshold was crossed; it could not tell me why, and I never thought to ask.**

### 4. Teach `plan-shrink-without-journal` about extraction

Per the section above — accept a staged new `.md` in the plan folder as evidence of relocation.
This is the only code change proposed.

### 5. Ship the concept to clients

Port the supporting-docs structure from `CLAUDE/PlanWorkflow.md:109-110` into
`install/templates/PlanJournalling.md` and the injected `plan_workflow` guidance.

---

## What is NOT wrong here — worth stating, because most of this system is right

I want to be precise about scope, since it would be easy to read the above as a broader
complaint. It isn't.

- **The size tiers are well calibrated.** 18,000 / 25,000 / 35,000 with block-only-on-growth is
  a genuinely well-designed escalation, and "only an edit that GROWS the file can be blocked" is
  a thoughtful touch that keeps an oversized plan always fixable.
- **The advisory was right every single time it fired.** The plan *was* too big. The problem is
  purely that the suggested remedies did not include the correct one.
- **The `PLAN.md` / `JOURNAL/` contract asymmetry is excellent** and the read-contract
  justification for it is the clearest articulation of that idea I have encountered. The
  proposal above extends that reasoning rather than disputing it.
- **`plan-qa --lint` / `--check-staged` are genuinely useful** and I used both to verify the
  restructure. Exit codes and JSON output make them trivially scriptable.
- **No handler malfunctioned.** Every one did exactly what it says. This is a documentation gap
  with real behavioural consequences, which is a different and cheaper thing to fix than a bug.

---

## The general lesson, offered because it likely generalises past this handler

**An advisory that fires repeatedly without being resolved is itself a signal, and nothing in
the system treats it as one.**

I applied the same ineffective remedy five times. Each application was locally reasonable — the
file did get smaller — and none addressed the cause. The daemon has the information needed to
notice this (it knows the plan number, it knows the check ID, it knows it has fired before), and
a repeat-firing advisory could say something categorically more useful than the first firing:

> This check has fired on this plan N times. Repeated remediation that does not hold usually
> means the remedy is aimed at the wrong cause — re-diagnose rather than reapplying.

That framing would generalise to any advisory handler, and it targets a real agent failure mode:
**an advisory tells you a threshold was crossed, but it cannot tell you why, and an agent under
task pressure will reach for the cheapest action that clears the threshold rather than stopping
to diagnose.** Nudging toward diagnosis on repeat firings is probably worth more than any
individual wording improvement above.
