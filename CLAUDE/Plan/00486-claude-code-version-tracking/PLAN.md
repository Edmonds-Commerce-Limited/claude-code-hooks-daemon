# Plan 00486: Claude Code version tracking

**Status**: Not Started
**Created**: 2026-10-03
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon is built on top of Claude Code, and Claude Code ships new versions all the time. A daemon release records nothing about which Claude Code version it was built and tested against. Nothing reviews what Claude Code added between two daemon releases, either. Without that, the daemon can keep doing work that Claude Code now does itself, or can end up fighting a new Claude Code behaviour. Owner request (2026-10-03): track the Claude Code version per daemon release, review the Claude Code changes at each release, and detect when a newer Claude Code is running. The trigger was a report that Claude Code now has idle compaction, which the daemon did not know about.

Prior art: Plan 00327 audited the hook contracts once and recorded `last_audited_claude_code_version` in `contracts/claude-code-hooks/META.json`. The `contract_staleness` SessionStart handler advises when the installed Claude Code is newer than that version, and `docs/guides/HOOK-CONTRACT-REFRESH.md` is the refresh procedure. All of that covers hook *contracts* only. This plan adds the *feature* side: the changelog review, the per-release record and the overlap check.

## Goals

- Every daemon release records the Claude Code version it was built and tested against.
- Every release reviews the Claude Code changelog since the previous release's recorded version. The review classifies each relevant change as one of:
  - adopt: the daemon should use it;
  - redundant: the daemon now duplicates it;
  - conflict: the daemon fights it;
  - no impact.
- Each adopt, redundant or conflict finding becomes a plan or ledger entry.
- A session running a newer Claude Code than the last reviewed version is told so once.

## Non-Goals

- Restarting long-running ccy sessions when Claude Code updates. That belongs to ccy, not this repository. The owner may want an issue filed on the ccy repository; that is the owner's call.
- Pinning or blocking Claude Code versions.

## Tasks

### Phase 1: Record and review

- [ ] ⬜ **Task 1.1**: Decide where the per-release record lives. Candidates:

  - a `claude_code_version` field in the RELEASES notes front matter;
  - a `CLAUDE/development/claude-code-versions.yaml` map from daemon release to Claude Code version and review date.

  Reuse `contract_status.py`'s version reading rather than adding a second reader.

- [ ] ⬜ **Task 1.2**: Add a RELEASING.md step that records the version and runs the review. The review is a dedicated read-only subagent definition, `claude-code-changelog-reviewer`. It reads the vendored changelog (`hooks-daemon remote-docs`) between the two versions. It writes its report into the release's plan folder or `untracked/release-artifacts/`.

- [ ] ⬜ **Task 1.3**: Vendor `https://code.claude.com/docs/en/changelog` through remote-docs so the review reads a provenance-stamped copy.

- [ ] ⬜ **Task 1.4**: Run a first backfill review from the version current at v3.67.0 to today's version. Include the idle compaction question: confirm whether it exists and where it overlaps the daemon's compaction handling and its prompt-cache and usage features.

### Phase 2: Detect drift in a session

- [ ] ⬜ **Task 2.1**: Extend `contract_staleness`, or add a sibling handler, to compare the running Claude Code version with the last *reviewed* version. It advises once per new version. Prefer one handler with two checks over two near-identical handlers.
- [ ] ⬜ **Task 2.2**: Brainstorm and decide with the owner on routine vs release-only review. Option: a Routine (CLAUDE/Routine) that runs the review when a new Claude Code version is first seen, between releases.

## Success Criteria

- [ ] A release cannot complete without the recorded Claude Code version and a review report.
- [ ] The backfill review is done and its findings are filed.
- [ ] A session on an unreviewed Claude Code version sees a single advisory.

## Delivery & Milestones

- Plan filed.
