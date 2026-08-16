# Plan 00244: path agnostic generated docs

**Status**: In Progress
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
public repo). Source report: `untracked/hooks-daemon-home-path.md`.

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

- [ ] ⬜ **Task 4.1**: Full QA suite green.
- [ ] ⬜ **Task 4.2**: Daemon restart verified RUNNING; regenerate this repo's
  `CLAUDE.md` and `.claude/HOOKS-DAEMON.md` and confirm the leaks are gone.
- [ ] ⬜ **Task 4.3**: Client-mode verification via `scripts/dummy-client-repo.sh`
  — the fixture's own root must not appear in its generated docs.
- [ ] ⬜ **Task 4.4**: Record the truth-change and file the report's fate
  (`untracked/` reports never linger).

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

- [ ] Rendering the generated docs under a client-mode root yields no occurrence
  of that root — enforced by a test, not by inspection.
- [ ] Runtime block reasons and advisories still emit absolute paths.
- [ ] Full QA suite passes.
- [ ] Daemon restarts RUNNING and regenerates this repo's tracked docs clean.
- [ ] `scripts/dummy-client-repo.sh` fixture confirms the fix in client mode.

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

- Plan opened from client bug report `untracked/hooks-daemon-home-path.md`
