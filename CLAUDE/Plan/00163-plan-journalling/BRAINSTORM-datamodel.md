# Plan Journaling — Data Model & Lifecycle Brainstorm

**Angle**: data model & lifecycle (a sibling agent covers enforcement mechanism).
**Repo grounding**: `CLAUDE/PlanWorkflow.md`, `CLAUDE/Plan/CLAUDE.md`, `CLAUDE/Plan/mkplan.bash`,
`CLAUDE/Plan/_TEMPLATE_.md`, `src/claude_code_hooks_daemon/plan_qa/` (parsers + checks catalogue).

---

## 0. What the repo already does (the constraints my design must fit)

- A plan = `CLAUDE/Plan/NNNNN-name/PLAN.md`; on a **terminal** status it is `git mv`'d whole into
  `CLAUDE/Plan/Completed/NNNNN-name/` (or `Cancelled/`). See `CLAUDE/Plan/CLAUDE.md`.
- `mkplan.bash` scaffolds the folder + `PLAN.md` **with bash `mkdir`/`cat`, NOT the Write tool** —
  deliberately, so the daemon's plan-number handler never sees the write and never double-increments.
  It renders a project-owned `CLAUDE/Plan/_TEMPLATE_.md` (Plan 00144) if present, else a built-in
  skeleton. `Created` uses `date +%F` (local date).
- **`## Notes & Updates`** in every PLAN.md is *already an ad-hoc journal*: real plans (00161, 00158)
  use it for dated `### YYYY-MM-DD` subsections holding cron IDs, findings, dogfooding notes,
  "CONFIRMED TRUTH #1..3", decisions-in-flight, delivery commit hashes. This is the exact overlap to
  reconcile — the journal formalises what Notes & Updates is informally straining to hold.
- `plan_qa` parsers are **rigid** and **ignore fenced code blocks** (plans embed shell/template
  excerpts). Any journal grammar the daemon lints must survive `markdown_table_formatter` (it rewrites
  *every* `.md` written — HTML comments and headings survive; tables get re-aligned).
- Status tokens (`plan_qa/model.py`): Not Started, In Progress, Complete, Blocked, Cancelled,
  Superseded, Dormant. Terminal = {Complete, Cancelled, Superseded}. **No completion dates** in plans
  (git is SSoT for "when"); `Created` *is* allowed.
- `markdown_organization` allows the whole `CLAUDE/Plan/` subtree, so `CLAUDE/Plan/NNNNN/JOURNAL/*.md`
  is an allowed write location with **zero config change**. (There is no top-level `CLAUDE/Journal/`
  today — Plan 00132 only *reserves the name* as a future exclusion; do not conflate.)
- Live datapoint: **this session crossed local midnight** (07-13 → 07-14). A day-partitioned journal
  must therefore roll to a new file mid-session — a real, not hypothetical, case.

---

## 1. File & folder naming

**Recommendation — confirm the user's shape, one tweak offered:**

```
CLAUDE/Plan/NNNNN-name/
  PLAN.md
  JOURNAL/
    NNNNN-Journal-YY-MM-DD.md      # e.g. 00163-Journal-26-07-14.md
    NNNNN-Journal-YY-MM-DD.md      # next day with activity
```

- **Redundant NNNNN in the filename is deliberate and good.** It survives copy/paste out of the
  folder, greps cleanly (`rg "00163-Journal"`), and disambiguates when several journals are opened at
  once. Keep it.
- **`JOURNAL/` (upper) vs `journal/`**: upper-case matches the "shouty landmark" style of `PLAN.md`
  and reads as a sibling artifact, not source. Keep `JOURNAL/`.
- **Date field — `YY-MM-DD` vs `YYYY-MM-DD`.** User specified `YY-MM-DD`. It lexically sorts correctly
  within this century and is terser. *Offered alternative*: `YYYY-MM-DD` (matches `date +%F`, the
  `Created` header, and `plan_qa`'s `_STATUS_DATE_RE = (\d{4}-\d{2}-\d{2})` — reusing that exact
  pattern would let a future lint parse the filename with an existing regex). **Call**: honour the
  user's `YY-MM-DD` but flag the 4-digit option as a near-free consistency win (§7 open question).
- **Timezone = local system date**, matching `mkplan`'s `date +%F` and the daemon's own "today". A
  **day = local midnight-to-midnight**. Document this explicitly; a session spanning midnight opens a
  new file (as this one would). Do **not** use UTC — it would disagree with `Created` and confuse
  humans reading their own wall-clock.
- **One file per day, append within it. Multiple entries per day → appended to that one file.**
- **A day with no activity has NO file.** Journals are sparse by design; the *set of files present*
  is itself a signal ("worked on 3 days"). Never scaffold empty day-files — an empty file is noise and
  would trip a "did anything happen?" reading.
- **Closure move is free.** Because `JOURNAL/` lives *inside* the plan folder,
  `git mv CLAUDE/Plan/NNNNN CLAUDE/Plan/Completed/NNNNN` carries the whole journal with it. No extra
  handling, and `plan_qa`'s `terminal_state_atomic` check (folder move + README row + stats in one
  commit) already covers it unchanged.

---

## 2. Entry format / grammar

**Design goals**: append-only, greppable by hand, machine-lintable, survives `mdformat-gfm`, no size
limit (entries may embed logs/snippets/diffs in fenced blocks).

**Recommended per-entry unit = an H2/H3 heading with a fixed, parseable grammar + free markdown body.**

```markdown
## 14:37 · finding · T2.1

`context_sidecar` keys state by `session_id`, but `disclosure_tracker` keys by
`transcript_path`. A per-thread status line therefore cannot reuse sidecar state.

Evidence:
```

$ rg "session_id" src/.../context_sidecar.py
...

```
```

Grammar of the heading line (the machine-parseable part):

```
## HH:MM · CATEGORY · REF   [— optional short title]
   |        |          |
   |        |          └─ optional: task/phase ref (T2.1, P2, README, —)
   |        └─ one of: action | finding | decision | thought | blocker | handoff
   └─ local 24h time (date is in the filename; do not repeat it)
```

- **Why heading-based, not a table**: headings survive mdformat untouched and render as a navigable
  outline (newest at bottom, or newest-first — see §5). A `·`-delimited heading is trivially split by
  a rigid parser (mirroring how `plan_qa/model.py` already splits `**Status**:` lines).
- **Optional machine header for strict linting**: if the enforcement agent wants a stronger contract,
  prefix each entry with a single HTML comment that mdformat preserves verbatim:
  `<!-- j ts=2026-07-14T14:37 actor=opus cat=finding ref=T2.1 -->`. This gives an unambiguous,
  table-formatter-proof, code-fence-proof anchor. **Recommendation**: make the human heading the
  *primary* contract and the HTML-comment header *optional/advisory* — one grammar to teach, and the
  daemon can lint the heading alone.
- **Categories (fixed, small, greppable)**:
  - `action` — what I did (ran X, wrote Y, restarted daemon).
  - `finding` — what I learned / confirmed / measured (the "CONFIRMED TRUTH" pattern from 00158).
  - `decision` — a choice made *in flight* (the durable version graduates into PLAN.md, see §3).
  - `thought` — hypothesis / next-step reasoning / open worry.
  - `blocker` — hit a wall / cleared a wall (pair with the clearing entry).
  - `handoff` — context snapshot for the next agent / pre-compaction / end-of-session.
- **Actor**: single-agent plans can omit it. For agent-teams (Opus + sub-agents, common here) put the
  actor in the optional HTML header (`actor=`) or as a trailing `— @opus`. Do not force it on every
  entry — YAGNI for solo plans.
- **Append-only, expressed as convention + parser-friendly hooks** (enforcement is the sibling
  agent's remit, but the *data model* must make it checkable):
  1. **Monotonic times** within a file — a new entry's `HH:MM` ≥ the last entry's. A lint can flag a
     regression.
  2. **Never edit a prior entry's body**; corrections are a *new* entry (`## 15:02 · finding · T2.1`
     "correction to 14:37: …"). This is exactly how 00158 handled its "the initial claim was **wrong**"
     moment — as a new note, not a rewrite.
  3. A git-diff-based check (sibling agent) can assert edits to a `JOURNAL/*.md` only *add* trailing
     lines. The data model enables this by making entries strictly append-ordered.

---

## 3. Relationship to PLAN.md "Notes & Updates" — \*\*recommendation: SUBSUME the blow-by-blow,

keep a thin curated milestone log\*\*

Today `## Notes & Updates` carries two *different* kinds of content mashed together:

| Content in Notes & Updates today            | Where it belongs under journaling                   |
| ------------------------------------------- | --------------------------------------------------- |
| Dated activity ("Phase 1 brainstorm dele…") | → **JOURNAL** (this is the time-series log)         |
| Findings / "CONFIRMED TRUTH #1..3"          | → **JOURNAL** (`finding` entries)                   |
| Cron IDs, dogfooding observations           | → **JOURNAL** (`action`/`finding`)                  |
| Decisions-in-flight                         | → **JOURNAL** (`decision`), resolved form → PLAN.md |
| **Delivery commit hash(es) on completion**  | → stays discoverable in PLAN.md (see below)         |

**Recommended split:**

- **PLAN.md keeps** (durable, curated, low-churn): status header, Overview, Goals, Non-Goals, Tasks,
  **Technical Decisions** (the *resolved* decision + rationale — the journal is where a decision is
  argued out; the settled decision graduates into PLAN.md), Success Criteria, Dependencies.
- **JOURNAL takes** the entire linear activity stream that `## Notes & Updates` currently strains to
  hold.
- **Retire the free-form `## Notes & Updates` section** from `_TEMPLATE_.md`, and **replace it with a
  short, curated `## Delivery & Milestones`** — a hand-maintained list of *milestone* lines and the
  **delivery commit hash(es)** required by the completion checklist. Rationale: the completion
  checklist and `CLAUDE/Plan/CLAUDE.md` both say "cite the delivery commit hash(es) in Notes &
  Updates"; those must still land somewhere in PLAN.md so the README/`plan_qa` completion story is
  unchanged. So the honest recommendation is **subsume the diary, keep a curated milestone/delivery
  stub** — not a pure replace.
- **Why subsume rather than coexist-fully**: two live time-series logs (Notes & Updates *and* JOURNAL)
  guarantees drift and double-writing. One diary (JOURNAL), one curated summary (PLAN.md milestones).
- **Migration cost is a template edit, not a check edit**: `plan_qa` never asserts a Notes & Updates
  section exists; `header_body_coherence` and `same_commit_plan_doc` key off status/tasks/prose, not
  Notes. Legacy plans keep their Notes & Updates untouched (grandfathered by not being rewritten).

---

## 4. Lifecycle touchpoints

| Moment                                 | Journal action                                                                                                                                | Who writes it |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **Plan creation**                      | `mkplan.bash` creates `JOURNAL/` + first day-file with a seeded `action` entry ("plan scaffolded")                                            | bash (mkplan) |
| **Phase start**                        | `action` entry naming the phase                                                                                                               | agent         |
| **Each task status flip** (⬜→🔄→✅)   | `action` entry ("started T2.1" / "T2.1 done — <one-line outcome>")                                                                            | agent         |
| **A finding / measurement / dead-end** | `finding` entry (the highest-value kind — see §5)                                                                                             | agent         |
| **A decision made in flight**          | `decision` entry; the resolved decision also lands in PLAN.md Technical Decisions                                                             | agent         |
| **Blocker hit / cleared**              | paired `blocker` entries                                                                                                                      | agent         |
| **Before compaction / end of session** | `handoff` entry: current state + next step (grounding for the resumer)                                                                        | agent         |
| **Plan completion**                    | final `handoff`/`action` entry summarising outcome + delivery commit(s); folder (incl. JOURNAL) `git mv`'d to `Completed/` in the same commit | agent         |

- **`mkplan.bash` scaffolds the journal** the same way it scaffolds PLAN.md — bash `mkdir JOURNAL && cat > JOURNAL/NNNNN-Journal-$(date +%y-%m-%d).md`. Same rationale as PLAN.md: written via bash so the
  daemon's numbering/write handlers aren't triggered. The seed entry doubles as a worked example of the
  grammar.
- **A project-owned journal template** (`CLAUDE/Plan/_JOURNAL_TEMPLATE_.md`, mirroring the Plan 00144
  `_TEMPLATE_.md` mechanism) lets clients customise the seed entry + header comment. Daemon deploy
  seeds it when missing, never overwrites.
- **Expected cadence is "on meaningful events", not per-tick.** Explicitly NOT a heartbeat and NOT one
  entry per tool call — that would recreate the idle-tick noise problem Plan 00161 is fighting.

---

## 5. Grounding value for future agents

**How a resumer actually uses it:**

- **Reconstruct context fast**: read the *latest* day-file's `handoff` entry first → "where was I".
  (Argues for reading **newest-first**; consider whether files render newest-day-first — filename sort
  is oldest-first, so a resumer opens the last file. Entries *within* a file stay chronological/append;
  a `handoff` at the tail is the entry point.)
- **Recover a rationale**: `rg "· decision" CLAUDE/Plan/NNNNN/JOURNAL/` → every choice with its
  in-flight reasoning, including the ones that PLAN.md's curated Technical Decisions compressed away.
- **Understand an abandoned path**: `rg "· blocker|dead.end|abandoned"` → *why* a direction was
  dropped, so the resumer doesn't re-walk it. This is the single biggest thing PLAN.md **cannot**
  carry — PLAN.md shows the *current* plan, never the roads not taken.
- **Audit a claim**: findings carry evidence (commands, captures) inline, like 00158's live-capture
  "CONFIRMED TRUTH" notes.

**What makes an entry genuinely useful:**

- Specific, timestamped, references a task/file/commit, and records the **WHY** and the **outcome**,
  not just the action. "T2.1 done — sidecar keys by session_id so per-thread state needs a new store"
  beats "worked on task 2.1".
- A dead-end entry states *what was tried and why it failed* so it's not retried.

**Anti-patterns to discourage (name them in the reference doc):**

- Restating PLAN.md (the plan is not the diary).
- Vague filler: "made good progress", "should be fine", "looking good" (also trips the repo's
  `dismissive_language_detector` / hedging advisories).
- Per-tool-call spam / heartbeat entries.
- Editing or backdating prior entries (breaks append-only grounding — correct with a *new* entry).
- Dumping a 500-line log with no one-line takeaway above the fence.
- Motivational/roleplay prose.

---

## 6. The reference doc: `CLAUDE/PlanJournalling.md`

A doc **client projects copy and fine-tune** ("ours is a reference, not set in stone"). It should be
deployed like the other reference artifacts and — per Plan 00161 Decision 6 — if it becomes a
daemon-managed skill/agent it takes the **`hooks-daemon-`** name prefix; as a plain doc it lands in the
client's `CLAUDE/` tree for them to edit.

**Proposed table of contents:**

1. **Purpose** — PLAN.md = the plan (what/why/state/tasks); JOURNAL = the linear activity log
   (what happened, when, findings, dead-ends). Complementary, not duplicative.
2. **File & folder layout** — `JOURNAL/NNNNN-Journal-YY-MM-DD.md`, one file per active day, timezone.
3. **Entry grammar** — heading contract, categories, optional machine header, body rules.
4. **Append-only discipline** — never edit priors; correct with a new entry; monotonic times.
5. **Lifecycle touchpoints** — the §4 table.
6. **PLAN.md vs JOURNAL** — what lives where; the Notes & Updates → Delivery-milestones migration.
7. **Good vs noise** — the §5 do/don't with worked examples.
8. **Customising this in your project** — which knobs are yours (below).

**Policy (daemon-enforced — do NOT let clients silently break) vs Convention (client-tunable):**

| Aspect                                                    | Policy / Convention                                  |
| --------------------------------------------------------- | ---------------------------------------------------- |
| Folder is `JOURNAL/` inside the plan folder               | **Policy** (so closure `git mv` and sweeps work)     |
| Filename `NNNNN-Journal-<date>.md`, NNNNN = plan number   | **Policy** (parser + grep contract)                  |
| Date granularity = one file per day, local tz             | **Policy** (append semantics depend on it)           |
| Append-only / monotonic entries                           | **Policy** (the whole value proposition)             |
| Journal moves with the folder on completion               | **Policy** (implied by layout; free)                 |
| Exact category set / their names                          | **Convention** (project may add e.g. `review`, `qa`) |
| Heading `·` delimiter vs a machine HTML header            | **Convention** (pick your parseable form)            |
| Actor annotation on entries                               | **Convention** (solo vs team)                        |
| Cadence / which touchpoints are mandatory                 | **Convention** (project's rigor level)               |
| `YY-MM-DD` vs `YYYY-MM-DD`                                | **Convention** (but pick one and lint it)            |
| Retiring `## Notes & Updates` vs keeping a milestone stub | **Convention**                                       |

Mirror the Plan 00144 `_TEMPLATE_.md` split: the *structural* contract is daemon policy; the *content*
template (`_JOURNAL_TEMPLATE_.md`) is project-owned and never overwritten on upgrade.

---

## 7. Open questions & risks (need a human decision)

01. **`YY-MM-DD` vs `YYYY-MM-DD`.** User asked for 2-digit; 4-digit reuses `plan_qa`'s existing date
    regex and matches `Created`. Pick one.
02. **Newest-first vs oldest-first ordering** — filenames sort oldest-first; entries append
    chronologically. Do we want a `handoff`-at-tail convention as the resumer's entry point, or an
    explicit "latest state" pointer? (Affects how a resumer reads.)
03. **Notes & Updates fate** — full retire + `## Delivery & Milestones` stub (my recommendation), vs
    keep Notes & Updates for durable milestones only, vs coexist. Where exactly do **delivery commit
    hashes** live so the completion checklist + `plan_qa` story is unchanged?
04. **Mandatory vs advisory cadence** — is a missing journal a *block* (enforcement agent's call) or
    just advised? What is the *minimum* required (e.g. one entry at creation + one at completion)?
05. **Append-only enforcement depth** — convention-only, edit-time monotonic-time lint, or a
    git-diff append-only check? (Sibling agent owns the mechanism; the data model above supports all
    three.)
06. **Multi-agent / team writes** — concurrent sub-agents appending to the *same* day-file risks
    interleave/clobber (cf. Plan 00159 thread-safe tmp naming). Per-actor day-files
    (`NNNNN-Journal-YY-MM-DD-opus.md`) vs a single serialized file? Needs a call for team plans.
07. **Sub-agent journaling** — do sub-agents (like this brainstorm agent) write to the plan's journal,
    or only the orchestrator? Today sub-agents can't reliably use Write and return summaries to the
    parent; likely the orchestrator journals on their behalf.
08. **`plan_qa` sweep scope** — should the SessionStart sweep and `plan-qa --sweep` learn about journals
    (e.g. "in-progress plan with no journal in N days" staleness signal), or stay journal-agnostic in v1?
09. **British spelling** — user's doc name is `PlanJournalling.md` (double-l). The repo runs a
    `british_english` advisory; `Journalling` is the British form, so it's consistent — just confirm the
    canonical spelling before it's referenced in code/paths.
10. **Retro-fitting existing active plans** — do we backfill `JOURNAL/` for in-flight plans (00144,
    00158, 00161, …) or only new plans from `mkplan.bash` onward? (No-backfill is cleanest.)
