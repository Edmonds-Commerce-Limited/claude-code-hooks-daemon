# Supplementary Ruleset — Sub-folder `CLAUDE.md` files and `.claude/rules/` (Plan 00284)

**Scope**: follow-up to `REVIEW-fable.md` §E.4, per user direction: path-proximate
programming hints are "probably best kept where they are" — this document turns that
instinct into an operational ruleset. Incorporates the two decided constraints:
mandatory human/agent tree split (names configurable), and the first-class SSOT-QUOTE
mechanism. `.claude/rules/*.md` = pointer-only is DECIDED; §3 gives its operational
form.

---

## 1. Population survey (every sub-root `CLAUDE.md`, classified)

Ten files below root (census verified by filesystem walk, excluding `untracked/`,
`.claude/hooks-daemon/`, worktrees):

| File                                     | Lines | Classification                                                            |
| ---------------------------------------- | ----: | ------------------------------------------------------------------------- |
| `docs/CLAUDE.md`                         |    12 | **Pointer-only** (SSoT routing table) — exemplar                          |
| `.claude/skills/CLAUDE.md`               |    12 | **Pointer-only** (charter + routing table) — exemplar                     |
| `src/CLAUDE.md`                          |    68 | **Mixed**: ownership guard (qualifies) + copied procedure (general truth) |
| `tests/CLAUDE.md`                        |    56 | **Mixed**: same guard shape; duplicates `src/CLAUDE.md`'s procedure       |
| `src/.../handlers/status_line/CLAUDE.md` |    61 | **Mixed**: genuine module invariants + a derived-fact table               |
| `src/.../qa/CLAUDE.md`                   |   277 | **Path-proximate but API-restating** (generation candidate)               |
| `src/.../strategies/tdd/CLAUDE.md`       |   705 | **Mixed**: module contract + repo-wide general truth                      |
| `CLAUDE/CLAUDE.md`                       |   112 | **Misfiled**: hand-maintained prose index (stale) + tree governance       |
| `CLAUDE/development/CLAUDE.md`           |    49 | **Misfiled**: stale index + general audience taxonomy                     |
| `CLAUDE/Plan/CLAUDE.md`                  |    92 | **Mixed**: pointer opener + duplicated lifecycle procedure                |

### General-truth content found inside them (file:line)

1. **`src/CLAUDE.md:26-55` and `tests/CLAUDE.md:35-56`** — a full four-step
   bug-reporting procedure (diagnostic script invocation, untracked report location,
   required report contents, submission route). This is general truth owned by
   `BUG_REPORTING.md` (both files even end by linking it), stated three times total,
   and the two guard-file copies are near-identical to each other — the exact shape
   the SSOT-QUOTE mechanism exists for. The guard sentence itself ("DO NOT EDIT —
   upstream dependency") is legitimately local; the procedure is not.
2. **`src/.../strategies/tdd/CLAUDE.md:7`** — "Any future handler that needs
   language-specific behaviour MUST follow this pattern exactly", plus §"Applying
   This Pattern to Other Handlers" (`:615-658`, naming future domains) and the
   design-principles recap (`:516-551`, restating CLAUDE.md's SOLID/DRY/NO-MAGIC
   text). A repo-wide mandate addressed to readers working in OTHER subtrees
   (lint, security, pipe-blocker strategies) — general truth in a module doc. The
   per-method Protocol contract (`:93-161`) and add-a-language walkthrough
   (`:376-495`) are, by contrast, genuinely path-proximate.
3. **`src/.../handlers/status_line/CLAUDE.md:9-18`** — a handler/priority table.
   Verified: its priorities (git_repo_name 3, account_display 5) match the SOURCE
   defaults (`constants/priority.py:216,218`) but disagree with the LIVE-config
   rendering in generated `.claude/HOOKS-DAEMON.md` (25 and 40), with no note that
   the two tables answer different questions (defaults vs this repo's overrides). A
   derived fact restated outside its generator — R5 violation, and a reader-facing
   contradiction today. The thread-safety contract (`:21-55`) is the best
   path-proximate content in the repo — but `:53-55` says the "paired guidance"
   also lives in `CLAUDE/Architecture/StatusLine.md`, i.e. the three rules exist in
   two prose homes with no quote linkage.
4. **`src/.../qa/CLAUDE.md:16-57`** — class-by-class, method-by-method API listing
   restating what the module's docstrings say (`run_ruff()`, field lists, parser
   helpers), plus tool-output format samples (`:107-207`). Its external references
   check out today (`scripts/run-qa-runner.sh`, `tests/unit/test_qa_runner.py` both
   exist), but an API restatement drifts on the next refactor by construction.
5. **`CLAUDE/Plan/CLAUDE.md:3` vs the rest** — opens "See `@CLAUDE/PlanWorkflow.md`
   for full planning workflow", then carries its own five-stage lifecycle including
   a completion checklist that PlanWorkflow.md also owns (REVIEW-fable A.2 finding
   10 territory: three plan-template/lifecycle homes).
6. **`CLAUDE/CLAUDE.md:14-70` and `CLAUDE/development/CLAUDE.md:22-25`** — stale
   hand-maintained prose indexes (REVIEW-fable A.4), plus general audience taxonomy
   (`development/CLAUDE.md:5-20` defines user-vs-development doc split — that
   belongs in `DocumentationStrategy.md` once it exists).

**Note on the two trees**: `CLAUDE/CLAUDE.md`, `CLAUDE/development/CLAUDE.md` and
`CLAUDE/Plan/CLAUDE.md` sit INSIDE the agent tree, so the sub-CLAUDE.md rules below
apply to them only in their routing role — canonical-tree content belongs in named
files, and their indexes fall under REVIEW-fable R7d (generate or delete). The
interesting population is the four under `src/`+`tests/`: docs living beside code.

---

## 2. Ruleset for sub-folder `CLAUDE.md` files

**Why they exist (and why the ruleset must protect them)**: Claude Code auto-loads a
`CLAUDE.md` when the agent works under its directory. That is a third matching
mechanism alongside `.claude/rules` (path-glob) and skills (intent): **proximity**.
It is the only one that follows the code when files move with their folder, and it
needs zero configuration. The user's instinct — path-proximate programming hints
stay put — is architecturally right: relocating the status_line thread-safety
contract to the far side of the repo would break the guarantee that an agent editing
those files has read it. The corollary is equally important: auto-loading means
every line is a recurring context cost paid by every session touching the subtree —
the same economics as `PLAN.md`, and the reason a budget survives the content-class
test (S6).

**S1 — The OUTSIDE-READER test (operational test for "purely related to files in
this folder").** Content belongs in a sub-CLAUDE.md iff its intended reader is an
agent about to create or modify files in THIS subtree, and removing the subtree
would make the content meaningless. Ask: *would a reader working anywhere else in
the repo ever need this?* If yes, it is general truth → canonical tree (agent tree
owns depth, per the decided split), with the module doc quoting or pointing.

Qualifying content classes:

- **(q1) Ownership/edit guards** — "do not edit, upstream dependency", "generated,
  edit the source" (`src/CLAUDE.md:1-9` minus the copied procedure).
- **(q2) Module-local invariants and contracts** — concurrency rules, ordering
  constraints, fail-silent requirements that code in this folder must satisfy
  (`status_line/CLAUDE.md:21-55` is the archetype).
- **(q3) Local build/run/test commands** — how to run THIS module's tests, this
  folder's scaffolding commands.
- **(q4) Editing gotchas** — "changes here are inert until X reloads", "this file
  is rewritten by Y on restart".
- **(q5) Local conformance walkthroughs** — how to add a new strategy/handler *in
  this folder*, provided the governing pattern itself is canonical elsewhere and is
  linked (the tdd doc's add-a-language steps qualify; its "all future handlers
  repo-wide MUST" mandate does not).
- **(q6) A local file index** only if trivially small or generated (R7d applies
  here too).

Disqualifying content classes (each observed in §1):

- **(d1) Repo-wide mandates** — any sentence whose subject is code outside the
  subtree ("any future handler MUST…"). → canonical pattern doc; module doc points.
- **(d2) Procedures for actors elsewhere** — bug reporting, release steps, plan
  lifecycle. → canonical doc; quote if the local copy must be self-contained.
- **(d3) Restated derived facts** — priority tables, handler rosters, check counts
  (R5). → name the generator (`.claude/HOOKS-DAEMON.md`, the constants module) or
  quote it.
- **(d4) API reference restating code** — docstrings are the SSoT for signatures;
  a hand-written mirror is a duplicate of the code itself. → delete or generate.
- **(d5) Tree governance / audience taxonomy / engineering-principles recaps** —
  `DocumentationStrategy.md` and root `CLAUDE.md` own these.

**S2 — Registered canonical homes.** A sub-CLAUDE.md MAY be the canonical home for
facts whose subject is its own module — but only by REGISTRATION (a config list,
`documentation.module_doc_registry` or similar). Registration is what lets the
checker and the docs-qa agent treat it as a legitimate depth-owner instead of a
satellite that grew. Unregistered sub-CLAUDE.md files are held to the routing/guard
budget (S6). Registration resolves the status_line two-homes problem in either
direction: EITHER `CLAUDE/Architecture/StatusLine.md` owns the thread-safety rules
and the module doc quotes them (S3), OR the module doc is registered as the owner
and StatusLine.md quotes back — one owner, the quote mechanism carries the text to
the other location verbatim-and-verified. Recommendation: the AGENT-TREE doc owns
system-level architecture; the module doc owns the "before you edit files here"
rendering — and whichever statement is longer is usually the owner.

**S3 — SSOT-QUOTE application.** Where a module doc needs canonical text
self-contained at point of use (guards especially — their whole value is being
un-missable), it embeds a quote block wrapped in metadata naming source file +
anchor, e.g.:

```markdown
<!-- ssot-quote source="BUG_REPORTING.md#reporting-steps" -->
…verbatim excerpt…
<!-- /ssot-quote -->
```

The checker extracts the excerpt, resolves the anchor in the source, and compares
normalised text: match = compliant duplication; mismatch = a mechanical drift
finding naming both files. This converts the three worst §1 findings from
"duplication" to "verified quotes": the bug-report procedure in `src/` and `tests/`
guards, the status_line paired rules, and the plan-lifecycle steps in
`CLAUDE/Plan/CLAUDE.md`. Rule: **a sub-CLAUDE.md never RESTATES canonical content —
it points, or it quotes with metadata.** An unquoted near-copy is the violation.

**S4 — Fate decision per file** (applying S1–S3 to the survey):

- `src/CLAUDE.md`, `tests/CLAUDE.md`: keep as guards; convert the procedure to an
  ssot-quote of `BUG_REPORTING.md` (or a bare pointer — quote only if the
  self-contained rendering is judged load-bearing for client repos, which it
  plausibly is: these files ship into installs where following a relative link is
  friction at exactly the wrong moment).
- `status_line/CLAUDE.md`: keep; delete or generator-source the priority table
  (d3); settle rule ownership with StatusLine.md via S2+S3.
- `qa/CLAUDE.md`: shrink to purpose + usage + integration points; drop the API
  mirror and output-format samples (d4) or generate them.
- `strategies/tdd/CLAUDE.md`: REGISTER as the canonical Strategy-Pattern archetype
  (it self-declares as such and is the best pattern doc in the repo) — but move the
  repo-wide mandate sentence and "Applying This Pattern to Other Handlers" into
  `CLAUDE/HANDLER_DEVELOPMENT.md` (which already owns "use Strategy Pattern for
  language-aware handlers") with a link INTO the registered module doc for the full
  contract; drop the SOLID/DRY recap (d5).
- `CLAUDE/CLAUDE.md`, `CLAUDE/development/CLAUDE.md`, `CLAUDE/Plan/CLAUDE.md`:
  reduce to routing tables on the `docs/CLAUDE.md` model; promote the audience
  taxonomy into `DocumentationStrategy.md`; the plan lifecycle collapses into
  PlanWorkflow.md with a quote if needed.

**S5 — Client parameterisation.** The registry (S2), the guard exemption (q1 is
daemon-shipped content in client repos), and the budget tiers (S6) are all config.
A client with template-generated sub-CLAUDE.md files gets the same grandfathering
as everything else (R12).

**S6 — Budget: yes, still needed, but as tiers not a cap.** The content-class test
bounds WHAT; auto-loading economics bound HOW MUCH. Unregistered sub-CLAUDE.md:
routing/guard budget (advisory above ~40 lines — both guards and the exemplar
routing tables fit). Registered module docs: plan-doc-size-style tiers (advisory /
escalated / grow-blocked at generous thresholds), because a 705-line auto-loaded
doc taxes every session in that subtree exactly as an oversized PLAN.md taxes every
session touching the plan. Grow-only blocking with the standard
`MUST_EXCEED_..._BECAUSE` escape; ssot-quote blocks count at a discount (they are
verified, not drift-prone) — or are excluded from the count entirely, which also
removes the perverse incentive to point instead of quote purely to stay under
budget.

---

## 3. `.claude/rules/*.md` — operational form of the decided pointer-only contract

**Compliant shape** (the whole file):

1. YAML frontmatter: `paths:` globs + one-line `description:` (both files already
   have this — keep as-is).
2. Body budget: ≤ ~15 lines / ≤3 sentences of orientation (R4's pointer test),
   comprising: the trigger statement ("you are reading this because you touched
   X"), the RULE in at most two imperative lines, and one or more links — to the
   agent tree, or to a relevant registered `CLAUDE.md` (both targets explicitly
   permitted by the user's direction).
3. Forbidden in the body: fenced code blocks, tables, numbered procedures,
   ssot-quote blocks (a rules file points; if the text must travel, the TARGET
   carries it — rules fire on path-touch, where brevity is the feature), and any
   normative content not present in the linked target.
4. Transition rule: a rules file may not be thinned by deleting its content —
   promote the content to (or verify it already exists in) the canonical home
   FIRST, then thin. The checker should treat a rules-file shrink that has no
   corresponding canonical-doc growth in the same commit as an advisory (the
   plan-shrink-without-journal shape, transplanted).

**Audit of the two existing files against this contract — both non-compliant:**

- **`.claude/rules/importing-reports.md`** (82 lines): frontmatter compliant
  (`:1-6`). Body carries the strip/replace table (`:28+`), the incident narrative
  (`:23-26`), and the report-fates procedure — all general truth that root
  `CLAUDE.md`'s "Report Handling" section already states at length (two full copies
  today, REVIEW-fable "Also noted"). Remediation: designate one canonical home for
  the sanitisation policy (the agent tree — a `CLAUDE/` doc or the existing root
  section), then reduce this file to trigger + rule ("this repo is public; read the
  report in full and strip reporter identifiers before committing") + link.
- **`.claude/rules/ccy-supervisor-dogfooding.md`** (67 lines): frontmatter
  compliant. Body is the ONLY copy in the repo of the worker hot-reload contract
  (content-hash + mtime pre-check, `:22-31`), the bare-`touch`/`cp -p` traps, and
  the verify-the-pid procedure (`:43-54`). Nothing to point at exists — the
  transition rule bites: create the canonical home first (natural candidates: a
  registered `.claude/ccy/CLAUDE.md` module doc — this is exactly q2/q4 content
  co-located with the files it governs — or `CLAUDE/Architecture/`), then thin the
  rule to trigger + link. Until then this file is grandfathered, not deleted:
  losing the only copy is worse than the shape violation.

---

## 4. Enforcement mapping (per REVIEW-fable R13)

| Check                                                                                                                   | Instrument                                                                                                                                               | Notes / FP assessment                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rules-file shape (frontmatter present; body line budget; contains ≥1 link; no fences/tables/numbered lists)             | DETERMINISTIC — edit-time + sweep                                                                                                                        | Structure-only, near-zero FP; grandfather the two existing files until remediated                                                                                    |
| Rules-file thinned without canonical-doc growth in same commit                                                          | DETERMINISTIC — commit gate, advisory                                                                                                                    | Same-commit heuristic can miss legitimate two-commit moves — advisory only                                                                                           |
| ssot-quote verification (excerpt vs source anchor, normalised)                                                          | DETERMINISTIC — edit-time (quote blocks in the written file) + bulk/sweep (source-side edits must re-verify all quoting files, needing the corpus index) | Mechanical diff; whitespace/mdformat normalisation required (the table formatter rewrites quotes — normalise before compare or quotes false-drift on pipe alignment) |
| Unquoted near-copy of canonical text inside a sub-CLAUDE.md or rules file                                               | DETERMINISTIC core (exact-block hash, D.2) + AGENT penumbra (paraphrase)                                                                                 | As in the main review                                                                                                                                                |
| Sub-CLAUDE.md registry + budget tiers (unregistered ~40-line advisory; registered plan-doc-size tiers, grow-only block) | DETERMINISTIC — edit-time                                                                                                                                | Size-only triggers are advisory below the block tier; the escape hatch keeps it honest                                                                               |
| Derived-fact table inside a sub-CLAUDE.md (d3)                                                                          | DETERMINISTIC for registered facts (D.4)                                                                                                                 | The status_line priority table would be caught only if handler-priority is a registered fact — recommend it is (the generator exists: `generate-docs`)               |
| OUTSIDE-READER test — does this content serve readers beyond the subtree? (d1/d2/d5)                                    | AGENT                                                                                                                                                    | Semantic by nature; the docs-qa agent audits sub-CLAUDE.md files as a named scan topic, pre-seeded with size/duplication hits                                        |
| API-mirror detection (d4)                                                                                               | AGENT                                                                                                                                                    | "Does this prose restate the module's own docstrings?" needs reading both — judgement                                                                                |
| Register-vs-shrink recommendation for a grown module doc                                                                | AGENT → human                                                                                                                                            | The agent proposes with evidence; registration is a config change, i.e. the human's act                                                                              |

---

## Summary of recommendations

1. Adopt the OUTSIDE-READER test (S1) with the six qualifying / five disqualifying
   content classes as the operational rule for sub-CLAUDE.md files — it preserves
   the user's "keep path-proximate hints where they are" while giving the checker
   and agent a decidable question.
2. Introduce the module-doc REGISTRY (S2): registered = legitimate canonical home
   with generous size tiers; unregistered = guard/routing budget. Register
   `strategies/tdd/CLAUDE.md` (minus its repo-wide sections); settle
   status_line rule ownership via registry + ssot-quote.
3. ssot-quote blocks are the bridge for guard files that must be self-contained
   (`src/`, `tests/` bug-report procedure) — normalise against mdformat before
   comparing, and exclude verified quotes from size budgets.
4. Rules-file contract: frontmatter + ≤15-line body + link(s), no fences/tables/
   quotes; both existing rules files are non-compliant, and
   `ccy-supervisor-dogfooding.md` must have its content PROMOTED (it is the only
   copy) before it can be thinned — encode that ordering as the transition rule.
