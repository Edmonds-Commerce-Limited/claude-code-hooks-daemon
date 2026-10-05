# Plan 00492: docs fake values registry

**Status**: Not Started
**Created**: 2026-10-05
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Two Claude Code docs pages (statusline and changelog) cannot be vendored, because an example session id in each matches
the `session-uuid` sensitive-content pattern (niggle N309; Plan 00479 Task 1.1; Plan 00486 Task 1.3). The remote-docs
fidelity rule forbids changing vendored text, so the two rules conflict.

The project owner ruled on 2026-10-05 (D1, see
[OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md)) for a broader design than the
question asked. There is one source of truth listing the FAKE values used in docs (session ids, tokens, hostnames and so
on). Docs may freely use any listed fake. Anything fake-looking that is not on the list must be replaced by a listed
fake, or the list extended for a genuinely new kind of fake.

This plan builds that registry and wires it into the docs QA, the sensitive-content check and remote-docs capture.

## Goals

- A canonical registry file of approved fake values, grouped by kind.
- A QA check that fake-looking values in docs and vendored docs are on the registry.
- The sensitive-content check treats a listed fake as allowed and still blocks a real-looking value.
- Vendored pages swap unknown fakes for listed ones, and the swap is recorded in the page's provenance.
- N309 settled; Plan 00479 Task 1.1 and Plan 00486 Task 1.3 unblocked.

## Non-Goals

- No weakening of the `session-uuid` pattern or any other public pattern for values not on the registry.
- No exemption of the vendored-docs tree from sensitive-content checks.
- No registry entry for a real credential, ever.

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Inventory the fake-looking values in tracked docs and in vendored docs, by kind (session ids,
  tokens, hostnames, paths, emails). Decide the registry file location and format (machine-readable, one entry per
  value with its kind).
- [ ] ⬜ **Task 1.2**: Decide how a fidelity-rule exception is expressed: which provenance field records a swap
  (original kind, listed replacement), and update the schema in `CLAUDE/RemoteDocs.md` (the canonical home).

### Phase 2: Registry and checks

- [ ] ⬜ **Task 2.1**: Create the registry with the initial entries, one canonical home, referenced and not copied.
- [ ] ⬜ **Task 2.2**: Add a docs QA check: a fake-looking value in docs or vendored docs that is not on the registry is
  a finding, with the remedy named (use a listed fake, or extend the list for a genuinely new kind). TDD.
- [ ] ⬜ **Task 2.3**: Teach the sensitive-content check that a listed fake is allowed. A value that is not on the
  registry is judged as before. TDD, including a real-looking value that must still be blocked.

### Phase 3: Remote-docs capture

- [ ] ⬜ **Task 3.1**: `remote-docs add` swaps an unknown fake for a listed one of the same kind and records the swap in
  the provenance frontmatter. TDD.
- [ ] ⬜ **Task 3.2**: Vendor the statusline page (unblocks Plan 00479 Task 1.1) and the changelog page (unblocks Plan
  00486 Task 1.3).
- [ ] ⬜ **Task 3.3**: Close N309 in the niggles ledger and mark the two plan tasks unblocked.

## Success Criteria

- [ ] One registry file is the only list of approved fakes.
- [ ] The docs QA check flags an unlisted fake-looking value and passes on listed ones.
- [ ] Sensitive-content allows a listed fake and still blocks an unlisted real-looking value.
- [ ] Both Claude Code docs pages are vendored, each with its swaps recorded in provenance.
- [ ] N309, Plan 00479 Task 1.1 and Plan 00486 Task 1.3 are closed.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00492-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan created from owner ruling D1.
