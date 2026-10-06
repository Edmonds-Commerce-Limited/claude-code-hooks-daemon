# Plan 00494: Claude Code mods review

**Status**: Complete
**Created**: 2026-10-06
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus (review), Sonnet (any follow-on build)
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner request (2026-10-06): Claude Code has a new "mod" feature. Review it and brainstorm whether anything this
repository does, or could do, within its areas of responsibility would be better served as a mod. Those areas include
hook handlers and the daemon, guards and QA, plan workflow, the status line, the ccy supervisor, crons and session
resilience, and remote docs.

The first step is evidence: vendor every upstream page about mods through `hooks-daemon remote-docs add`, so the review
reads provenance-stamped copies. The review then works out how mods are built, loaded, scoped and trusted, and how they
relate to hooks, plugins, skills, agents and settings.

## Goals

- Every available upstream doc on Claude Code mods is vendored with provenance.
- A written review explains what a mod is and what it can and cannot do, with citations to the vendored pages.
- A brainstorm sorts each candidate in this repository's areas of responsibility as: a better fit as a mod, a mod
  that complements the daemon, or no fit, with reasons.
- Promising candidates become follow-up plans or ledger entries, chosen by the owner.

## Non-Goals

- Building a mod in this plan. Any build is a follow-up plan the owner picks.
- Replacing the daemon's hook architecture on speculation.

## Tasks

### Phase 1: Evidence and review

- [x] ✅ **Task 1.1** (013b4ab38, 0bd1c8ce0): Vendor every upstream page about mods (and any directly related pages it
  depends on) with `bin/hooks-daemon remote-docs add <url>`. Record the URLs captured and any that could not be
  captured, with the reason. 21 pages captured, none refused; the list is in the report's Sources section.
- [x] ✅ **Task 1.2** (a12b69915): Opus review of the feature from the vendored pages, written to `subagent-reports/`.
  It covers the mechanism, lifecycle, trust and permissions, distribution, and how mods relate to hooks, plugins, skills
  and agents. Report: [261006-mods-review-opus.md](subagent-reports/261006-mods-review-opus.md).
- [x] ✅ **Task 1.3** (a12b69915): Brainstorm against this repository's areas of responsibility, with each candidate
  classed as better as a mod, complementary, or no fit, and the reasons. Put the shortlist to the owner. The shortlist
  and six open questions are in the report; they went to the owner on 2026-10-06.

### Phase 2: Owner decision

- [x] ✅ **Task 2.1**: The owner's choice (2026-10-06, A2 of
  [OWNER-RULINGS-261006.md](../../00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md)):
  - **Approved:** daemon mod awareness, with an exceptionally loud warning for mods that can interfere with hooks.
  - **One mod only:** a single hooks-daemon mod carrying several features, never several mods.
  - **New candidates:** a user to-do and question list in the sidebar, and SessionStart messages.
  - **Maybe:** the session-resilience features, pending a detailed proposal.
  - **Rejected:** the ccy supervisor as a mod. Mods are not for protection.
- [x] ✅ **Task 2.2** (`f794f4cd1`): Detailed proposal for the single hooks-daemon mod: architecture, the to-do/question list,
  SessionStart messages, session resilience, and a concrete spec for daemon mod awareness. It also answers the owner's
  question of how mods are updated and how projects are kept on the right mod version. Report:
  `subagent-reports/261006-hooks-daemon-mod-proposal-opus.md`.
- [x] ✅ **Task 2.3**: Build daemon mod awareness (approved), TDD, from the Task 2.2 spec. Moved to
  [Plan 00497](../../00497-hooks-daemon-mod/PLAN.md) Task 1.1, so the whole build lives in one plan.
- [x] ✅ **Task 2.4**: Put the Task 2.2 proposal to the owner; file a build plan for the mod features chosen. The owner
  approved the design, the build order and the deployment route on 2026-10-06, and added suggested prompts. Build plan:
  [Plan 00497](../../00497-hooks-daemon-mod/PLAN.md).

## Success Criteria

- [x] All reachable mod docs are vendored with valid provenance.
- [x] The review and the brainstorm are written, cite the vendored pages, and have reached the owner.
- [x] The owner has chosen which candidates to pursue, and each chosen one has a plan or ledger entry (Plan 00497).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00494-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's request.
