# Plan 00548: python entry point shebang detector

**Status**: Not Started
**Created**: 2026-10-22
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #130 (follow-up)

## Overview

Plan 00546 built the `bare-python-invocation` rule. That rule finds shell lines that run a bare `python3`, which on
a client can be older than the 3.11 floor. Its Q2 ruling (adviser, delegated by the owner) left two forms of the
same defect class outside the rule, to be handled in this follow-up:

- **`#!/usr/bin/env python3` shebangs on Python entry points a client may start directly.** There are 56 such
  shebangs. Five were judged plausibly client-run. Four of those are already guarded, by the package import's floor
  check or by `install.py`'s own guard. The fifth, `scripts/debug_info.py`, had a real pre-guard 3.11 import and was
  fixed in Plan 00546.
- **`command -v python3` probes whose result is executed later.** There are 0 instances: every site is
  floor-checked, handed to `uv`, or only reports. This is recorded as a known gap, with no rule yet.

Ruling and evidence: Plan 00546's `subagent-reports/261022-owner-questions-advice-fable.md` (Q2) and
`subagent-reports/261022-rulings-applied-sonnet.md`.

## Goals

- A detector finds a client-run Python entry point that can do 3.11-only work before any floor guard runs.
- It covers the whole defect class, not only the shebang spelling.
- Its universe of files is decided and written down first.

## Non-Goals

- CI workflow `run:` lines. Every one follows `actions/setup-python`; ruled out of scope in Plan 00546 Q2.
- A probe-result rule. Build one only when an instance appears.

## Tasks

### Phase 1: Universe and detector

- [ ] ⬜ **Task 1.1**: Decide the detector's universe: which Python files a client can start directly. Record how
  "client-run" is determined.
- [ ] ⬜ **Task 1.2**: Defence Before Fix: an independent search, then the rule, proven red on a planted instance and
  green on the tree.
- [ ] ⬜ **Task 1.3**: Optionally, give the other client-run scripts the same floor guard once the detector exists.

## Success Criteria

- [ ] The detector runs in QA and reports 0 on the tree, and is proven red on a planted instance.
- [ ] The probe-result form is documented as a known gap with 0 instances.
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the pending-release holding area) if the detector
  changes anything a client sees; otherwise this plan states it has no release-bound consequences.

## Delivery & Milestones

- Filed from Plan 00546's Q2 ruling.
