# Triage — `duplicate-block` whole-repo sweep (Task 3.1f)

Hand-triage of the first real `bin/hooks-daemon docs-qa --sweep --json` run
against this repo's own doc corpus, per the 00208/00214 discipline the
design's `duplicate-block` row requires before any promotion past
advisory. This check has **no block-eligible path in code at all** (see
`docs_qa/checks/duplicate_block.py`'s module docstring) — this document is
the evidence trail for any future decision to add one.

## Method

`extract_structured_block_hashes` normalises every fenced code/command
block, markdown table, and 3+-item list run (the R4 structured classes)
through the same mdformat-gfm pipeline `quote-drift` uses, then hashes it.
A block below `MIN_BLOCK_LENGTH_CHARS` (120 normalised characters) is
never even considered a candidate — sized against the design's own worked
example, the recurring two-line `./bin/hooks-daemon restart` /
`./bin/hooks-daemon status` fence pair, which sits at ~54 raw characters.

The sweep was run against this repo's own live `.claude/hooks-daemon.yaml`
config, which already grandfathers `CLAUDE/UPGRADES/**` for `documentation.qa`
(pre-existing, R8/R9 rationale: versioned upgrade guides are historical
records). The CLI therefore reports 8 findings; the raw corpus scan (no
grandfather filter) surfaces 11 shared-block groups — the 3 extra are the
`CLAUDE/UPGRADES/**` ones triaged below for completeness, since the task is
to triage every finding the check CAN produce, not only the ones a given
project's config happens to show.

## Findings

| #   | Reporter → partner(s)                                                                                               | Shared content                                                                                                                                     | Verdict                                   | Reasoning                                                                                                                                                                                                                                                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | `.claude/agents/release-agent.md` → `CLAUDE/UPGRADES/upgrade-template/BREAKING-CHANGES-TEMPLATE.md`                 | A worked-example fenced snippet ending in a markdown link citing the v2.11-to-v2.12 upgrade guide, illustrating the template's own citation format | fixture/example-noise                     | `release-agent.md` cites the template's own worked example to show an agent what the template produces; the "duplication" is a doc explaining a template by quoting its example output, not two independent statements of the same fact drifting apart                                                                                                       |
| 2   | `CLAUDE/AgentTeam.md` → `CLAUDE/Worktree.md`                                                                        | A verbatim 3-step numbered procedure ("Checks venv exists…", "Runs `./scripts/qa/run_all.sh`…", "Reports pass/fail…")                              | true-duplication-worth-fixing             | A normative numbered procedure (R4's own example class) stated twice in two live, actively-edited docs — genuine drift risk. Already flagged independently in this plan's Task 3.2 dogfood-migration worklist (`AgentTeam.md`/`Worktree.md` both need `run_all.sh` → `llm_qa.py` + R5 cleanup), so this finding corroborates rather than discovers new scope |
| 3   | `CLAUDE/CodeLifecycle/General.md` → `CLAUDE/QA.md`                                                                  | The illustrative QA-runner console output block (`QA Summary` / `Magic Values : PASSED` / `Overall Status: ALL CHECKS PASSED`)                     | deliberate-idiom-candidate-for-ssot-quote | A worked example of the SAME tool's output, legitimately shown at two points of use (a lifecycle doc and the QA reference doc). Good candidate to wrap in `<!-- ssot-quote -->` against one canonical home rather than leave as an untracked copy                                                                                                            |
| 4   | `CLAUDE/AcceptanceTests/GENERATING.md` → `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md`                    | The three-layer test-safety rationale ("Layer 1 (echo)… Layer 2 (hooks)… Layer 3 (fail-safe args)…")                                               | archive-noise                             | The partner file is explicitly named `-archived` — a historical snapshot (R8) that should never be retro-edited to match the live doc. The live doc legitimately still carries the same rationale it inherited from the archived one                                                                                                                         |
| 5   | `CLAUDE/LLM-INSTALL.md` → `CLAUDE/LLM-UPDATE.md` (hash A)                                                           | The `.claude/hooks-daemon.yaml` header comment block describing how to restart the daemon after editing config                                     | deliberate-idiom-candidate-for-ssot-quote | Two sibling, both-live guides (install vs. update) that legitimately need the same boilerplate verbatim. `ssot-quote` is exactly the mechanism this shape exists for                                                                                                                                                                                         |
| 6   | `CLAUDE/Code/HooksSystem.md` → `CLAUDE/PROJECT_HANDLERS.md`                                                         | A python import snippet (`get_bash_command`, `get_file_path`, `get_file_content` from `core.utils`)                                                | true-duplication-worth-fixing             | Real API usage documentation, not an illustrative aside — if the utility module's import path or exported names change, both copies must be updated in lockstep and nothing currently enforces that. Candidate for canonicalising in one doc (or the module's own docstring) with the other pointing at it                                                   |
| 7   | `CLAUDE/LLM-INSTALL.md` → `CLAUDE/LLM-UPDATE.md` (hash B)                                                           | The `### Hooks Daemon` markdown snippet meant to be pasted into a downstream project's own `CLAUDE.md`/`README.md`                                 | deliberate-idiom-candidate-for-ssot-quote | Same sibling-guide relationship as #5; the snippet's own purpose is to be copied into someone else's file, but between these two guides it is still an untracked internal copy worth tracking via `ssot-quote`                                                                                                                                               |
| 8   | `CLAUDE/Plan/00100-venv-ssot-consolidation/PLAN-v1.md` → `CLAUDE/Plan/00100-venv-ssot-consolidation/PLAN.md`        | A "Release / What shipped / What broke" table                                                                                                      | archive-noise                             | `PLAN-v1.md` is the PlanWorkflow-convention superseded prior revision (`PLAN.md` → `PLAN-v1.md` + a fresh `PLAN.md`, per `CLAUDE/PlanWorkflow.md`'s "Review & Revise" step) — a frozen historical snapshot by design, not two docs independently stating the same fact                                                                                       |
| 9   | `CLAUDE/UPGRADES/upgrade-template/post-upgrade-tasks/README.md` → 7 versioned `post-upgrade-tasks/README.md` copies | The template's boilerplate 3-step reading procedure                                                                                                | archive-noise (already grandfathered)     | Every versioned copy is scaffolded FROM this template (`RELEASING.md` Step 6: `cp .../post-upgrade-tasks/README.md "$TARGET/README.md"`) and is itself a per-release historical record afterwards. `CLAUDE/UPGRADES/**` is already grandfathered in this repo's config for exactly this reason                                                               |
| 10  | `CLAUDE/UPGRADES/v2/v2.11-to-v2.12/v2.11-to-v2.12.md` → `CLAUDE/UPGRADES/v2/v2.12-to-v2.13/v2.12-to-v2.13.md`       | A bash YAML-validation snippet                                                                                                                     | archive-noise (already grandfathered)     | Both are versioned upgrade guides (R8/R9 historical records); already covered by the `CLAUDE/UPGRADES/**` grandfather entry                                                                                                                                                                                                                                  |
| 11  | `CLAUDE/UPGRADES/v2/v2.29-to-v2.30/README.md` → `CLAUDE/UPGRADES/v3/v2.32-to-v3.0/README.md`                        | A `validate-project-handlers` command snippet                                                                                                      | archive-noise (already grandfathered)     | Same as #10                                                                                                                                                                                                                                                                                                                                                  |

## Counts by verdict

| Verdict                                   | Count                                          |
| ----------------------------------------- | ---------------------------------------------- |
| true-duplication-worth-fixing             | 2                                              |
| deliberate-idiom-candidate-for-ssot-quote | 3                                              |
| fixture/example-noise                     | 1                                              |
| archive-noise                             | 5 (3 already grandfathered by existing config) |

## Was the floor adjusted?

**No.** Noise (fixture/example + archive) accounts for 6 of 11 findings, but
5 of those 6 are either already-grandfathered historical records or a doc
explicitly quoting a template's own worked example — not false positives
the check got wrong, but real duplication the check correctly found and
existing policy (R8/R9, the pre-existing grandfather entry) correctly
already treats as non-actionable. The remaining 5 findings (2
true-duplication + 3 ssot-quote candidates) are exactly the shape the
design predicts: genuine untracked repetition in live, actively-maintained
docs. `MIN_BLOCK_LENGTH_CHARS = 120` cleanly excluded the one category the
design specifically warned about (the ubiquitous two-line
`./bin/hooks-daemon restart`/`status` fence pair, and every other short
command/status snippet like it) without needing a second pass — across the
full 198-document corpus (2,183 structured-block instances), only 11
distinct blocks were shared across document boundaries at all. Nothing
here indicates the floor needs raising or a category needs excluding.

## Follow-up

The five actionable findings (#2, #3, #5, #6, #7) are documentation
housekeeping, not a defect in this check — they belong to the semantic
half of R13 (judging whether extracted content should be canonicalised
via R1, wrapped via `ssot-quote`/R4b, or left as-is) and are exactly the
kind of finding `hooks-daemon-docs-qa` (Task 3.1g/2.3) is designed to
adjudicate at scale, or a human doing plan-linked documentation cleanup.
They are not tracked as new plan tasks here — Task 3.2's existing
`AgentTeam.md`/`Worktree.md` line item already covers finding #2, and the
others are small enough to fix opportunistically rather than warranting a
dedicated task.
