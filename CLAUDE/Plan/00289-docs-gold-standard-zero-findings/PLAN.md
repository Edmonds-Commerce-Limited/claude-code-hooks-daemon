# Plan 00289: docs gold standard zero findings

**Status**: In Progress
**Created**: 2026-08-29
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner has mandated zero docs-qa tech debt ahead of the next release. A
whole-repo `docs-qa --sweep` (Plan 00284's documentation SSoT enforcement,
Plan 00287/00288's follow-on fixes) reported 34 advisory findings. Triaging
them showed they decompose into three different kinds of problem, each
needing a different remedy: genuine checker bugs producing false findings,
genuine documentation debt that needs fixing, and findings that are the
correct behaviour of the checker applied to content the project has
deliberately decided not to police (a frozen historical record, a
self-labelled archived draft).

The work splits into two halves sharing one sweep-to-zero target: the SRC
half (checker bug fixes plus scope-policy decisions, both requiring code and
config changes) and the DOCS half (root `CLAUDE.md` `@`-import conversion,
module-doc thinning/promotion, the `release-agent.md` duplicate block).

## Goals

- Fix the two checker bugs that produced false findings: `pointer-resolves`
  mis-resolving an absolute filesystem path, and `module-doc-budget`'s SWEEP
  and EDIT arms both measuring a REGISTERED module doc against the
  UNREGISTERED routing-table budget instead of its own larger tier.
- Give the docs-qa corpus a deliberate, config-driven scope-exclusion
  mechanism for frozen historical records, distinct from
  `grandfather_allowlist` (which still indexes a file and merely caps its
  severity) — and apply it to the versioned upgrade guides and to
  self-labelled archived/superseded plan drafts.
- Fix the one genuine live-documentation defect in scope: a wrong-depth
  relative link in the (live, not archived) `upgrade-template/`.
- Leave `docs-qa --sweep` reporting zero findings that are this plan's
  responsibility, handing the docs half a clean baseline for its own
  remaining findings (root `CLAUDE.md` imports, module-doc thinning, the
  `release-agent.md` duplicate).

## Non-Goals

- Thinning or promoting module `CLAUDE.md` docs, converting root
  `CLAUDE.md`'s `@`-imports, or resolving the `release-agent.md` duplicate
  block — all owned by the parallel docs half.
- Retroactively fixing dead links or duplicated content genuinely INSIDE a
  frozen historical record. Per `CLAUDE/PlanWorkflow.md`'s "truth is
  enforced on LIVE plans, never on the historical record" principle, a
  frozen upgrade guide or an archived draft is a record of what was true
  when it was written; scope-excluding it is a decision that its content is
  out of scope for enforcement, not a promise to have fixed it first.

## Technical Decisions

### Decision 1: `pointer-resolves` absolute-path resolution

**Context**: a markdown link written as the project's own fully-qualified
filesystem path (`/workspace/CHANGELOG.md`, when `project_root` genuinely IS
`/workspace`) was reported as "does not exist", because the leading `/` was
always treated as the repo-root-relative shorthand convention
(`/CHANGELOG.md` meaning "from the repo root"), which strips the leading `/`
and joins under `project_root` — doubling the root segment
(`/workspace/workspace/CHANGELOG.md`) for a target that was already correct
as written.

**Decision**: try the literal absolute path FIRST (`Path(target).exists()`);
only fall back to the repo-root-relative join if that fails. An absolute
path that exists now PASSES outright — no distinct "unportable path"
message. A distinct message was considered (and is cheap to add) but
rejected: the plan's goal is zero findings, and a link that genuinely
resolves is not a defect, so flagging it forever as an unportability
complaint would trade one kind of permanent noise for another. Both
conventions are still supported: `/workspace/CHANGELOG.md` (literal) and
`/CHANGELOG.md` (repo-root-relative) both resolve.

### Decision 2: `module-doc-budget` registered-doc tiering

**Context**: a REGISTERED module doc (`documentation.qa.registered_module_docs`)
is documented (root `CLAUDE.md`'s generated `<hooksdaemon>` guidance) as
getting "the larger block-tier budget instead" of the 40-line
unregistered routing-table budget. The code did not implement this: both the
EDIT and SWEEP arms shared one `_tiers_for()`/`_finding_for()` pair that gave
a registered doc a BLOCK tier at 900 lines but reused the SAME 40-line
UNREGISTERED advisory tier underneath it — so a registered doc between 40
and 900 lines (e.g. `.claude/ccy/CLAUDE.md` at 65 lines) was still reported
against the unregistered budget, with an "or register it" remediation that
made no sense for a doc that was already registered.

**Decision**: give registered docs their OWN advisory tier, reusing
`plan_qa`'s advisory-tier constant (350 lines) rather than inventing a new
number — mirroring how the existing block tier already reuses `plan_qa`'s
block-tier constant (900 lines). A registered doc is now clean under 350
lines, advisory between 350 and 900, and block-eligible (grow-only,
worse-only) above 900. Both the EDIT and SWEEP arms share the fix, since
both route through the same helper — the SWEEP-only framing in the original
task turned out to also cover EDIT, which had the identical bug.

### Decision 3: corpus scope exclusion for frozen historical records

**Context**: `grandfather_allowlist` already existed for
`CLAUDE/UPGRADES/**`, but it only caps SEVERITY at ADVISE for a file that
stays fully INDEXED — so its links are still checked (and reported,
forever, as advisory noise) and its structured blocks are still compared
against every other document for `duplicate-block`. The versioned upgrade
guides under `CLAUDE/UPGRADES/v2/**` and `v3/**` are frozen records
(`CLAUDE/PlanWorkflow.md`'s live-vs-historical principle): their dead
relative links (files renamed or moved after the guide was written) are
never going to be fixed, and pairing them against a live document in
`duplicate-block` is comparing current truth against a historical snapshot.
The same principle applies to a superseded plan draft kept alongside its
live `PLAN.md` (`CLAUDE/Plan/CLAUDE.md`'s own documented `PLAN-v1.md`
convention) and to any file that self-labels itself an archived record in
its own name.

**Decision**: add a new `documentation.qa.scope_exclude_globs` config field
(model, policy protocol, corpus `_is_excluded`), distinct from
`grandfather_allowlist` by being an exclusion from the corpus ENTIRELY, not
a severity cap. Checked against both the full relative path (for a
directory-scoped pattern) and the bare basename (for a filename-SHAPE
pattern, so `PLAN-v[0-9]*.md` targets the file's own naming convention
regardless of which directory it lives in, without a plain fnmatch over the
full path silently never matching a slash-less pattern at all). This
project's config sets three patterns:

- `CLAUDE/UPGRADES/v[0-9]*/**` — the frozen per-version upgrade guides.
  Deliberately does NOT match the LIVE siblings directly under
  `CLAUDE/UPGRADES/` (`README.md`, `upgrade-template/**`, `UNRELEASED/**`,
  `truth-changes/**`, `config-changes/**`), which stay normally enforced.
- `PLAN-v[0-9]*.md` — a superseded plan draft kept beside its live
  `PLAN.md` (verified against a full-repo scan of `.md` basenames matching
  this shape: only the intended two files, one of which is already inside
  `Completed/` and redundantly excluded by the existing plan-archive rule).
- `*archived*.md` — any file that self-labels itself an archived record in
  its own name (verified the same way: only
  `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md` matches
  repo-wide).

A broader single pattern (`*-v[0-9]*.md`, matching any file whose full path
contains a `-v<N>` segment anywhere) was tried first and rejected: because
`fnmatch`'s `*` matches across `/`, it also matched live, non-archived
documents whose ENCLOSING DIRECTORY happened to be version-named (e.g.
`CLAUDE/Plan/00104-v3.10.0-venv-resolver-dry-consolidation/PLAN.md`), which
would have wrongly scope-excluded a live plan's own current-truth document.
The narrower basename-only patterns avoid this because a slash-less pattern
only ever matches the FILE's own name, never a parent directory segment.

The old `grandfather_allowlist: ["CLAUDE/UPGRADES/**"]` entry is removed:
everything it covered is now either scope-excluded (the frozen `v[0-9]*`
guides) or was never meant to be grandfathered at all (the live siblings,
which should be normally enforced — Task 4 below fixed a genuine defect in
one of them).

### Decision 4: live-template dead link

`CLAUDE/UPGRADES/upgrade-template/README.md`'s "Full changelog" link used
`../../CHANGELOG.md` (two levels up, landing on `CLAUDE/CHANGELOG.md`,
which does not exist) instead of `../../../CHANGELOG.md` (three levels up,
to the real repo-root `CHANGELOG.md`). The template's other two links at the
same depth (`../README.md`, `../../HANDLER_DEVELOPMENT.md`) were already
correct. `BREAKING-CHANGES-TEMPLATE.md`'s apparently-wrong-depth links to
`../CLAUDE/UPGRADES/v2/...` are inside fenced ```` ```markdown ```` code blocks —
illustrative example content, not real links (`extract_link_targets`
correctly never sees them, via `lines_outside_fences`) — so nothing there
needed fixing.

## Tasks

### Phase 1: SRC half (checker bugs, scope policy, live-template fix)

- [x] ✅ **Task 1**: Fix `pointer-resolves`'s absolute-path double-root bug
  (Decision 1). TDD: failing tests added to
  `tests/unit/docs_qa/checks/test_pointer_resolves.py` (EDIT-stage
  integration case + a direct `_resolves()` regression case), fix in
  `src/claude_code_hooks_daemon/docs_qa/checks/pointer_resolves.py`.
- [x] ✅ **Task 2**: Fix `module-doc-budget`'s registered-doc tiering
  (Decision 2). TDD: existing test encoding the buggy behaviour replaced
  with the corrected contract, new EDIT- and SWEEP-arm regression tests
  added to `tests/unit/docs_qa/checks/test_module_doc_budget.py`, fix in
  `src/claude_code_hooks_daemon/docs_qa/checks/module_doc_budget.py`.
- [x] ✅ **Task 3**: Add `documentation.qa.scope_exclude_globs` and apply it
  (Decision 3). New config field in
  `src/claude_code_hooks_daemon/config/models.py`
  (`DocumentationQaConfig`), `src/claude_code_hooks_daemon/docs_qa/policy.py`
  (dataclass, Protocol, `policy_from_config`), matching logic in
  `src/claude_code_hooks_daemon/docs_qa/corpus.py` (`_matches_scope_exclude`,
  wired into `_is_excluded`). This repo's `.claude/hooks-daemon.yaml` sets
  the three patterns and drops the superseded `grandfather_allowlist` entry.
- [x] ✅ **Task 4**: Fix the wrong-depth link in
  `CLAUDE/UPGRADES/upgrade-template/README.md` (Decision 4).

## Success Criteria

- [x] `pointer-resolves` no longer reports a false "does not exist" for an
  absolute path that is the project's own fully-qualified path.
- [x] `module-doc-budget` measures a registered doc against its own tier at
  both EDIT and SWEEP stages; a registered doc under 350 lines is clean.
- [x] `CLAUDE/UPGRADES/v2/**` and `v3/**`, a superseded plan draft
  (`PLAN-v[0-9]*.md`), and a self-labelled archived file (`*archived*.md`)
  are invisible to `pointer-resolves` and `duplicate-block`, while their
  live siblings under `CLAUDE/UPGRADES/` remain normally enforced.
- [x] The live `upgrade-template/README.md` changelog link resolves.
- [x] `docs-qa --sweep` reports zero findings attributable to this plan's
  scope (verified: 34 → 1 remaining finding, the `release-agent.md`
  duplicate block owned by the parallel docs half).
- [ ] Full QA suite (`./scripts/qa/llm_qa.py all`) green.
- [ ] Daemon restarts and reports RUNNING with the new code.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00289-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- SRC-half work (Tasks 1-4) implemented and unit-tested; commit hashes to
  follow once QA/daemon-restart verification completes.
