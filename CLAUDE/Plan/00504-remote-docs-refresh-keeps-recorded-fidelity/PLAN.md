# Plan 00504: remote docs refresh keeps recorded fidelity

**Status**: In Progress
**Created**: 2026-10-11
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #73

## Overview

`remote-docs refresh` resolves one fetcher from the command line's `--verbatim`
flag (`daemon/cli.py`, `resolve_fetcher(verbatim=...)`) and uses it for every
target. Each stored document's provenance frontmatter records its `fidelity`,
but refresh never reads it. So refreshing a corpus that mixes verbatim and
converted documents rewrites one kind wrongly, whichever way the flag is set:
a document captured with `add --verbatim` becomes an extraction after a plain
`refresh --all`.

## Goals

- By default, refresh chooses each target's fetcher from that document's
  recorded fidelity.
- An explicit `--verbatim` stays an override, applied knowingly to every
  target.
- A mixed corpus refreshes each document in its own mode, and its frontmatter
  still records that mode.

## Non-Goals

- Changing `remote-docs add`.
- Changing the provenance schema.

## Tasks

### Phase 1: Fix

- [ ] 🔄 **Task 1.1**: RED. Tests: `refresh --all` over a corpus with one verbatim
  and one converted document keeps each one's fidelity; `refresh --path` on a
  verbatim document fetches verbatim with no flag; `--verbatim` still forces
  verbatim; a document with no readable fidelity behaves as today (say which,
  in the test).
- [ ] 🔄 **Task 1.2**: GREEN. Resolve the fetcher per target from its recorded
  fidelity.
- [ ] 🔄 **Task 1.3**: Update the `refresh` help text, `CLAUDE/RemoteDocs.md`,
  and add a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks, merge; comment on #73 and
  close it.

## Success Criteria

- [ ] A mixed-fidelity corpus refreshes with no flag and keeps every
  document's recorded fidelity.
- [ ] `--verbatim` still overrides.
- [ ] The release-bound consequence, a behaviour change in `refresh`, is in the
  pending-release holding area as a release note.

## Delivery & Milestones

- Issue #73 triaged and claimed.
