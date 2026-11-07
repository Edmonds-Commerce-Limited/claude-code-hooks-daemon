# Plan 00574 design v2: the decision log (`DECISIONS.md`) and the lean PLAN.md

Supporting doc for [PLAN.md](PLAN.md). Supersedes [DESIGN-v1.md](DESIGN-v1.md) (kept for history). Driven by [CRITIQUE-v1.md](CRITIQUE-v1.md); the first draft is [PLAN-v1.md](PLAN-v1.md). Unbounded by contract; edit in place.

Paths below are under `src/claude_code_hooks_daemon/` unless they start with `CLAUDE/`.

## 1. Verified facts (re-checked against `main`)

| Fact                                                                                                                                                   | Cite                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| Size tiers bind PLAN.md only; blocks only an edit that grows the file                                                                                  | `plan_qa/checks/plan_doc_size.py:18-30`, `plan_qa/types.py:60-62`, `:86-103`                 |
| Any non-PLAN `.md` in a plan folder is `SUPPORTING_DOC`: unbounded, edit in place, read on demand                                                      | `plan_qa/paths.py:228-236`, `CLAUDE/PlanJournalling.md:47-58`                                |
| Remedy wording SSoT is `plan_qa/remedy.py`; the EXTRACT remedy already names `DECISIONS.md`                                                            | `plan_qa/remedy.py:43-52`, rendered at `plan_doc_size.py:68-72`                              |
| `plan-shrink-without-journal` accepts only a NEW (`A`) supporting `.md`; a modify never counts                                                         | `plan_qa/checks/common.py:584-614`                                                           |
| `_folder_has_supporting_docs` is true for any non-PLAN `.md`, so a pre-created stub silences the "notepad" hint                                        | `plan_qa/checks/plan_doc_size.py:127-142`                                                    |
| Journal appends deliberately take no lock (Plan 00427 D6a); one file per entry removed the append conflict (Plan 00543)                                | `CLAUDE/Plan/mkplan.bash:500-508`, `:486-497`, `CLAUDE/PlanJournalling.md:244-257`           |
| Planning mode creates `NNNNN-name/PLAN.md` itself, bypassing mkplan                                                                                    | `handlers/pre_tool_use/markdown_organization.py:855-870`                                     |
| `PlanJournalling.md` routing row sends "why was option B rejected" to JOURNAL                                                                          | `CLAUDE/PlanJournalling.md:36-41`                                                            |
| `DECISIONS.md` exists in 16 plan folders; 17 niggle-ledger folders key by N-id                                                                         | critique H4, M2 (corpus counts, reviewer-measured)                                           |
| Grammar SSoT must live in a daemon-owned doc: `PlanJournalling.md`, `_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md` are client-owned, seeded only when absent | `install/plan_workflow.py:50-66`, `:344-360`; core docs: `install/core_docs.py:14`, `:71-89` |

## 2. What actually bloats PLAN.md (critique measurements, accepted)

Over 52 plans at or above 18,000 bytes: Tasks about 48 percent of H2 bytes, decision/design/rationale sections about 11 percent, progress logs about 8 percent, evidence about 7 percent. Inside Tasks (32 large recent plans), post-delivery "Outcome:" narrative dominates (about 46 percent), then spec and test lists (about 30), then decisions (about 23); an order-of-magnitude figure only. Only 11 of 175 plans numbered 00400 or higher reach the advisory tier, so the existing rules already work for most plans.

So the decision log is one of three levers, and the plan treats it that way:

| Bulk                                                                       | Home                                                 | PLAN.md keeps                                |
| -------------------------------------------------------------------------- | ---------------------------------------------------- | -------------------------------------------- |
| Decision with rationale: options, ruling, "open questions", rulings tables | `DECISIONS.md`                                       | one-line task outcome with a `[D-...]` link  |
| Post-delivery outcome narrative under a ticked task                        | `JOURNAL/` entry (via `mkplan.bash --journal`)       | one outcome line, optionally the commit hash |
| Task spec and test lists                                                   | a named supporting doc (`SPEC-*.md`, or `DESIGN.md`) | the task title and a link                    |

## 3. Name, kind and write contract

- **Name: `DECISIONS.md`** (existing convention, 16 plans, already in remedy.py). The v1 name `PLAN-DECISIONS.md` is dropped: it forks a convention and its `PLAN-` prefix collides with `PLAN-v1.md`. Critique H4 accepted.
- **Kind: an ordinary `SUPPORTING_DOC`**, edited in place, git is the history, unbounded. No new `PlanFileKind`, no fourth contract, no in-place-heading-edit exception. Critique M3 accepted; v1 Task 1.3 dropped. Checks detect the file by filename inside the existing kind.
- **Supersede by adding, not rewriting** is guidance in the grammar doc, not a tool-enforced rule: add a new entry with `Supersedes:` and set the old entry's status to `superseded` with a `Superseded-by:` line. Git preserves the original text.

## 4. Grammar

One H2 per decision:

```
## D-261107T1432-a3f · Task 2.3 · accepted · owner — short title
```

Fields separated by `·`:

1. Id: `D-` then `YYMMDDTHHMM` (UTC) then `-` and 3 hex chars. Collision-free with no allocator.
2. Refs, free-form but typed, comma separated: `Task 2.3`, `N330`, `plan` (plan-wide or planning-time). Covers niggle ledgers (N-ids) and decisions that precede tasks (M2).
3. Status: `proposed`, `accepted`, `superseded`, `reversed`.
4. Decider: `owner`, `agent`, `stand-in`.
5. Title after an em dash.

Body, bold labels in order: **Context**, **Options** (each with why kept or rejected), **Decision** (verbatim quote for an owner ruling), **Consequences**, **Links** (`Supersedes:`, `Superseded-by:`, task, journal entry paths).

Parse anchor: `^## D-\d{6}T\d{4}-[0-9a-f]{3} · `. Lookup by task, anchored so `Task 2.3` does not match `Task 2.30`:

```
grep -nE '^## D-.* · (.*, )?Task 2\.3(, .*)? · ' DECISIONS.md
```

(The exact regex is finalised and tested in Task 1.1.) Outside the file, always cite with the plan number (`00574/D-261107T1432-a3f`) because plan-local `Dn` names already recur across plans (L2).

Legacy files: the 16 existing `DECISIONS.md` files use `## Decision N:` or `## DN:` headings. They are grandfathered from the grammar check by plan number (at or below 00574), using the same style of scoping as `journal_in_commit_scope`. Not migrated, not flagged.

## 5. Ids and merge safety (decision: stamp ids in one file)

Options considered:

| Option                                                  | Verdict                                                                                                                                                                                                                                                        |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Sequential `D-NNNN` from a tool                         | Rejected. The mkplan lock is per clone and cannot make two worktrees agree; appends deliberately avoid it (mkplan.bash:500-508); a renumber after collision corrupts append-only journal references (H2).                                                      |
| One file per decision under a folder (Plan 00543 style) | Rejected for now. Decisions are rare next to journal entries, so append conflicts are rare; a folder breaks the one-readable-document property, the existing 16 `DECISIONS.md` files, and the single grep. Revisit if conflicts are observed (Phase 3 option). |
| **Stamp id plus single file**                           | **Chosen.** Ids never collide, never need renumbering, so references are permanently stable. Two branches appending at EOF still give a textual conflict, but the resolution is "keep both sides", with no semantic change.                                    |

Conflict handling: document "keep both" in the grammar doc. Deferred: teach `mkplan.bash --resolve-conflict` to union `DECISIONS.md` (it already unions legacy day-files).

## 6. Scaffold: lazy creation (decision)

Pre-creating an empty file would (a) make every later extraction a Modify, which the shrink guard ignores (H3), (b) silence the notepad hint (H6), and (c) leave an empty stub in 535 of 551-style plans (L1). The owner asked for pre-creation (discoverability); the cheaper way to keep that benefit is:

- `_TEMPLATE_.md` header gets `**Decisions**: [DECISIONS.md](DECISIONS.md) (created on first decision)`, visible in the file every session reads; a lookup of a missing file is harmless.
- `mkplan.bash` creates `DECISIONS.md` from `_DECISIONS_TEMPLATE_.md` **only** via `mkplan.bash --decision-init <plan>` (Phase 3, optional) and the grammar doc tells agents to copy the template on the first entry. Pre-creation at plan birth is rejected with this reason; if the owner insists, pre-create AND ship the H3/H6 fixes in Phase 1 (they are in the plan anyway, because a modify-extraction into an existing legacy `DECISIONS.md` is already misclassified today).
- Planning-mode plan folders get the same header via `_TEMPLATE_.md`-independent text: the guard's plan-content hint, not the file, carries the pointer (Task 2.3), so no second creation path is needed.

## 7. Agent levers (the point at which agents choose a home)

- `plan_qa/remedy.py`: EXTRACT names `DECISIONS.md` for decisions and a `SPEC-*.md` for task spec lists; RELOCATE names ticked-task "Outcome:" narrative explicitly (keep one line, move the rest to JOURNAL); `plan_doc_size.py` interpolates the plan folder's actual decisions path.
- `plan_doc_size._folder_has_supporting_docs`: ignore a `DECISIONS.md` with no decision entries (guard for a future stub).
- `has_staged_supporting_doc`: also accept a staged Modify of `DECISIONS.md` whose added lines include a decision heading. Test: extraction-shaped commit into an existing log gives no finding.
- `plan_workflow` handler guidance and the daemon-owned `PlanWorkflow.core.md` carry the grammar and routing rule, so existing installs receive them.
- Optional advisory sweep: a ticked task whose body exceeds N lines points at the remedy (Phase 3).

## 8. Routing rule (one SSoT, other rows redirected)

| Content                                                       | Home                                                                                                                   |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Decision with rationale about this plan's work                | `DECISIONS.md` only; journal may say "recorded 00574/D-... " in one line                                               |
| Transient in-session choice that will not outlive the session | JOURNAL `decision` entry                                                                                               |
| Chosen design as current state                                | `DESIGN.md`; options and rejected alternatives link to the log                                                         |
| Owner rulings                                                 | log entry, decider `owner`, verbatim quote; stop creating `OWNER-RULINGS-*.md` and `DECISION-<topic>.md` for new plans |
| `OWNER-DECISIONS.md` (questions briefing)                     | may remain; answers land in the log                                                                                    |
| `CRITIQUE-vN.md`                                              | stays a review artefact; accepted points that change the plan become entries                                           |

The PlanJournalling routing row "Why was option B rejected mid-flight? | JOURNAL" is changed to point at `DECISIONS.md`.

## 9. QA scope (minimum viable)

One new check `decisions-grammar`: every H2 in a non-grandfathered `DECISIONS.md` matches the heading, ids unique, `Supersedes:`/`Superseded-by:` targets exist, at edit and commit stages. Refs existence (`Task N.N` in PLAN.md) is advisory and sweep-only because tasks are renumbered and niggle ledgers key by N-id (M2). `plan-links-decisions` and a lookup CLI are Phase 3, only if grep proves insufficient (M1). No size check applies to the log (test).

## 10. Critique dispositions

| Point                               | Disposition                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| H1 wrong target                     | Accepted: section 2, Phase 2 remedy and routing tasks                                                                                 |
| H2 ids / merge                      | Accepted: section 5                                                                                                                   |
| H3 shrink guard                     | Accepted: section 7, Task 2.2                                                                                                         |
| H4 name                             | Accepted: `DECISIONS.md`, grandfathering                                                                                              |
| H5 retire routes                    | Accepted: section 8                                                                                                                   |
| H6 remedy.py, hint                  | Accepted: section 7                                                                                                                   |
| M1 tooling weight                   | Accepted: writer and CLI to Phase 3                                                                                                   |
| M2 task keying                      | Accepted: typed free-form refs, advisory existence check                                                                              |
| M3 hybrid contract                  | Accepted: ordinary supporting doc; "append-only" becomes supersede guidance                                                           |
| M4 client drift, planning mode      | Accepted: grammar in core doc; planning mode handled via guidance, not scaffold                                                       |
| L1 empty stub                       | Accepted: lazy creation. Partially rejects the owner's pre-create ask; flagged for owner decision in Task 1.1                         |
| L2 id namespace                     | Accepted: cite with plan number                                                                                                       |
| Critique's `merge=union` suggestion | Rejected: `.gitattributes` is not deployed to clients and a union merge would silently keep both versions of an edited-in-place entry |
