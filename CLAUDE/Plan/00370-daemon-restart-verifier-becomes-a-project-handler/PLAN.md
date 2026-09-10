# Plan 00370: daemon restart verifier becomes a project handler

**Status**: Not Started
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner ruling, verbatim: "we should downgrade that handler to a project level
handler - also us dogfooding the project level handler concept. it should not
even be shipped as a built in handler." `daemon_restart_verifier`
(`src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_restart_verifier.py`)
only ever fires inside the hooks-daemon repository itself — its `matches()`
refuses every other project, because a client cannot break the daemon by
committing to it. It was just given a relevance declaration on `main`
(commit `e94ee7c7`, Plan 00330, release-notes callout 22) so `/hooks-daemon optimise` stops scoring a client project against a handler that can never do
anything for it. That was a bandage: the handler never belonged in the
shared, cross-project library in the first place. It is pure self-dogfooding
— "verify this repo's own daemon restarts before this repo's own commit" —
which is exactly what the project-level handler surface
(`.claude/project-handlers/`, `CLAUDE/PROJECT_HANDLERS.md`) exists for, and
which this repository already dogfoods with three other project handlers
(`enforce_llm_qa`, `plan_done_requires_holding_area`, `release_blocker`).

This plan removes `daemon_restart_verifier` from the built-in handler
library entirely — source, tests, constants, registry entries, docs, shipped
config — and re-homes its one-line advisory behaviour as a project handler
under `.claude/project-handlers/pre_tool_use/` in THIS repository, dropping
the now-redundant `is_hooks_daemon_repo` gate (a project handler only ever
runs inside the project that declares it). Because a client's
`.claude/hooks-daemon.yaml` is the client's file, not ours, removing the
handler does not remove a leftover `daemon_restart_verifier:` key from an
existing config; that key is registered in `RETIRED_HANDLERS` so the
config validator accepts it silently (a warning surfaced through the
upgrade manifests) instead of degrading the daemon on every session
(Plan 00233's precedent, `constants/handlers.py`).

## Goals

- A project handler at `.claude/project-handlers/pre_tool_use/ daemon_restart_verifier.py` reproduces the built-in's one-line advisory
  behaviour on `git commit` in THIS repository, with `get_claude_md()`,
  acceptance tests, and a co-located test file, configured via the
  project-handler surface (no `is_hooks_daemon_repo` gate needed — a cheap
  sanity check replaces it).
- The built-in handler is removed completely: source file, unit tests,
  `HandlerID`/`Priority`/`HandlerKey` entries, `handler_profiles.py`
  strict-only list, shipped `.claude/hooks-daemon.yaml` /
  `hooks-daemon.yaml.example` keys, and every doc mention
  (`docs/guides/HANDLER_REFERENCE.md`, `CLAUDE/LLM-INSTALL.md`,
  `CLAUDE/Performance/BASELINE.md`), then `.claude/HOOKS-DAEMON.md` and the
  `CLAUDE.md` generated block are regenerated.
- `daemon_restart_verifier` is registered in `RETIRED_HANDLERS`
  (`constants/handlers.py`) with a reason, so a client config that still
  names it gets a clear, silent-accept message rather than the hard
  "Unknown handler" validation error — covered by a regression test.
- The release holding area records the removal: a `config-changes/ v3.64.0.yaml` `removed:` entry that merges cleanly alongside the two other
  in-flight additions to that file (Plan 00367, Plan 00368), and
  release-notes callout 22 is rewritten to describe the removal and the
  project-handler re-home (keeping the file number, renaming the file to
  match).
- A short dogfooding note (`CLAUDE/SELF_INSTALL.md` or
  `CLAUDE/PROJECT_HANDLERS.md`) states that this repository's own
  `.claude/project-handlers/` is the reference example for a project
  standing up its first project handler.
- Every release-bound consequence lands in `CLAUDE/UPGRADES/UNRELEASED/`
  before this plan closes (the holding-area criterion, step 0 of the Plan
  Completion Checklist).

## Non-Goals

- Not a redesign of the project-handler surface itself (discovery,
  `test-project-handlers`, `validate-project-handlers`) — this plan is a
  consumer of that surface, not a change to it.
- Not a change to any OTHER built-in handler's relevance/scoring behaviour;
  Plan 00330's `get_relevance()` mechanism stays as shipped for handlers
  that remain built-in.
- Not a rewrite of the advisory's wording or trigger condition (`git commit`
  in this repo) — behaviour is preserved, only its layer moves.
- Not a versioned upgrade guide under `CLAUDE/UPGRADES/v3/` — Step 9 of
  `CLAUDE/development/RELEASING.md` requires one only when the release's
  CHANGELOG entry is flagged breaking; `RETIRED_HANDLERS` keeps a leftover
  config key a silent accept rather than a crash, matching the v3.53.0
  precedent (16 handlers removed, `config-changes` kept `breaking: false`)
  rather than the v2.11.0/v3.58.0 precedent (marked `breaking: true`) —
  confirmed against the validator before deciding, not assumed.

## Tasks

### Phase 1: Project handler

- [ ] ⬜ **Task 1.1**: `.claude/project-handlers/pre_tool_use/ daemon_restart_verifier.py` — same one-line advisory on a `git commit`
  Bash command in this repository, `get_claude_md()`, `get_acceptance_tests()`,
  no `is_hooks_daemon_repo` gate (replaced by a cheap sanity check since the
  file only ships in this checkout).
- [ ] ⬜ **Task 1.2**: Co-located `test_daemon_restart_verifier.py`
  (TDD: written first) covering init/identity, `matches()` positive and
  negative cases, `handle()` content, acceptance-test declarations.
- [ ] ⬜ **Task 1.3**: `bin/hooks-daemon test-project-handlers --verbose`
  and `validate-project-handlers` both pass with the new handler present.

### Phase 2: Remove the built-in

- [ ] ⬜ **Task 2.1**: Delete
  `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_restart_verifier.py`
  and `tests/unit/handlers/pre_tool_use/test_daemon_restart_verifier.py`.
- [ ] ⬜ **Task 2.2**: Remove `HandlerID.DAEMON_RESTART_VERIFIER`,
  `Priority.DAEMON_RESTART_VERIFIER`, the `HandlerKey` Literal entry, and the
  `_STRICT_ONLY_HANDLERS` entry in `install/handler_profiles.py`; add
  `"daemon_restart_verifier"` to `RETIRED_HANDLERS` with a reason
  referencing this plan.
- [ ] ⬜ **Task 2.3**: Remove the shipped key from
  `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon.yaml.example`, and the
  example block in `daemon/init_config.py`.
- [ ] ⬜ **Task 2.4**: Update every remaining doc mention
  (`docs/guides/HANDLER_REFERENCE.md`, `CLAUDE/LLM-INSTALL.md`,
  `CLAUDE/Performance/BASELINE.md`, `README.md`) and the stale comment in
  `daemon/validation.py` naming the handler as an example hot caller of
  `is_hooks_daemon_repo`. Regenerate `.claude/HOOKS-DAEMON.md` and the
  `CLAUDE.md` generated block via `bin/hooks-daemon regenerate-docs`. Do not
  touch `RELEASES/*.md` history.
- [ ] ⬜ **Task 2.5**: Update the per-handler exemption/expectation maps in
  `tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py`,
  `tests/integration/test_claude_md_guidance_coverage.py`,
  `tests/integration/test_doc_truth_check.py`, and the docstring reference
  in `tests/unit/daemon/test_validation.py` that name the removed class.
- [ ] ⬜ **Task 2.6**: Regression test: a config carrying a leftover
  `handlers.pre_tool_use.daemon_restart_verifier:` key validates without
  error (retired-handler path), while an unrelated typo'd name still hard
  errors.

### Phase 3: Upgrade path + release notes

- [ ] ⬜ **Task 3.1**: `CLAUDE/UPGRADES/UNRELEASED/config-changes/ v3.64.0.yaml` — additive `removed:` entry for
  `handlers.pre_tool_use.daemon_restart_verifier`, written so it merges
  cleanly with Plan 00367's and Plan 00368's independent additions to the
  same file.
- [ ] ⬜ **Task 3.2**: Rewrite `CLAUDE/UPGRADES/UNRELEASED/release-notes/ 22-optimise-no-longer-asks-a-client-for-the-dogfood-handler.md` (rename to
  match) to describe the removal and the project-handler re-home, keeping
  `**Plan**: 00370` and the file number 22.
- [ ] ⬜ **Task 3.3**: Dogfooding note in `CLAUDE/SELF_INSTALL.md` (or
  `CLAUDE/PROJECT_HANDLERS.md`) pointing at this repo's own
  `.claude/project-handlers/` as the reference example.

### Phase 4: QA + verification

- [ ] ⬜ **Task 4.1**: `./scripts/qa/llm_qa.py all` clean on every touched
  file (whole-repo pyright may carry pre-existing errors other in-flight
  branches fix; every other tool, and pyright on touched files, must pass).
- [ ] ⬜ **Task 4.2**: `bin/hooks-daemon test-project-handlers --verbose`
  passes.
- [ ] ⬜ **Task 4.3**: Worktree daemon restarted, confirmed RUNNING, and a
  live `git commit` in the worktree carries the advisory line from the new
  project handler (not the old built-in).

## Success Criteria

- [ ] The project handler exists, is tested, and a real `git commit` in this
  repository's worktree shows the advisory from the PROJECT handler.
- [ ] No trace of the built-in remains in `src/`, `tests/`, shipped config,
  or generated docs; `RETIRED_HANDLERS` accepts a leftover client config key
  silently, proven by a test.
- [ ] `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.64.0.yaml` carries the
  `removed:` entry and merges cleanly with the other two in-flight plans'
  additions to that file.
- [ ] Every release-bound consequence of this plan is in the pending-release
  holding area: the rewritten release-notes callout 22 and the
  `config-changes/v3.64.0.yaml` entry above (`CLAUDE/UPGRADES/UNRELEASED/`).
- [ ] Full QA green on touched files (`./scripts/qa/llm_qa.py all`);
  `test-project-handlers --verbose` passes; worktree daemon restarted and
  verified RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00370-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
