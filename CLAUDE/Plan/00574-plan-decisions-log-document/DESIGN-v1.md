# Plan 00574 design: PLAN-DECISIONS.md

Supporting doc for [PLAN.md](PLAN.md). Unbounded by contract; edit in place.

## 1. Research findings (current state)

| Topic              | Finding                                                                                                                                                                                                               | Cite                                                                                                      |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Size limits        | Tiers apply to PLAN.md only; trip on bytes OR lines; block only when an edit grows the file; escape hatch `MUST_EXCEED_PLAN_SIZE_BECAUSE`                                                                             | `plan_qa/checks/plan_doc_size.py:18-30`, `plan_qa/types.py:60-62`, `:86-103`                              |
| Scope classifier   | `classify` returns one `PlanFileKind`; anything not `PLAN.md` in a plan folder is `SUPPORTING_DOC`; journals exempt from every plan-document rule                                                                     | `plan_qa/paths.py:45-58`, `:61-65`, `:228-236`                                                            |
| Supporting docs    | Unbounded, edit in place, read on demand; the doc already names `DECISIONS.md` as an example                                                                                                                          | `CLAUDE/PlanJournalling.md:47-58`, `:111-113`                                                             |
| Shrink guard       | Sharp PLAN.md shrink must stage a journal entry or a new supporting doc, so extracting to the log satisfies it                                                                                                        | `plan_qa/checks/plan_shrink_without_journal.py:93`                                                        |
| Task grammar       | Tasks are `- [ ] ⬜ **Task N.N**: ...`; ids are the referent for decision links                                                                                                                                       | `plan_qa/checks/task_grammar.py:33-35`, `plan_qa/model.py:207`                                            |
| mkplan scaffold    | Creates folder and PLAN.md from `_TEMPLATE_.md`; JOURNAL/ is gated on `_JOURNAL_TEMPLATE_.md`; `--journal` stamps UTC time, writes one new file per entry                                                             | `CLAUDE/Plan/mkplan.bash:13-15`, `:94-101`, `:486-630`                                                    |
| Journal categories | `decision` already a legal category                                                                                                                                                                                   | `plan_qa/model.py:369`                                                                                    |
| Markdown location  | Plan folder allows `PLAN.md`, supporting docs, JOURNAL entries, subagent-reports                                                                                                                                      | `CLAUDE/DirectoryRoles.md:39`; guard in `handlers/pre_tool_use/markdown_organization.py`                  |
| Client deploy      | `mkplan.bash` and `_planlib.inc.bash` daemon-owned (overwritten); `_TEMPLATE_.md`, `_JOURNAL_TEMPLATE_.md`, `PlanJournalling.md` client-owned (seeded, never overwritten); core docs via `CLAUDE/core/<Name>.core.md` | `install/plan_workflow.py:50-66`, `:232-239`, `:302-303`, `:348-357`; `install/core_docs.py:14`, `:71-89` |
| CLI                | `plan-qa` command exists and is the model for a sibling lookup                                                                                                                                                        | `daemon/cli.py:8609`                                                                                      |

Conclusion: no size rule needs relaxing. Supporting docs are already unbounded; the gap is
convention, scaffolding, grammar, lookup and QA. The log must be a distinct file kind
(Task 1.3) so QA can apply decision rules without reintroducing plan-document rules.

Open point for Task 1.3: confirm in `plan_qa/checks/common.py` and the markdown-location
guard that a new top-level name needs no allowlist change (supporting docs appear to pass).

## 2. Entry grammar

One heading per decision, then a fixed body:

```
## D-0007 · T2.3,T2.4 · accepted · owner — short title
```

Fields, separated by `·`: stable id `D-NNNN` (allocated by the tool, never reused);
comma-separated task ids (`T2.3`, or `T-` for plan-wide); status; decider; title after
an em dash. Parse regex is anchored to `^## D-\d{4} · `, so a grep for `^## D-` lists all
and `grep 'T2\.3'` on heading lines finds a task's decisions.

Body sections, in order, as bold labels: **Context**, **Options** (bullets, each with the
reason it was kept or rejected), **Decision**, **Consequences**, **Links**
(`PLAN.md#task-2-3`, journal entry paths, supersedes/superseded-by ids).

Status: `proposed`, `accepted`, `superseded`, `reversed`. Decider: `owner`, `agent`,
`stand-in` (matches the stand-in ruling shape in `CLAUDE/SessionModes.md`).

## 3. Write rules

- Append-only for decisions: new entries via `mkplan.bash --decision`, which allocates the id
  and refuses unknown task ids (read from PLAN.md).
- A status change is a new entry (`supersedes D-0007`); the old entry's heading status is
  the single permitted in-place edit (`accepted` to `superseded`) and gets a `Superseded-by` line.
  Alternative to settle in Task 1.1: make even that a tool command (`--decision-status`).
- Body text of an existing entry is never rewritten (parallel to journal discipline).
  Typos are fixed by a new entry. Unlike the journal, the file is one document, so
  merge conflicts are possible; the tool appends at EOF and QA flags duplicate ids so
  a conflict resolution that collides ids is caught.

## 4. Lookup

`hooks-daemon plan-decisions <plan> [--task N.N] [--status S] [--decider D] [--json]`.
`<plan>` accepts number or name (same resolution as `find-plan`). Documented fallback:
`grep -n '^## D-.*T2\.3' CLAUDE/Plan/<folder>/PLAN-DECISIONS.md`.

## 5. QA checks

| Check                       | Stage        | Rule                                                                                                                                |
| --------------------------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| decision-task-exists        | edit, commit | each task id in a heading exists in PLAN.md (advise for archived plans)                                                             |
| decision-id-unique          | edit, commit | ids unique and well-formed                                                                                                          |
| decision-supersede-resolves | edit, commit | supersede and superseded-by ids exist; statuses consistent                                                                          |
| plan-links-decisions        | sweep        | PLAN.md that embeds a block headed `Decision` over a threshold, or has a log with entries but no link to it, advises (never blocks) |

No size check applies to the log. Journal links are checked by the existing
`plan-link-resolves` check.

## 6. Interlinking (DRY)

- Task line in PLAN.md ends with `Decisions: D-0007` links; PLAN.md holds only the
  one-line outcome, never the reasoning.
- Each decision links the task and any journal entry holding the evidence.
- Journal `decision` entries for task-linked choices say `see D-NNNN` instead of
  restating.

## 7. Migration (optional)

Per plan, when it next hits a size tier: move each embedded decision into the log as an
entry with `accepted` and the original decider, replace the PLAN.md text with a link,
and stage the new file (satisfies `plan-shrink-without-journal`). Plans are never
migrated in bulk; completed plans are left alone.

## 8. Risks

- Template drift in clients: the new template is client-owned and seeded only when absent,
  so `--decision` must fall back to an embedded default heading when it is missing.
- `--decision` id allocation under concurrent branches: use the lock mkplan already takes.
- Docs SSoT: the grammar lives only in `PlanJournalling.md` or `PlanWorkflow.md`
  (decide in Task 4.1); other docs link, never restate.
