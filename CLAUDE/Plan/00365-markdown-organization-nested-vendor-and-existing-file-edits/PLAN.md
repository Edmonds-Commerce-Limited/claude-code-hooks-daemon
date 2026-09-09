# Plan 00365: markdown_organization — a declared project at any depth, nested vendor trees, existing-file edits

**Status**: In Progress
**Created**: 2026-09-09
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Field report (imported as [FIELD-REPORT.md](FIELD-REPORT.md)): on v3.63.0,
`markdown_organization` (R-MARKDOWN-WRONG-LOCATION) denies an `Edit` of an
EXISTING `.md` file inside a first-party git clone vendored two `vendor/`
levels deep, and neither escape hatch changes the verdict — not an
`extra_allowed_markdown_paths` regex that matches the path, not a `projects:`
declaration for the clone. The same edit one `vendor/` level down is allowed.

**The owner's ruling on the report**: the correct solution is to define the
sub-project properly in the top-level config — a `projects:` entry whose
`root` is the directory as it actually is, vendored, vendored-inside-vendored,
or anything else — and that declaration must simply work. That is the primary
fix; everything else here is secondary hygiene.

Reproduced against the handler on main. Three defects, one root:

1. The dependency-prefix branch in `matches()` runs BEFORE
   `_declared_subproject_relative` and returns early, so a `projects:` entry
   whose root sits under `vendor/` is never consulted.
2. `_strip_dependency_prefix` strips exactly one `vendor/{a}/{b}/` level and
   the remainder is judged by `_is_invalid_location`, which has no dependency
   stripping, so `vendor/lts/…/docs/x.md` is judged as a plain path and blocked.
3. `_matches_extra_allowed` is tested only against the package-relative
   remainder, never the repo-relative path, so a pattern anchored at
   `^vendor/…` cannot match.

And one message defect: the rule text says "a new `.md` file written to an
unrecognised location" for an `Edit` of a file that already exists. The
handler's purpose is where NEW markdown lands; a file that already exists at a
path has already had its location accepted (by a commit, a vendor install, or
an earlier allowed write), and editing it moves nothing.

## Goals

- A `projects:` declaration resolves a file to its sub-project for ANY root —
  under `vendor/`, `node_modules/`, another declared project, anywhere — and
  the declaration beats the built-in dependency-directory inference. The deny
  message for a path under a dependency directory names `projects:` as the
  fix.
- The dependency-directory inference applies at every nesting level
  (`vendor/a/b/vendor/c/d/docs/x.md` → `docs/x.md`).
- `extra_allowed_markdown_paths` matches against BOTH the repo-relative path
  and the project-relative path.
- An `Edit` of, or a `Write` to, a `.md` file that already exists on disk is
  never a location violation, and the deny text for a genuinely new file says
  "new".

## Non-Goals

- Inferring sub-projects from directory shape without a declaration (Plan
  00300 removed that on purpose; the report does not ask for it back and the
  owner's ruling is that the declaration IS the mechanism).
- Rewiring the other handlers `CLAUDE/Code/WorkspaceResolution.md` lists as
  still on `ProjectContext.project_root()`; this plan fixes the one the
  report names and records the others in the journal.

## Tasks

### Phase 1: reproduce and fix

- [ ] ⬜ **Task 1.1**: Regression tests (RED) for the three path defects and
  the existing-file case, using the report's shape with neutral names
  (`vendor/org-a/pkg-a/vendor/org-b/pkg-b/docs/guide.md`), including a
  `projects:` entry whose root is that nested clone.
- [ ] ⬜ **Task 1.2**: Declared `projects:` resolution runs FIRST in
  `matches()`; a declared root anywhere wins over dependency inference. The
  deny message for a dependency-directory path points at `projects:`.
- [ ] ⬜ **Task 1.3**: Dependency-prefix stripping repeats until no
  `vendor/`/`node_modules/` prefix remains.
- [ ] ⬜ **Task 1.4**: `_matches_extra_allowed` is tried on the repo-relative
  path as well as the project-relative one.
- [ ] ⬜ **Task 1.5**: A `.md` that already exists at the target path is not
  a location violation for `Edit` or `Write`; the acceptance playbook and
  `get_claude_md()` guidance say so.

### Phase 2: closure

- [ ] ⬜ **Task 2.1**: Full QA 26/26; daemon restart; release-notes callout;
  `CLAUDE/Code/WorkspaceResolution.md` names `markdown_organization` as
  rewired; plan archived.

## Success Criteria

- [ ] The report's `Edit` is allowed with the declaration alone, and also
  with the regex alone, and also with no config at all (existing file).
- [ ] `vendor/a/b/random/notes.md` (a genuinely new misplaced file, no
  declaration) is still blocked, and the message names `projects:`.
- [ ] `./scripts/qa/llm_qa.py all` green.

## Delivery & Milestones

- Filed from the field report the day after v3.63.0 shipped.
