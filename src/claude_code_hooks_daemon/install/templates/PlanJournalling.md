# Plan Journalling

> **Reference, not gospel.** This document describes how the hooks daemon
> supports per-plan journalling. It is deliberately copy-and-customisable:
> a client project can adopt it verbatim, tune the conventions to taste, or
> replace the narrative wholesale — the only hard contract is the small set
> of **daemon-enforced** rules called out in the POLICY section at the end.

## Why journal a plan (and where does durable detail go)?

`PLAN.md` captures **what** the work is and **why** — goals, tasks, decisions,
success criteria. It is a living *specification*, curated and rewritten as the
plan evolves. It is a TASK LIST, kept deliberately lean, so it structurally
cannot hold two other kinds of content that plans accumulate:

- The **linear time-series of what actually happened** — findings, dead-ends,
  in-flight decisions, hand-off state a future agent needs to pick the work
  back up. This is HISTORY: it belongs in `JOURNAL/`.
- **Durable detail that is current** — research output, a decision and its
  full reasoning, an evidence table, a draft deliverable. This is NOT
  history (it is still true today) and NOT task list (it is not a task) —
  it belongs in a **named supporting document** in the plan folder.

Conflating either of these with `PLAN.md` is the same failure mode with two
different symptoms: append the time-series and `PLAN.md` becomes a stale
log; compress the durable detail to keep `PLAN.md` "lean" and you delete
real content trying to hit a size target. A **journal** is the first
stream — each plan folder gains a `JOURNAL/` sub-directory holding per-day,
append-only files. A **supporting document** is the second — a plain `.md`
file living directly in the plan folder, edited in place like `PLAN.md` but
never re-read in full by every session, only opened on demand via a link
from a task.

| Question                                      | Look in            |
| --------------------------------------------- | ------------------ |
| What are we building and why?                 | `PLAN.md`          |
| What tasks remain? What's the status?         | `PLAN.md`          |
| What does the evidence/research/decision say? | a supporting `.md` |
| What did we try at 14:00 that failed?         | `JOURNAL/`         |
| Where did the last session hand off?          | `JOURNAL/`         |
| Why was option B rejected mid-flight?         | `JOURNAL/`         |

Three diaries would drift; one specification (`PLAN.md`), supporting
documents for durable detail, and one activity log (`JOURNAL/`) stay
coherent.

## The contracts (SSoT)

This table is the single source of truth for how the three file kinds
differ. Everything else — handler guidance, `docs/PLAN_SYSTEM.md`, the size
checks — points here rather than restating it.

|             | `PLAN.md`                                                                          | supporting `SOME-DOC.md`                                                                                                                 | `JOURNAL/NNNNN-Journal-YY-MM-DD.md`                                                                              |
| ----------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Write**   | Commit if dirty, edit **in place**, commit. Rewrite freely — git holds the history | Edit **in place**, freely — a named document, not a log                                                                                  | **APPEND ONLY.** Never edit or remove an earlier entry; corrections are new dated entries at the bottom          |
| **Content** | Lean, surgical, always correct — current truth only                                | Durable detail that is current but too big for the task list: research, findings, decisions and their reasoning, evidence tables, drafts | What actually happened: dated progress, findings, dead-ends, hand-offs                                           |
| **Read**    | Read **in full** every session — it is your grounding                              | **On demand only** — opened when its link from `PLAN.md` is followed                                                                     | **Never read whole.** `tail -n N` the newest day-file, grep for a term, or send a sub-agent for deep archaeology |
| **Size**    | Bounded and enforced — see the tiers below                                         | **Unbounded** — never opened by a session that doesn't follow its link, so it costs that session nothing                                 | **Unbounded by design.** Length is never a problem; never tidy, trim or summarise a journal                      |

### Why the asymmetry (the read contract justifies the write contract)

A plan is re-read **in full** at the start of every session that touches it, so
every kilobyte is a recurring context cost paid before any work begins. A
supporting document and a journal are both only ever **read on demand** — one
via its link, the other by tailing/grepping, or by a sub-agent whose context
is discarded afterwards — so both are safe to let grow forever. This is the
same progressive-disclosure argument this daemon's `markdown_organization`
handler already makes for `.claude/rules/*.md`; a plan folder just wasn't
applying its own principle to itself.

That single fact explains the whole design: it is why a plan has a size
limit at all, and why applying one to a supporting document or a journal
would be a category error. It is also why "my journal is getting long" (or
"my RESEARCH.md is getting long") is never a problem to fix.

### Reading a journal without flooding your context

```bash
tail -n 60 CLAUDE/Plan/00190-thing/JOURNAL/00190-Journal-26-07-31.md
grep -n "rate limit" CLAUDE/Plan/00190-thing/JOURNAL/*.md
```

Both take the path as an **argument**, so no pipe is involved and the
`pipe_blocker` handler never sees them. For anything deeper — "why did we
abandon approach B three weeks ago?" — dispatch a sub-agent to read the
journal and report back, so the bulk never enters your own context.

### Size tiers on `PLAN.md`

Enforced by the `plan-doc-size` check; configurable under
`plan_workflow.qa.plan_doc_size`. A tier trips on **bytes or lines**,
whichever comes first.

| Tier     | Bytes    | Lines | Effect            |
| -------- | -------- | ----- | ----------------- |
| Advisory | > 18,000 | > 350 | Nudge             |
| Warning  | > 25,000 | > 500 | Escalated wording |
| Block    | > 35,000 | > 900 | Edit denied       |

**When a plan exceeds a tier there are three remedies, and NONE is
deletion:**

1. **Extract** durable-but-current detail — research output, findings,
   decisions and their reasoning, drafts, evidence tables — into a named
   supporting document in the plan folder (e.g. `RESEARCH.md`,
   `DECISIONS.md`) and link to it from the task. This is the correct answer
   most often: `PLAN.md` is a task list, so almost anything making it big is
   detail that wants a name, not history and not more tasks.
2. **Relocate** dated narrative into this plan's `JOURNAL/` day-file.
3. **Split** the plan if the task tree itself is the bulk — an over-scoped
   plan is not fixed by better journalling.

**Only an edit that GROWS the file can be blocked.** Shrinking it is silent
(that is the remedy in progress) and a same-size edit such as ticking a
checkbox only advises — so an oversized plan can always be updated and
refactored down. A plan that genuinely warrants its size declares why with
`<!-- MUST_EXCEED_PLAN_SIZE_BECAUSE: <reason> -->`. A commit that shrinks a
`PLAN.md` sharply while staging neither a journal entry NOR a new
supporting document is flagged by `plan-shrink-without-journal` — that shape
is usually content being deleted rather than relocated or extracted. If the
advisory notes the plan folder has no supporting documents at all, that is
a HINT the bulk may be detail wanting a named file — never a diagnosis
(some plans are legitimately large because the task tree itself is the
bulk).

## Layout

```
CLAUDE/Plan/NNNNN-name/
  PLAN.md
  RESEARCH.md                      # optional: a named supporting document
  DECISIONS.md                     # optional: another one — as many as needed
  assets/                          # optional: diagrams, logs, non-markdown artefacts
  JOURNAL/
    NNNNN-Journal-YY-MM-DD.md      # one file per LOCAL day with activity
    NNNNN-Journal-YY-MM-DD.md
```

- Supporting documents are plain `.md` files living **directly** in the plan
  folder, named for their content (`RESEARCH.md`, `DECISIONS.md`,
  `RATE-TABLE.md` — whatever names the detail). There is no fixed count or
  naming scheme; a plan may have zero, one, or many. Link to them from the
  relevant task in `PLAN.md` rather than duplicating their content there.
- `JOURNAL/` is an upper-case landmark sibling of `PLAN.md`, **inside** the plan
  folder — so archiving a plan (`git mv` into `Completed/`) carries the journal
  (and every supporting document) for free.
- Day-files are named `NNNNN-Journal-YY-MM-DD.md`: the redundant `NNNNN` plan
  number survives copy/paste and greps cleanly; `YY-MM-DD` is the local day.
- **One file per local day.** Multiple entries append to that day's file. A day
  with no activity has **no file** — never scaffold empty day-files.
- `mkplan.bash` scaffolds `JOURNAL/` plus a seeded day-1 file automatically when
  a `_JOURNAL_TEMPLATE_.md` is present in the plan directory.

## Entry grammar

Each entry is a heading with a fixed grammar followed by a free markdown body:

```
## HH:MM · CATEGORY · REF   [— optional short title]
```

- **`HH:MM`** — UTC 24-hour time when appended through `mkplan.bash --journal`
  (the date lives in the filename, also UTC); a day-file whose preamble
  carries no sentinel line predates this system and its times are local with
  the zone unrecorded (legacy — never migrated). Times run monotonically down
  a file.
- **`CATEGORY`** — one of a small fixed core set:
  `action` · `finding` · `decision` · `thought` · `blocker` · `handoff` ·
  `correction`. `mkplan.bash --journal` accepts exactly these seven and
  rejects any other.
- **`REF`** — optional task/phase reference (`T2.1`, `P2`, or `—` for none).
  For a `correction` it is required and names the corrected entry instead:
  see [Append-only discipline](#append-only-discipline).
- Separator is the middot `·` (U+00B7).

Bodies may embed fenced logs, diffs, or code snippets — put a one-line takeaway
*above* the fence so a skim reader gets the point without expanding it.

### Appending an entry

`mkplan.bash --journal` is THE way to add an entry, not the preferred one. It
reads the real clock, normalises it to UTC and writes the heading itself, so
the caller never supplies a time:

```bash
# 1. Write the entry BODY (no heading) with the Write tool to a FRESH file, e.g.
#    untracked/scratch/journal-190-260924-1405.md
# 2. Append it:
CLAUDE/Plan/mkplan.bash --journal 190 finding untracked/scratch/journal-190-260924-1405.md --title "rate limit is per token"
```

Add `--ref T2.1` for a task reference. If today's day-file does not exist yet,
the script creates it from `_JOURNAL_TEMPLATE_.md` first. `mkplan.bash --help`
prints the full usage. Use a new body-file name for every entry: the file stays
behind after the append, and a second Write to the same name is refused by the
clobber guard (ledger 00422 N29), as is one sub-agent writing over another's.
In a worktree, run that worktree's own `CLAUDE/Plan/mkplan.bash`.

**Why it is enforced.** In one session a coordinator and five sub-agents
appended every entry by hand. One heredoc entry was stamped `09:50` when the
clock read `09:11`. A journal is append-only, so a wrong stamp can only be
corrected by a later `correction` entry that names it, and the file then
carries both readings for good. The `plan_journal_guard` handler therefore DENIES a hand-written entry and
prints the exact `--journal` command for that plan, with absolute paths into
the checkout the day-file belongs to. It covers every checkout, worktrees
included, and archived plans. It denies:

- an `Edit` or `Write` that adds any line to a day-file, or a `Write` that
  creates one. Any line, not only a heading: a note appended under the last
  entry inherits that entry's stamp;
- a Bash command that writes into a day-file by any route: `>`/`>>`, `tee`, a
  heredoc, `cp`/`mv`/`install`/`dd`/`ln`/`rsync`/`sponge` onto it, an in-place
  editor, a patch, or a program handed to an interpreter (inline, on a heredoc,
  or behind a wrapper such as `timeout` or `uv run`) that opens it for writing;
- a Bash destination the shell builds at run time (`$(date …)`, a variable, a
  glob, a relative name after a `cd` in the same command) that names a
  day-file, or whose file name is built inside a `JOURNAL/` directory.

It allows `mkplan.bash` itself, `git` (moving a plan folder into `Completed/`
carries the journal), reading a journal, and an `Edit` that adds no line:
removing conflict markers after merging two branches that each appended an
entry, reordering, or redacting within a line. It is active only where the tool
exists: plan workflow enabled, journalling enabled and not `off`,
`mkplan.bash` deployed with `--journal`, `_JOURNAL_TEMPLATE_.md` present, and
the journal directory left at its default `JOURNAL` name. When any of those
fails it is inert and logs which one, once, at INFO. A coordinator that asks a
sub-agent to journal puts the two-step pattern above in the brief.

### Append-only discipline

A journal is **append-only**. New entries go at the **bottom**; earlier entries
are never edited. **Corrections are new entries**, not rewrites — if you got
something wrong at 09:00, append a `correction` entry whose `--ref` names it.
This keeps the log an honest record of what was believed when, and lets the
daemon's `journal-append-only` check confirm each edit only adds.

```bash
CLAUDE/Plan/mkplan.bash --journal 190 correction untracked/scratch/journal-190-fix.md --ref 09:00
```

The `--ref` is `HH:MM` for an entry in today's day-file, or `YY-MM-DD/HH:MM`
for one in an earlier day-file of the same plan. The script refuses a
correction whose named entry does not exist, and writes nothing.

**A correction is also how a wrong clock reading is fixed.** If an entry was
stamped `09:50` when the clock read `09:11`, the correction's honest time is
earlier than the entry it corrects. Appending it still breaks "times increase
down the file", and moving it would break append-only. So an entry that a
correction in the same day-file names no longer counts for
`journal-entry-ordering`. It stays where it is, with its text unchanged, and
the entries around it are judged without it. Only a `correction` has this
effect. A `--ref` on any other category is a task reference.

### Hand-off convention

The resumer's entry point is the **last entry of the newest day-file**. End a
work session with a `handoff` entry naming what's done, what's next, and any
in-flight state — so the next agent (or the failsafe recovery cron) can resume
without re-deriving context.

## Good vs. noise

Journal **meaningful events**, not every tool call. The log is a narrative a
human or agent reads to reconstruct the work — not a keystroke trace.

**Good** (worth an entry):

```
## 14:05 · finding · T1.4 — append-only check can't use try/except-return
The error_hiding audit flags `return None` inside `except`. Fixed by splitting
regex-match (guard-clause None) from calendar validity (precondition via stdlib
`calendar`), so no ValueError is ever caught. QA error_hiding now clean.

## 15:20 · decision · T1.6 — grandfather at plan number, not date
Chose number threshold (≥163) over a date cutoff for `journal-folder-present`:
survives clean across branches and needs no git query. Legacy plans below the
threshold are never nagged.
```

**Noise** (do not journal):

```
## 14:06 · action · — ran pytest      ← tick-spam; only log a meaningful result
## 14:07 · action · — read a file     ← not an event
## 14:08 · thought · — hmm            ← empty; say something or omit
```

Cadence is a *convention*: journal when something is worth grounding a future
agent on. It is never enforced per-tool-call — the daemon never turns
journalling into a heartbeat.

## Lifecycle touchpoints

| When                         | Do                                                                                                                                                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Plan created (`mkplan.bash`) | `JOURNAL/` + day-1 file scaffolded; append an `action` entry with `mkplan.bash --journal`                                                                                                                    |
| Work happens                 | Append `action`/`finding`/`decision`/`blocker` entries with `mkplan.bash --journal <plan-number> <category> <body-file> [--ref R] [--title T]` — the only way; see [Appending an entry](#appending-an-entry) |
| A day rolls over             | Nothing to do: `--journal` creates today's `NNNNN-Journal-YY-MM-DD.md` on the day's first entry (never create one by hand)                                                                                   |
| Session ends / context low   | Append a `handoff` entry naming next steps, with `mkplan.bash --journal`                                                                                                                                     |
| Plan archived                | `JOURNAL/` moves with the folder automatically                                                                                                                                                               |

## Notes & Updates migration

Historically the blow-by-blow stream was crammed into `PLAN.md`'s
`## Notes & Updates` section, which strained the file and got compressed away.
Going forward, that stream lives in `JOURNAL/`; `PLAN.md` keeps only a thin,
curated `## Delivery & Milestones` stub (milestone lines + delivery commit
hashes for the completion checklist). Legacy plans that still carry
`## Notes & Updates` are never rewritten — the change applies to new material.

---

## POLICY vs CONVENTION

Everything above is **convention** you can tune, **except** the small set of
rules the daemon actually checks. The journal QA checks below ship **ADVISE**
(they add context, they do not block) and are governed by
`plan_workflow.qa.journal.*` in `.claude/hooks-daemon.yaml`.

The one journal rule that DENIES is a handler rather than a QA check:
`plan_journal_guard` (see [Appending an entry](#appending-an-entry)). It
stands down when `journal.enabled` is false, `journal.mode` is `off`, or
`journal.dir_name` is not `JOURNAL`, and in any checkout whose plan directory
lacks `_JOURNAL_TEMPLATE_.md` or a `mkplan.bash` that offers `--journal`. Each
of those is logged once at INFO. It is switched off on its own with
`handlers.pre_tool_use.plan_journal_guard.enabled: false`.

> **`mode: block` is a ceiling, not a guarantee.** The journal sub-block is
> subordinate to the surface mode it rides on: a journal blocker only denies
> when `plan_workflow.qa.edit_mode` is ALSO `block`. Under `edit_mode: warn` it
> degrades to an advisory, and `edit_mode: off` disables both journal edit
> checks outright — even with `journal.enabled: true`. Set the surface mode
> first, then ratchet `journal.mode`.

### Daemon-enforced (POLICY)

| Check                    | Stage | What it advises                                                                            | Knob                                                |
| ------------------------ | ----- | ------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| `journal-dayfile-naming` | edit  | day-file name matches `NNNNN-Journal-YY-MM-DD.md`, right plan number, today/yesterday date | `mode` (the only check that may ratchet to `block`) |
| `journal-append-only`    | edit  | an edit only appends — never rewrites/removes earlier entries                              | always advise                                       |
| `journal-folder-present` | sweep | an In-Progress plan ≥ `grandfather_before` has a `JOURNAL/`                                | `grandfather_before`                                |
| `journal-freshness`      | sweep | a plan's newest day-file isn't older than `freshness_days`                                 | `freshness_days`                                    |

Configuration block (defaults shown):

```yaml
plan_workflow:
  qa:
    journal:
      enabled: true          # master switch for all journal checks
      mode: advise           # advise | block | off (only naming honours block)
      dir_name: JOURNAL       # journal sub-directory name
      freshness_days: 3       # nag a quiet JOURNAL/ sooner than plan staleness
      enforce_on_completion: false
      grandfather_before: 0   # plans below this number are never nagged for a JOURNAL/
```

Set `grandfather_before` to the plan number at which your project adopted
journalling, so pre-existing journal-less plans are never nagged (no backfill).

### Client-tunable (CONVENTION)

Cadence, hand-off style, the `## Delivery & Milestones` stub, and everything in
the narrative sections above are yours to adapt. The four checks and their
knobs are enforced, only ever as advisories unless you deliberately ratchet
`mode: block`. So is `plan_journal_guard`, which denies a hand-written entry
wherever `mkplan.bash --journal` and its template are deployed. The heading grammar (category
set, middot separator) is written by that tool, so it is fixed while the guard
is on.
