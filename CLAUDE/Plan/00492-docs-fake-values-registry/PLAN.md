# Plan 00492: docs fake values registry

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Inventory the fake-looking values in tracked docs and in vendored docs, by kind (session ids,
  tokens, hostnames, paths, emails). Decide the registry file location and format (machine-readable, one entry per
  value with its kind).
  Inventory: the only kind with a public pattern that fakes collide with is `session-uuid`. Tracked files hold twelve
  all-same-digit ids (digits 0-5 and a-f) and a handful of upstream-style random ids (the vendored hooks page and
  tests). Decision: `.claude/fake-values.yaml`, a `kinds:` mapping keyed by the public pattern's name, each kind with
  `values` (exact), an optional `fake_looking` regex and a description. Tokens, hostnames and emails have no public
  pattern here, so no kind is registered for them; a new kind is a new key.
- [x] ✅ **Task 1.2**: Decide how a fidelity-rule exception is expressed: which provenance field records a swap
  (original kind, listed replacement), and update the schema in `CLAUDE/RemoteDocs.md` (the canonical home).
  Coordinator call (2026-10-06): one optional provenance field, `value_swaps`, a list of
  `{kind, replacement, occurrences, original_sha256}`, not an owner ruling. It extends the existing schema in
  place, so `remote_docs_provenance` and `remote_docs_commit_gate` carry it through `parse_provenance` with no new
  file. A document with swaps cannot declare `verbatim` (the parser rejects it) and is recorded `converted`;
  `source_sha256` stays the hash of the raw upstream bytes. The original value is stored only as a hash, because
  the value itself is what the public patterns refuse.

### Phase 2: Registry and checks

- [x] ✅ **Task 2.1**: Create the registry with the initial entries, one canonical home, referenced and not copied.
  `.claude/fake-values.yaml`; loader and swap logic in `utils/fake_values.py`; the account of it is in
  `CLAUDE/RemoteDocs.md`.
- [x] ✅ **Task 2.2**: Add a docs QA check: a fake-looking value in docs or vendored docs that is not on the registry is
  a finding, with the remedy named (use a listed fake, or extend the list for a genuinely new kind). TDD.
  `unlisted-fake-value` (edit and sweep, advisory).
- [x] ✅ **Task 2.3**: Teach the sensitive-content check that a listed fake is allowed. A value that is not on the
  registry is judged as before. TDD, including a real-looking value that must still be blocked.
  Handler, commit scan and `scripts/qa/check_sensitive_content.py`.

### Phase 3: Remote-docs capture

- [x] ✅ **Task 3.1**: `remote-docs add` swaps an unknown fake for a listed one of the same kind and records the swap in
  the provenance frontmatter. TDD. `refresh` swaps the same way.
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
