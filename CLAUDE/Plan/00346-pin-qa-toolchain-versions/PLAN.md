# Plan 00346: pin qa toolchain versions

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

Every QA tool in `pyproject.toml`'s `[dev]` extra is declared with a lower
bound and no upper bound, and every one of them has since drifted past a major
version. A fresh `pip install -e '.[dev]'` on another machine therefore
installs a toolchain nobody has run this repository against, and the result is
not a clear failure — it is a silent change in what QA means.

The formatter is the sharpest case, because `scripts/qa/run_format_check.sh`
**auto-fixes**. A black release that rewraps differently does not fail the
build; it rewrites the tree and reports success, so the change arrives as
hundreds of unrelated modified files in someone's next diff. The same shape
already happened to a linter here: `pyproject.toml:192` records ruff 0.14
newly enforcing TC002/TC003 across 30 findings in 24 files, answered by adding
ignores rather than by pinning.

This plan does not choose a pinning policy in advance. It establishes what each
tool's floor should be, whether an upper bound belongs on tools whose output is
a contract (black) versus tools whose output is a report (bandit, deptry), and
records the decision where the next person will find it.

## Goals

- Every QA tool in `[project.optional-dependencies].dev` carries a bound that
  reflects a version this repository has actually been run against.
- Tools whose output is auto-applied to the tree cannot change that output
  without a deliberate, reviewable dependency change.
- The rationale for each bound is recorded next to the bound.

## Non-Goals

- Upgrading or downgrading any tool. The installed versions pass QA today;
  this plan is about declaring them, not changing them.
- Pinning runtime dependencies. The `[dev]` extra is not shipped to client
  projects — `scripts/install/venv.sh` installs without it.
- Introducing a lockfile or changing the packaging toolchain.

## Evidence

Declared floor versus what is installed and passing QA today:

| Tool        | Declared  | Installed | Majors adrift |
| ----------- | --------- | --------- | ------------- |
| pytest      | `>=7.0`   | 9.1.1     | 2             |
| pytest-cov  | `>=4.0`   | 7.1.0     | 3             |
| pytest-mock | `>=3.11`  | 3.15.1    | 0             |
| black       | `>=23.0`  | 26.5.1    | 3             |
| ruff        | `>=0.1.0` | 0.15.22   | pre-1.0       |
| mypy        | `>=1.0`   | 2.3.0     | 1             |
| bandit      | `>=1.7`   | 1.9.4     | 0             |
| semgrep     | `>=1.100` | 1.172.0   | 0             |

## Tasks

### Phase 1: Decide the policy

- [ ] ⬜ **Task 1.1**: Separate the tools by what their output IS — a change
  applied to the tree (black), a gate that fails (ruff, mypy, pytest), or a
  report that is read (bandit, semgrep, deptry, safety). The three want
  different bounds and the plan should say which and why.
- [ ] ⬜ **Task 1.2**: Decide whether the repository wants upper bounds, a
  lockfile for dev, or floors raised to the installed versions. Record the
  decision and the rejected alternatives.

### Phase 2: Apply and verify

- [ ] ⬜ **Task 2.1**: Update `pyproject.toml` per the decision, with a comment
  per bound giving its reason (the file already uses this style — see the
  semgrep and pre-commit entries).
- [ ] ⬜ **Task 2.2**: Verify a clean install of the declared set reproduces a
  green QA run, so the declaration is measured rather than asserted.

## Success Criteria

- [ ] No QA tool is installable at a version this repository has never run.
- [ ] The formatter cannot silently rewrite the tree after a routine install.
- [ ] Each bound carries a reason a later reader can evaluate.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00346-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet started.
