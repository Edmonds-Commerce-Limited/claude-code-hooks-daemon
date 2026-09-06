# Plan 00334: core doc templates for client projects

**Status**: Complete
**Created**: 2026-09-06
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct implementation, with one sub-agent per document
for the genericisation pass

## Overview

The daemon can be configured to enforce a workflow whose documentation it never
creates. `plan_workflow.enabled: true` sets `workflow_docs` to
`CLAUDE/PlanWorkflow.md` (`config/models.py:808-811`), handler guidance tells
the agent to read that file (`plan_workflow.py:78`), and nothing ever deploys
it. A freshly-installed client project therefore enforces a workflow against a
document that does not exist, and instructs its agent to read a path that
resolves to nothing.

Found in a real client install, not by inspection.

It is a class, not an instance:

| Surface                                                    | Names                    | Deployed |
| ---------------------------------------------------------- | ------------------------ | -------- |
| `handlers/pre_tool_use/plan_workflow.py:78`                | `CLAUDE/PlanWorkflow.md` | never    |
| `handlers/pre_tool_use/worktree_file_copy.py:57`           | `CLAUDE/Worktree.md`     | never    |
| `config/models.py:808-811`                                 | `CLAUDE/PlanWorkflow.md` | never    |
| `install/templates/agents/hooks-daemon-docs-qa.md:135-136` | `CLAUDE/PlanWorkflow.md` | never    |

The last is the sharpest: a file the daemon **does** ship cites one it does
**not**. And `plan_number_helper.py:499-503` guards the same kind of reference
with an `.exists()` check first, so the hazard is already known here and the
guard is applied inconsistently.

Two existing facts shape the fix rather than being incidental to it. The
ownership machinery already exists — `install/plan_workflow.py` deploys
`PlanJournalling.md` as a CLIENT-owned seed-once document (`:334-378`) beside
DAEMON-owned always-overwritten `mkplan.bash` (`:379-416`), so a shipped doc
template is not a new concept and `PlanWorkflow.md` is simply the one left out.
And this project's own document cannot ship verbatim: `CLAUDE/PlanWorkflow.md`
(34K) opens by naming "the Claude Code Hooks Daemon project", so shipping it
would push this repo's specifics into every client — the outcome the owner
ruled out.

## Goals

- No daemon-emitted guidance names a client document the daemon does not ensure
  exists.
- A client receives a usable core workflow document on install AND upgrade, and
  keeps its own customisations across both.
- Upstream improvements to a core document reach existing clients on upgrade
  without overwriting anything the client wrote.
- This repository consumes the templates it ships, verifiably rather than by
  convention, so a broken template breaks our own build first.

## Non-Goals

- **Rewriting the documents' content.** Genericisation removes project-specific
  claims; it is not a rewrite of guidance that already works.
- **Shipping every `CLAUDE/*.md` in this repo.** Several are genuinely
  project-specific (`ARCHITECTURE.md`, `AgentTeam.md`, `SELF_INSTALL.md`) and
  would be noise in a client. The set is chosen, not swept.
- **Making `@` a real import.** It is a CLAUDE.md feature; in a referenced
  document it is a convention. This plan VERIFIES the convention is followed
  rather than pretending the mechanism is something it is not (Decision 3).

## Tasks

### Phase 1: Reproduction (RED)

- [x] ✅ **Task 1.1**: Failing test proving a fresh client-mode deploy leaves
  `CLAUDE/PlanWorkflow.md` absent while `workflow_docs` points at it.
- [x] ✅ **Task 1.2**: Failing test for the general invariant — every client doc
  path named in handler guidance or a config default is either deployed or
  guarded by an existence check. Six tests, all RED, each naming a real defect.

### Phase 2: The core/override mechanism

- [x] ✅ **Task 2.1**: `install/templates/core/` as the home for genericised
  core documents, deployed DAEMON-owned and overwritten every run (mirroring
  `mkplan.bash`) into the project's configured agent-docs tree.
- [x] ✅ **Task 2.2**: Seed the CLIENT-owned override document once, never
  clobbering it, carrying the reference to its core document plus an empty
  overrides section (mirroring `_TEMPLATE_.md`). The reference is a markdown
  link rather than an `@`-import (Decision 3).
- [x] ✅ **Task 2.3**: Wire into the install and both upgrade paths, so every
  route that turns a subsystem on also produces the documents it names.
  Superseded in part by Task 4.4 — see Decision 8 for why the plan-workflow
  bootstrap was the wrong home.

### Phase 3: The first core documents

- [x] ✅ **Task 3.1**: Genericise `CLAUDE/PlanWorkflow.md` and `Worktree.md`
  into core documents. Nothing was lost in the reduction — each core is LARGER
  than the original it was extracted from.
- [x] ✅ **Task 3.2**: Convert this repo's own documents to the reference +
  overrides form (1053 → 90 lines and 104 lines), so the dogfooding is live.
- [x] ✅ **Task 3.3**: The other two offenders needed no edit: deploying the
  documents is what makes `worktree_file_copy.py:57` and the shipped
  `hooks-daemon-docs-qa.md` reference resolve. A reference is only wrong while
  its target is missing.

### Phase 4: The remaining core set

- [x] ✅ **Task 4.1**: Roster selected and recorded, with the reason each
  document is in or out (Decision 6).

- [x] ✅ **Task 4.2**: Genericise and ship `DocumentationStrategy` — 178 lines
  of ours became an 803-line core carrying R1–R13 in full, and our own copy
  became a 99-line override.

- [x] ✅ **Task 4.3**: Deploy to the path the CONFIG names, not a hardcoded
  `CLAUDE/` (Decision 7) — found by auditing the Phase 2 work, reproduced RED.

- [x] ✅ **Task 4.4**: Gate each document on the subsystem that NAMES it, at its
  own decision site (Decision 8). The plan-workflow bootstrap was the wrong
  home: it is opt-in and defaults to off, so a stock install got nothing.

- [x] ✅ **Task 4.5**: Repoint the 21 citations in 16 shipped assets that name a
  client-relative `CLAUDE/<doc>.md` for a document the client never receives
  (`LLM-INSTALL`, `PROJECT_HANDLERS`, `HANDLER_DEVELOPMENT`, `DEBUGGING_HOOKS`,
  `SELF_INSTALL`). These are the DEPLOY-or-REPOINT alternative from Decision 4:
  the documents are out of the roster per Decision 6, so the citation is what
  has to change. Naming the daemon clone rather than a path keeps it correct in
  both install modes, which a literal `.claude/hooks-daemon/…` would not be —
  in self-install the daemon root IS the project root, so that path resolves to
  nothing. `skills/hooks-daemon/install.md` already qualified its reference
  ("in the daemon repo") and needed no change, which is where the wording came
  from.

- [x] ✅ **Task 4.6**: Replace the hand-maintained guard with a SCAN
  (`test_shipped_asset_citations.py`). Task 1.2's list is useful but is itself
  the shape of the root cause — a citation nobody remembered to add cannot be
  caught by a list nobody remembered to extend. The scan found three more
  citations that the manual sweep in Task 4.5 had missed, and carries four
  self-checks proving it can fail, because a scanner that can only pass is one
  nobody can trust.

- [x] ✅ **Task 4.7**: Fix the two CROSS-SUBSYSTEM citations — the sharpest
  instances of this plan's own bug class, and both masked by the scanner from
  Task 4.6. `hooks-daemon-docs-qa.md` is gated on `agents.docs_qa.enabled`, a
  THIRD switch independent of the plan workflow and the documentation
  subsystem, yet cited `CLAUDE/PlanWorkflow.md`; `skills/docs-qa/SKILL.md`
  deploys unconditionally and cited `CLAUDE/DocumentationStrategy.md`. Both
  now state the condition, and the agent states the rule inline rather than
  depending on a document it cannot rely on. Teaching the scanner this rule
  was tried and reverted — it fired on seven legitimate citations that share
  the gate of what they cite, and the gap is documented instead.

### Phase 5: Verify

- [x] ✅ **Task 5.1**: The Phase 1 invariant test passes with no exemptions —
  all three named documents are deployed, none guarded away.
- [x] ✅ **Task 5.2**: Full QA gate green (25/25, 18057 tests, coverage 95.2%);
  daemon restarts clean; docs regenerated.
- [x] ✅ **Task 5.3**: A simulated fresh client install produces a project whose
  named documents all exist — six files, 644, in the configured tree. The
  stock all-defaults case correctly produces `CLAUDE/Worktree.md` alone, which
  is the one document a stock install's guidance names.

## Technical Decisions

Moved to [DECISIONS.md](DECISIONS.md) when this document crossed the
plan-doc-size advisory — the reasoning is durable detail, which is what a named
supporting document is for. Nine decisions in summary:

| #   | Decision                                                                      |
| --- | ----------------------------------------------------------------------------- |
| 1   | The core is DAEMON-owned, the override CLIENT-owned; both halves load-bearing |
| 2   | The core is DEPLOYED into the client, not referenced in the vendored clone    |
| 3   | A markdown link, not an `@`-import — and the read is VERIFIED by a test       |
| 4   | Guidance must not name a document the daemon does not ensure exists           |
| 5   | A missing bundled template fails the BUILD, never a client's install          |
| 6   | Ship what the daemon ENFORCES in the client's repo; link to what it CONSULTS  |
| 7   | Deploy to the path the CONFIG names, never a hardcoded one                    |
| 8   | Gate each document on the subsystem that NAMES it                             |
| 9   | A citation must not cross a gate boundary unconditionally                     |

Decisions 7 and 8 reverse this plan's own earlier work, 3 corrected two shipped
templates, and 9 is the plan's own bug class reproduced inside the fix for it.
All four were found by auditing what had already been committed, not by a test
failing — which is the reason they are recorded rather than quietly amended.

<!-- The full text of every decision, the rejected alternatives, and the known
     residuals live in DECISIONS.md. Do not restate them here: two copies is
     the drift this plan exists to prevent. -->

## Success Criteria

- [x] A fresh client-mode install produces a project where every doc path named
  in handler guidance or a config default exists.
- [x] An upgrade refreshes core documents and leaves override documents
  byte-identical.
- [x] This repo's own `CLAUDE/PlanWorkflow.md` is the override form, and a test
  fails if it stops referencing its core document.
- [x] No shipped file cites a document that is not shipped.
- [x] Full QA gate green.

## Open follow-ups, deliberately not actioned

Two questions are the OWNER's call and were flagged rather than answered, so
that a judgement about scope is not made silently by the person implementing:

- **Does "full set" mean a wider roster?** Three core documents ship. Decision
  6 gives the rule for what is in or out (the daemon ENFORCES it in the
  client's repo vs the client merely CONSULTS it), and every document currently
  named by active guidance is covered — but "full set" could mean more.
- **Should `PlanJournalling` migrate into the core/override mechanism?** It is
  already deployed, seed-once and frozen, by the plan-workflow bootstrap on a
  plan-directory-relative path. Migrating it would move a working deploy, which
  is a real risk for a gain that is consistency rather than function.

Both are recorded in full under "Known residuals" in
[DECISIONS.md](DECISIONS.md). Neither blocks anything shipped here.

## Delivery & Milestones

- `4e78f7c9` — configured-path deploy (Decision 7), `workflow_docs` as a
  `ProjectLayout` axis, and `DocumentationStrategy` shipped as the third core.
