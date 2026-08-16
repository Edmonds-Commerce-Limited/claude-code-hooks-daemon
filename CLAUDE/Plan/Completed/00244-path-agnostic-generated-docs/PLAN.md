# Plan 00244: path agnostic generated docs

**Status**: Complete
**Created**: 2026-08-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon rewrites the `<hooksdaemon>` section of a client project's tracked
`CLAUDE.md` on every restart, and generates the tracked `.claude/HOOKS-DAEMON.md`.
Every daemon-CLI example inside them is emitted as an **absolute path rooted at
the rendering machine's project directory**, because handler `get_claude_md()`
bodies call `daemon_cli_command()` / `daemon_path()`, which resolve from
`ProjectContext.project_root()`.

On a client install that writes the developer's home directory into a tracked,
committed, sometimes public file. It also makes the documentation wrong for
every other clone, and causes per-machine churn: two developers — or a host and
a container view of the same bind-mounted repo — each rewrite the same lines on
restart, so the file ping-pongs and conflicts on merge.

Absoluteness is **correct** for the audience Plan 00192 had in mind: a runtime
block reason or advisory is ephemeral, is read by an agent on this machine, and
must be copy-paste runnable from any cwd. That reasoning stands and is not
reverted here. The defect is that one builder serves two audiences with opposite
requirements, and only the ephemeral one was considered.

Reported against v3.51.0 from a client install (`LongTermSupport/fedora-desktop`,
public repo). Origin report, with the two corrections the fix made to its
conclusions: [REPORT-client-home-path.md](REPORT-client-home-path.md).

## Goals

- Generated **tracked** documentation contains no machine-specific absolute path
  — no occurrence of the rendering project's own root.
- Runtime output (block reasons, advisory context) keeps absolute paths exactly
  as Plan 00192 specified.
- A regression guard that fails under a **client-mode** root, so the defect
  cannot reappear and cannot be masked by self-install mode again.
- This repo's own `CLAUDE.md` and `.claude/HOOKS-DAEMON.md` regenerate clean.

## Non-Goals

- Reverting or weakening Plan 00192's absolute-path contract for runtime output.
- Changing where the wrapper is deployed, or the wrapper's name.
- Rewriting hand-authored docs that legitimately quote `/workspace/…` while
  documenting self-install mode.

## Context & Background

`core/claude_md_injector.py` collects `handler.get_claude_md()` and writes the
result verbatim into the tracked `<hooksdaemon>` block. Any handler whose
guidance embeds a path builder therefore puts a machine-specific path into a
committed file.

**Why this was invisible.** In self-install mode the project root is
`/workspace`, so our own generated docs render `/workspace/bin/hooks-daemon …` —
absolute, but identical for everyone. Our committed artifacts look correct while
every client install leaks. Same blind-spot class as the context-sidecar path
mismatch fixed in v3.34.1.

**Path form** (decided with the human; see JOURNAL). Project-root-relative:
`.claude/hooks-daemon/bin/hooks-daemon status` in a client install,
`bin/hooks-daemon status` in self-install. Path-agnostic and still runnable from
the project root — the documented working directory for every daemon command —
and the same shape `_fallback_relative_path()` already returns, so there is one
definition of a path-agnostic wrapper path rather than two.

## Tasks

### Phase 1: Guard first (DBF)

- [x] ✅ **Task 1.1**: Write the failing client-mode regression test — render the
  generated docs with `ProjectContext` pinned to a client root, assert the
  output contains no occurrence of that root.
  - [x] ✅ Cover the `CLAUDE.md` `<hooksdaemon>` block (injector).
  - [x] ✅ Cover `.claude/HOOKS-DAEMON.md` (docs generator).
  - [x] ✅ Assert it fails today for the right reason, not by accident — 13 RED
    failures, matching the call-site map exactly.
- [x] ✅ **Task 1.2**: Write failing unit tests for the doc-variant builder
  (both install modes, no `$`, no leading `/`, arguments appended in order).

### Phase 2: The builder

- [x] ✅ **Task 2.1**: Add the path-agnostic doc variant to `utils/cli_command.py`
  alongside the runtime builders, sharing the existing named constants.
- [x] ✅ **Task 2.2**: Document in the module docstring WHY two builders exist —
  the two audiences and their opposite requirements — so the next reader does not
  "unify" them back into one.

### Phase 3: Switch the tracked-doc call sites

- [x] ✅ **Task 3.1**: Switch every `get_claude_md()` body that embeds a path
  builder to the doc variant (10 handlers, 11 call sites).
- [x] ✅ **Task 3.2**: Switch the docs generator's header line.
- [x] ✅ **Task 3.3**: Leave every runtime call site (block reasons, advisory
  context) on the absolute builder, and confirm each deliberately.
- [x] ✅ **Task 3.4**: Fix the SECOND defect class the report did not identify —
  guidance that hard-codes the literal `/workspace`. Not merely
  machine-specific: on a client install that directory does not exist at all.
  `absolute_path` (guidance AND its runtime block reason) and
  `root_recursion_guard` (both surfaces).

### Phase 4: Verify

- [x] ✅ **Task 4.1**: QA — **21/22 checks pass**. The one failing check is
  `tests`, carrying exactly 5 failures in
  `tests/integration/test_hooks_deploy_permissions.py` (expects `0o755`, gets
  `0o744`). Verified **pre-existing and unrelated** by running that file in a
  clean worktree at HEAD before any of this work: identical 5 failures. Cause is
  this container's `umask 0077` stripping the group/other bits `chmod +x` would
  grant; nothing in this plan touches permissions. Whether the deploy should
  force `0o755` regardless of umask is a separate decision about the permissions
  subsystem — raised with the human, not folded in here.
- [x] ✅ **Task 4.2**: Daemon restart verified RUNNING; regenerated this repo's
  `CLAUDE.md` and `.claude/HOOKS-DAEMON.md`. Leaks inside the generated block:
  **0** (was 13 wrapper paths + 3 hard-coded `/workspace` mentions); the
  `HOOKS-DAEMON.md` header now reads `bin/hooks-daemon generate-docs`. The 8
  remaining `/workspace` mentions in `CLAUDE.md` are outside the generated
  block — hand-authored self-install repo docs, correct as they stand.
- [x] ✅ **Task 4.3**: Client-mode verification via `scripts/dummy-client-repo.sh`
  (production installer, not synthesised state). The fixture's generated
  `CLAUDE.md` contains **0** occurrences of its own root and **0** of
  `/workspace`, and renders
  `.claude/hooks-daemon/bin/hooks-daemon status`. Dogfood daemon still RUNNING;
  fixture destroyed.
- [x] ✅ **Task 4.4**: Truth-change staged at
  `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.53.1.yaml` (two entries — the
  tracked-docs form change, and the `/workspace` hard-codes). No
  config-changes entry: this adds no config option and flips no default. The
  origin report is now tracked at `REPORT-client-home-path.md` in this folder
  rather than left in `untracked/`.

## Technical Decisions

### Decision 1: Two builders, not one reworked builder

**Context**: The same path builder feeds both ephemeral runtime output and
tracked generated documentation.

**Options Considered**:

1. Make the single builder relative everywhere — reverts Plan 00192 and breaks
   copy-paste runnability of block reasons from an arbitrary cwd.
2. Add a doc variant and route tracked-doc callers to it — both audiences keep
   the form they need.

**Decision**: Option 2. The requirements genuinely differ by destination, so the
split belongs in the API rather than in each caller's judgement.

**Date**: 2026-08-16

### Decision 2: Project-root-relative, not a `<repo-root>` placeholder

**Context**: The bug report ranked a `<repo-root>/…` placeholder first.

**Decision**: Project-root-relative. A placeholder is not runnable as printed,
and Plan 00192 exists because non-runnable documented commands led agents to
"repair" working installs — the same failure class this project already paid
for. Confirmed with the human before overriding the report's stated preference.

**Date**: 2026-08-16

## Success Criteria

- [x] Rendering the generated docs under a client-mode root yields no occurrence
  of that root — enforced by a test, not by inspection.
- [x] Runtime block reasons and advisories still emit absolute paths — pinned by
  `TestTheTwoBuildersStayDistinct` and by the guard's own fixture check.
- [x] QA passes, except one pre-existing failing check proven unrelated by a
  clean-tree run (Task 4.1). No check regressed.
- [x] Daemon restarts RUNNING and regenerates this repo's tracked docs clean.
- [x] `scripts/dummy-client-repo.sh` fixture confirms the fix in client mode.

## Risks & Mitigations

| Risk                                                           | Impact | Probability | Mitigation                                                                     |
| -------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------ |
| A tracked-doc call site is missed and keeps leaking            | Medium | Medium      | The Phase 1 guard renders the WHOLE generated output, so a miss fails the test |
| A runtime call site is switched by mistake, undoing Plan 00192 | Medium | Low         | Task 3.3 confirms each runtime site deliberately; unit tests pin absoluteness  |
| Relative form confuses a reader running from a subdirectory    | Low    | Medium      | Failure is a plain "No such file"; guidance already says run from project root |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00244-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan opened from the client bug report, now tracked here as
  `REPORT-client-home-path.md` — commit `8f58cb29`
- Fix, guard and the second defect class delivered at commit `6d7f8192`
- Verified end to end: dogfood regeneration clean (0 leaks in the generated
  block, was 16), and a real client install provisioned by the production
  installer renders `.claude/hooks-daemon/bin/hooks-daemon status` with 0
  occurrences of its own root
