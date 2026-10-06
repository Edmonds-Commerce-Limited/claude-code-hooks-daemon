# Plan 00494: Claude Code mods review

**Status**: In Progress
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

- [ ] ⬜ **Task 2.1**: File follow-up plans or ledger entries for the candidates the owner chooses. Waiting on the
  owner's choice from the shortlist.

## Success Criteria

- [x] All reachable mod docs are vendored with valid provenance.
- [ ] The review and the brainstorm are written, cite the vendored pages, and have reached the owner.
- [ ] The owner has chosen which candidates to pursue, and each chosen one has a plan or ledger entry.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00494-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan filed from the owner's request.
