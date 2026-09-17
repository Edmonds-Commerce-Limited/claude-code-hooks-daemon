# Plan 00429: format markdown crosses repo boundaries

**Status**: In Progress
**Created**: 2026-09-17
**GitHub Issue**: #47
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`hooks-daemon format-markdown <dir>` walks with a bare `path.rglob("*")` and
formats every markdown file it finds. It applies no exclusion of any kind — no
`daemon.exclude_paths`, no gitignore awareness, and no repository boundary — so
run from a project root that vendors dependencies as real git checkouts it
rewrites files inside a DIFFERENT repository and leaves uncommitted changes
there.

**Reproduced at triage, not inferred.** With a fixture containing a nested git
checkout under `vendor/dep/`, the command printed `Reformatted:` for the
vendored file, and `git -C .../vendor/dep status --short` then reported
` M docs/b.md` in a repository the caller does not own.

The severity is not "wrong output". This command WRITES, and it writes outside
the tree the caller pointed it at in any meaningful sense. The housekeeping
skill's documented invocation is `format-markdown .`, so the damaging case is
the normal one.

## What is already true

- `cmd_format_markdown` (`daemon/cli.py:5100`) receives only `args` — `config`
  is never passed in, so the reporter's "configuration ruled out" is correct:
  no setting can reach this walk.
- `git log -S "cmd_format_markdown"` shows one introducing commit and no later
  exclusion work. Never built, never reverted.
- The pattern to reuse EXISTS. Plan 00362 Task 2.9 threaded
  `config.daemon.exclude_paths` through the docs-qa and plan-qa CLIs for
  exactly this reason ("a by-hand run must agree with what the handlers skip"),
  and `utils/path_exclusion` already provides `is_path_excluded` /
  `path_matches_globs`. This plan reuses that utility rather than inventing a
  second filter.

## The fix must be BOTH halves, and that is a deliberate ruling

The issue offers repository boundaries **or** `daemon.exclude_paths`. Treated as
a hypothesis rather than a specification, each alone leaves the defect's class
open:

- **`exclude_paths` alone** protects only a project that already thought to
  list `vendor/**`. Not having thought of it is precisely the situation the
  reporter was in, so the default-configuration case — every fresh install —
  stays broken.
- **Repository boundary alone** still rewrites excluded-but-same-repo trees
  (`untracked/**` and friends), which is the thing `exclude_paths` exists to
  prevent and which the sibling CLIs already honour.

They also differ in kind, which is the real argument for both: the boundary
check is a SAFETY default that needs no configuration and protects a repo the
caller does not own, while `exclude_paths` is the project's declared preference
about its own tree. Collapsing them into one mechanism would make a safety
property opt-in.

**`--check` mode is the same defect**, not a separate one: it reports
`Would reformat:` for foreign files and returns non-zero, so a CI gate fails on
a file the project does not own. One fix covers both modes.

## Goals

- `format-markdown <dir>` never writes to, or reports on, a file inside a
  nested git repository below the walk root.
- It honours `daemon.exclude_paths`, agreeing with the sibling CLIs.
- A regression test reproduces the vendored-checkout case and fails before the
  fix.

## Non-Goals

- **Gitignore awareness.** The issue names it as a third missing mechanism.
  Formatting a gitignored file is materially less harmful — it is untracked, so
  nothing is silently modified in anyone's history — and `exclude_paths` is
  this project's declared exclusion mechanism, already honoured by the sibling
  CLIs. Adding a third source here would mean three answers to "is this file
  mine?" in one walk. Out of scope, recorded rather than forgotten.
- Changing the `markdown_table_formatter` HANDLER. The defect is in the CLI
  walk; the handler judges one file it is handed.
- Any change to what mdformat does to a file it is correctly given.

## Tasks

### Phase 1: reproduce and fix

- [x] ✅ **Task 1.1**: RED test first — a fixture with a nested git checkout
  below the walk root, asserting the nested repo is untouched and that
  `--check` does not report it either. It must fail before the fix, with the
  failure quoted.
- [x] ✅ **Task 1.2**: Skip any directory below the walk root that is itself a
  git repository. The walk root's own repo is not a boundary — only a NESTED
  one is — so a normal `format-markdown .` on an ordinary project is unchanged.
- [x] ✅ **Task 1.3**: Honour `daemon.exclude_paths` via
  `utils/path_exclusion`, matching how the docs-qa and plan-qa CLIs load and
  apply it. Exclusions resolve against the project root, as they do there.
  Review found the first implementation loading the config from the WALK root,
  which made `format-markdown <subdir>` apply no exclusions at all; probed
  live, fixed in `06bb8fee` with `_enclosing_project_root`.
- [x] ✅ **Task 1.4**: Confirm the sibling behaviour is unchanged: a file
  argument (not a directory) is still formatted even if excluded, because the
  caller named it explicitly. Decide and pin this rather than leaving it
  implicit.

### Phase 2: prove and ship

- [ ] ⬜ **Task 2.1**: Full QA in the worktree; read `QA_EXIT` on its own line.
- [x] ✅ **Task 2.2**: Release note — this is user-visible behaviour a client
  will notice. `UNRELEASED/release-notes/07-format-markdown-stays-inside-your-repository.md`.

## Success Criteria

- [ ] The reproduction from the issue leaves the nested repo clean.
- [ ] Every release-bound consequence is in the pending-release holding area.
- [ ] #47 carries a closing comment saying what was wrong, what changed, how it
  was verified, and anything found that the reporter did not report.

## Delivery & Milestones

- Filed by the issue-sdlc loop from issue #47; triaged actionable, reproduced
  before any code was written.
