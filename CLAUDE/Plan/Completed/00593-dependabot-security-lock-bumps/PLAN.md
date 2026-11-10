# Plan 00593: dependabot security lock bumps

**Status**: Complete (2026-11-10)
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

## Outcome

| Package           | From   | To      | Alert cleared | Constraint holding it                                             |
| ----------------- | ------ | ------- | ------------- | ----------------------------------------------------------------- |
| nltk              | 3.9.4  | 3.10.4  | yes           |                                                                   |
| anyio             | 4.13.0 | 4.16.0  | yes           |                                                                   |
| virtualenv        | 21.7.1 | 21.15.6 | yes           |                                                                   |
| urllib3           | 2.6.3  | 2.8.0   | yes           |                                                                   |
| cryptography      | 46.0.7 | 50.0.2  | yes           |                                                                   |
| idna              | 3.13   | 3.20    | yes           |                                                                   |
| filelock          | 3.29.0 | 3.32.7  | no            | `safety` 3.8.1 (latest) requires `filelock<4.0`; patched is 4.2.1 |
| mcp               | 1.29.0 | 1.29.0  | no            | `semgrep` 1.184.0 (latest) requires `mcp==1.29.0`                 |
| opentelemetry-api | 1.37.0 | 1.37.0  | no            | `semgrep` 1.184.0 (latest) requires `opentelemetry-api~=1.37.0`   |

Forcing the held packages makes the resolver downgrade `semgrep`/`safety` (and drop `mcp`, `nltk` and others), so none
was forced and no dependency or pyproject floor was changed. Side effects of the update: `defusedxml` 0.7.1 added (new
`nltk` dependency); `packaging` and `python-discovery` moved. No runtime `[project] dependencies` package changed, so
no release note.

## Goals

- Every alerted package at or above its first patched version, unless a named constraint holds it.
- QA green on the bumped lock; any code change a new version forces is made test-first.

## Non-Goals

- No bump of packages without an alert, beyond what the resolver needs.
- No change to the Dependabot configuration.

## Tasks

### Phase 1: Bump

- [x] ✅ **Task 1.1**: `uv lock --upgrade-package` for each alerted package; record any package held by a constraint and
  why
- [x] ✅ **Task 1.2**: targeted QA plus the tests that exercise the bumped packages; fix forced breakage test-first

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: merge, main CI green, confirm the Dependabot alert count dropped, close PR #193

## Success Criteria

- [x] Open Dependabot alerts on `main` cover only packages held by a recorded constraint (77 to 18: filelock 13, mcp
  4, opentelemetry-api 1, all held by the latest `safety`/`semgrep` pins above)
- [x] Main CI green on the merge (run 42769393325 on `cc6ace282`)
- [x] Release-bound consequences in the holding area: none. No runtime `[project] dependencies` package changed; the
  one code change adds anyio's new `--anyio-mode` to the full-QA blocker's pytest option table, where an unlisted
  option was already judged under both readings (safe), so nothing a client sees changes.

## Delivery & Milestones

- Lock bump `d1d248e1d` (+ report `fe618f597`), fast-forwarded to main. Main CI run 42767350336 failed one test: anyio
  4.16 adds the pytest option `--anyio-mode`, which the option-table rot detector
  (`test_every_option_of_the_running_pytest_is_in_a_table`) caught. The implementer's targeted QA had passed because a
  lock-only change maps to no test files (`--allow-unmapped`), so no tests ran; its venv was synced
  (`uv sync --frozen --all-extras`). Fixed forward in `cc6ace282`; main CI run 42769393325 green.
- PR #193 closed by Dependabot once nltk 3.10.4 was on main.
