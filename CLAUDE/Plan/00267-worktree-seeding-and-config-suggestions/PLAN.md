# Plan 00267: Worktree seeding and config suggestions

**Status**: In Progress
**Created**: 2026-08-25
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A fresh git worktree is a clean checkout, so the git-ignored local files that
make the main checkout work — local env files, local settings, local secrets —
are simply absent. An `isolation: "worktree"` agent then runs against a
different configuration from the session that spawned it, and behaves
differently for reasons nothing surfaces.

This plan makes the `worktree_create` handler seed a fresh worktree from a
**project-owned** list of paths, where the project chooses per entry whether
each is **symlinked** (shared truth, writes flow back to the main checkout) or
**copied** (isolated, may drift), and may name **files or directories**.

Because no shipped default can know which git-ignored files a given project
has, the plan also adds a **suggestion generator**: it scans the repo, proposes
entries, and diffs the current config against those suggestions. One
implementation serves both install/upgrade time and ad-hoc invocation.

Full design detail — inherited review findings, config shape, validation
policy, CLI contract — is in [DESIGN.md](DESIGN.md).

## Goals

- On fresh worktree creation, seed a project-configured list of paths, each
  symlinked or copied per the project's choice, supporting files and
  directories.
- Symlinks are **relative**, so they survive the same tree being viewed at
  different absolute prefixes (host vs container bind-mount).
- Fail fast on an entry that cannot be honoured, **before** the worktree is
  created, so there is never a partially-seeded worktree.
- Never clobber a destination that already exists.
- Generate config suggestions by scanning the repo, and report drift between
  the current config and those suggestions.
- The project owns its config: suggestions are reported, and written only on
  explicit request.

## Non-Goals

- **Not** rebuilding config preservation — the daemon config file already
  receives a three-way merge on upgrade, and the seed config inherits it
  (DESIGN §6).
- **Not** seeding tracked files; git already provides those in the checkout.
- **Not** glob or wildcard expansion in the entry list — explicit paths only.
- **Not** on by default; a shared upstream daemon must not start failing
  worktree creation in repos that simply lack these files.
- **Not** resuming the superseded branch — see DESIGN §1.

## Context & Background

An earlier attempt exists, unmerged, on the remote branch
`plan/00190-worktree-create-seed-env-files` (self-renumbered Plan 00191). It
conflicts with current `main` and its config shape cannot express the
per-entry mode choice. It is superseded; its hostile Opus review is distilled
into DESIGN §2 and its findings are carried as binding constraints here.

Phase 1 addresses a **pre-existing bug**, not scaffolding for this feature:
the handler never resolves the git top-level, so worktrees already land in the
wrong place for a session whose cwd is a subdirectory (DESIGN §3).

## Tasks

### Phase 1: Resolve the repository root (pre-existing bug)

- [x] ✅ **Task 1.1**: Failing test — a worktree created from a subdirectory
  cwd lands at the repo root, not under the subdirectory
- [x] ✅ **Task 1.2**: Use the existing `GitRepo.resolve_for` helper in the
  handler; introduce no new top-level resolver
- [x] ✅ **Task 1.3**: Test + handling for the not-a-git-repo case — an
  unresolvable root falls back to cwd, so git still refuses loudly
- [x] ✅ **Task 1.4**: Record the existence-check idempotency limitation in the
  handler docstring (it is blind to git's own worktree registry)

### Phase 2: Seed config schema and validation

- [x] ✅ **Task 2.1**: Tests for the parser — bare string, unknown mode,
  unknown key, missing path, non-list entries
- [x] ✅ **Task 2.2**: Frozen dataclass for a parsed entry, raising on the
  trusted construction path
- [x] ✅ **Task 2.3**: Defensive parser: shape errors warn and skip, never
  raise (house idiom)
- [x] ✅ **Task 2.4**: Lazy parse into a memo field — options arrive after
  `__init__`, so nothing is parsed in the constructor

### Phase 3: Seeding execution

- [x] ✅ **Task 3.1**: Tests for symlink mode
  - [x] ✅ link is **relative** and survives tree relocation to a new prefix
  - [x] ✅ edits to the canonical file are visible through the link
  - [x] ✅ an entry nested one directory deep creates its parent directories
- [x] ✅ **Task 3.2**: Tests for copy mode
  - [x] ✅ a copied file is independent — editing the source does not change it
  - [x] ✅ a copied directory is recursive
  - [x] ✅ writing the copy does not touch the main checkout
- [x] ✅ **Task 3.3**: Tests for fail-fast content errors — absent source,
  absolute path, parent traversal — each raising **before** creation, with
  every offending entry named in one message
- [x] ✅ **Task 3.4**: Tests for never-clobber (including a *dangling*
  destination symlink) and no re-seed on idempotent re-fire
- [x] ✅ **Task 3.5**: Implement seeding to pass Tasks 3.1–3.4, in
  `utils/worktree_seeding.py`, and wire it into the handler
- [x] ✅ **Task 3.6**: Containment check — the resolved target stays under the
  repo root, guarding a symlinked path component

### Phase 4: Suggestion generator

- [x] ✅ **Task 4.1**: Tests for the scanner — proposes git-ignored
  local-config shapes, excludes tracked files and build/vendor/cache dirs
- [x] ✅ **Task 4.2**: Implement the scanner over a repo path, asking **git**
  what is ignored rather than reimplementing gitignore semantics
- [x] ✅ **Task 4.3**: Tests for the diff — configured-but-absent and
  present-but-unconfigured. **Mode mismatch was deliberately NOT implemented**
  as drift: the mode is the choice this feature exists to give the project, so
  flagging a deliberate `copy` against a suggested `symlink` would nag about a
  decision already made. A test pins that it is not reported (DESIGN §8)
- [x] ✅ **Task 4.4**: Implement the diff. The dotted-path config helpers were
  **not** reused — see DESIGN §8; they answer a different question

### Phase 5: CLI command and install/upgrade entry point

- [x] ✅ **Task 5.1**: A `run_*` function in the install config CLI layer
  returning a plain dict; zero logic in the argument parser module
- [x] ✅ **Task 5.2**: Register the subcommand with a text/json format flag and
  a dry-run default. **No explicit-write flag was built** — PyYAML cannot
  round-trip comments, so writing would strip the config's own documentation.
  A paste-ready YAML block is rendered instead (DESIGN §9)
- [x] ✅ **Task 5.3**: Exit-code contract — 0 clean, 1 drift, 2 operational
  error; a test for each
- [x] ✅ **Task 5.4**: Invoke the **same** command from install/upgrade so the
  scan has exactly one implementation
- [x] ✅ **Task 5.5**: Dogfooding the finished command against this repository
  exposed two false negatives in the Phase 4 heuristics; patterns widened with
  a regression test for the non-config artefacts (DESIGN §9)

### Phase 6: Integration, docs and dogfooding

- [ ] ⬜ **Task 6.1**: `get_claude_md()` — state both modes' hazards, including
  symlink write-through to the main checkout
- [ ] ⬜ **Task 6.2**: Document the option in the shipped example config
- [ ] ⬜ **Task 6.3**: Add the missing `worktree_create` block to this repo's
  own daemon config and dogfood the feature
- [ ] ⬜ **Task 6.4**: Add a config-changes manifest entry for the new option
- [ ] ⬜ **Task 6.5**: Full QA green; daemon restart verified RUNNING
- [ ] ⬜ **Task 6.6**: Decide the fate of the superseded remote branch once its
  value is fully harvested

## Dependencies

- Supersedes: the unmerged branch `plan/00190-worktree-create-seed-env-files`
  (self-renumbered Plan 00191), never merged to `main`
- Related: Plan 00176 — the same config-ownership problem on a different file;
  its daemon-owned / recommended-default / client-owned key model is the right
  vocabulary, and the seed list is client-owned
- Related: Plan 00189 — touches the same handler on a different concern

## Technical Decisions

Recorded in full in [DESIGN.md](DESIGN.md). In brief:

1. **Per-entry mode with a project default** (DESIGN §4) — a flat list for the
   common case, dict entries where precision is needed. Follows an established
   handler-option idiom rather than inventing one.
2. **Shape warns, content fails** (DESIGN §5) — a mis-typed config cannot be
   guessed at, but a clear intention the daemon cannot fulfil must not degrade
   to a quietly under-seeded worktree.
3. **Relative symlinks always** (DESIGN §2) — carries a HIGH finding with a
   reproduced failure across host and container path views.
4. **One suggestion implementation, two entry points** (DESIGN §6) — separate
   install-time and ad-hoc paths would duplicate the scan and drift apart.

## Success Criteria

- [x] A worktree created from a subdirectory cwd lands at the repo root
- [x] A fresh worktree contains the configured entries, symlinked or copied per
  the project's per-entry choice, for both files and directories
- [x] Symlinks are relative and resolve after the tree is relocated
- [x] A content error aborts before creation; no partially-seeded worktree
- [x] The suggestion command reports this repo's own missing `worktree_create`
  block, and exits 1 on drift
- [ ] No secrets in code, tests or fixtures
- [ ] Full QA green; daemon restart verified RUNNING

## Risks & Mitigations

| Risk                                                                      | Impact | Probability | Mitigation                                                                           |
| ------------------------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------------ |
| Symlink write-through clobbers a real secrets file from inside a worktree | High   | Medium      | Per-entry mode; hazard stated in guidance; copy available for anything writable      |
| Suggestion scanner proposes a file containing secrets                     | High   | Low         | Suggestions are reported, never auto-written; the path is named, contents never read |
| Phase 1 root change alters existing worktree locations                    | Medium | Medium      | It corrects placement that is already wrong; covered by tests before the change      |
| Scope spans handler, CLI and install                                      | Medium | High        | Phases are independently shippable; Phase 1 stands alone as a bug fix                |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00267-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
