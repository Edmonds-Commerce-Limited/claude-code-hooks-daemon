# Plan 00593: dependabot security lock bumps

**Status**: In Progress
**Created**: 2026-11-10
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

GitHub reports 77 open Dependabot alerts on `main` (4 critical, 37 high). All 77 are pip packages pinned in `uv.lock`,
and every one has a patched release. The owner's standing instruction is that dependencies are updated as a matter of
course. This plan takes every patched version the dependency constraints allow, in one lock update.

| Package           | Locked | First fully patched |
| ----------------- | ------ | ------------------- |
| nltk              | 3.9.4  | 3.10.4              |
| anyio             | 4.13.0 | 4.14.2              |
| virtualenv        | 21.7.1 | 21.14.9             |
| urllib3           | 2.6.3  | 2.8.0               |
| cryptography      | 46.0.7 | 50.0.0              |
| filelock          | 3.29.0 | 4.2.1               |
| mcp               | 1.29.0 | 1.30.0              |
| idna              | 3.13   | 3.15                |
| opentelemetry-api | 1.37.0 | 1.45.1              |

A known constraint: `safety>=3.8.1` requires `filelock<4.0`, so filelock was held at 3.29.0 in `3b655a3c8`. A package
that cannot reach its patched version is recorded here with the constraint that holds it and the alert it leaves open,
never dropped silently.

Dependabot PR #193 (nltk only) is superseded by this plan and is closed once this lands.

## Goals

- Every alerted package at or above its first patched version, unless a named constraint holds it.
- QA green on the bumped lock; any code change a new version forces is made test-first.

## Non-Goals

- No bump of packages without an alert, beyond what the resolver needs.
- No change to the Dependabot configuration.

## Tasks

### Phase 1: Bump

- [ ] ⬜ **Task 1.1**: `uv lock --upgrade-package` for each alerted package; record any package held by a constraint and
  why
- [ ] ⬜ **Task 1.2**: targeted QA plus the tests that exercise the bumped packages; fix forced breakage test-first

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: merge, main CI green, confirm the Dependabot alert count dropped, close PR #193

## Success Criteria

- [ ] Open Dependabot alerts on `main` cover only packages held by a recorded constraint
- [ ] Main CI green on the merge
- [ ] Release-bound consequences: none for client projects (a dev-lock update of this repository; the daemon's
  installed runtime dependencies are unchanged unless Task 1.1 records otherwise, in which case a release note is added)

## Delivery & Milestones

- (pending)
