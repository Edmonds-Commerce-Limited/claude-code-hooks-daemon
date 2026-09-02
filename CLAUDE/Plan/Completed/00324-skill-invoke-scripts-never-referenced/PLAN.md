# Plan 00324: skill invoke scripts never referenced

**Status**: Complete
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Plan 00322 found the config-optimisation step's 395-line procedure sitting in
a sibling `invoke.sh` that no SKILL.md referenced, and confirmed against the
Claude Code skills documentation that only a skill's markdown is loaded — a
script beside SKILL.md never runs unless the markdown says to run it, and no
frontmatter key changes that. That plan fixed the one skill it was moving and
noted four others share the shape. Noting is not fixing.

`configure` (133 lines), `mode` (52), `acceptance-test` (182) and `release`
(317) each carry an `invoke.sh` their SKILL.md never mentions. Every
invocation of those four has been running on the SKILL.md summary alone. Two
of them are argument-aware — `mode` reads `${*:-get}`, `release` reads
`${1:-auto}` — so the arguments a user types have been discarded as well as
the procedure.

The failure is silent by construction: the skill still "works", just with a
thinner brief, and nothing in the build compares the two files. A contract
test closes it for these four and for every skill added later.

## Goals

- Each of the four skills starts by running its own `invoke.sh`, with the
  user's arguments passed through where the script reads them.
- A skill directory that ships an `invoke.sh` its SKILL.md never references
  fails CI.

## Non-Goals

- Rewriting what any `invoke.sh` says.
- Merging the scripts into their SKILL.md — the scripts resolve per-install
  paths at runtime, which static markdown cannot.
- `docs-qa` and `hooks-daemon`, which already reference their scripts.

## Tasks

### Phase 1: Lock the contract

- [x] ✅ **Task 1.1**: Contract test: for every skill directory under
  `.claude/skills/` and under
  `src/claude_code_hooks_daemon/skills/`, an `invoke.sh` (or a
  `scripts/*.sh`) present on disk must be referenced by that skill's
  markdown. RED first on the four.

### Phase 2: Reference the scripts

- [x] ✅ **Task 2.1**: Add a "run this first" block to `configure`, `mode`,
  `acceptance-test` and `release`, passing arguments through for the two
  scripts that read them.

### Phase 3: Ship

- [x] ✅ **Task 3.1**: QA, daemon restart + verification, CHANGELOG entry,
  commit and push.

## Success Criteria

- [x] Invoking any of the four loads the procedure its author wrote, with
  arguments intact.
- [x] A future skill that bundles an unreferenced script fails CI.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00324-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivered in the archiving commit: four SKILL.md files gain a "Run this first" block with argument passthrough, plus `tests/unit/scripts/test_skill_scripts_are_referenced.py` covering both skill trees.
