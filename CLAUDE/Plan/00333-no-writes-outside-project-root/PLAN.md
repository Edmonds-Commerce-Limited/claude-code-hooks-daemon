# Plan 00333: no writes outside project root

**Status**: In Progress
**Created**: 2026-09-06
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct implementation with sub-agent survey support

## Overview

Every path guard in this daemon is expressed in repo-relative coordinates, and
the absolute-to-relative conversion **is** the containment test. When that
conversion fails the uniform verdict is *allow*: `markdown_organization.py:956`
catches the `ValueError` and returns `False`, and eight further handlers do the
same — `sensitive_content.py:358` even comments *"Outside the project root: not
ours to judge"*. So `/workspace/notes.md` is denied and `/tmp/notes.md` is
silently allowed. Not one of the 88 rule IDs in `constants/rule_ids.py` encodes
an out-of-root concept.

The single exception proves the mechanism is available: R-MARKDOWN-UNTRACKED-MEMORY
guards `~/.claude/projects/*/memory/*.md`, an out-of-repo path, because it is a
**raw-string marker** rule (`_is_claude_memory_path`, `:852`) evaluated *before*
the out-of-root return, and it already covers the Bash side-door including `cp`.

The harm is durability. `/tmp` is container-ephemeral while the repo is a bind
mount, so anything written there is lost on restart, invisible to git, and
outside review. The project already holds this position in three places —
`daemon/paths.py:7` (*"All runtime files stored in daemon's untracked directory,
not /tmp, to prevent security vulnerabilities"*), `scripts/echd-capture:69`
(prefers `untracked/captures`, calls `/tmp` a *"last resort"*), and
`worktree_seed_suggestions.py:57` (calls `untracked/` *"this daemon's own scratch
convention"*). It was never made a rule, so tools obeyed it and the agent did not.

Owner ruling: never allow `/tmp` at all; use `untracked/`, and create it when it
does not exist.

## Goals

- A write whose target is named outside the repository root is DENIED, on both
  the Write/Edit/NotebookEdit surface and the Bash surface.
- `untracked/scratch/` exists, is correctly ignored, and is named in guidance as
  the sanctioned location — bootstrapped in consumer projects, not assumed.
- No surface of the daemon recommends `/tmp` to an agent any more.
- Reads are unaffected.

## Non-Goals

- **Policing what a program does at runtime.** A PreToolUse hook receives a
  command string, not syscalls; it cannot see `tmp_path` and must not pretend
  to. Measured on this container: of 324 MB in `/tmp`, 308 MB is
  `pytest-of-root/` and 2,415 of 2,834 entries are zero-length `uv-*.lock`
  files. A guard fighting uv, pytest, pyright, node and semgrep would be
  switched off within a day.
- Blocking reads of out-of-root paths.
- Changing `markdown_organization`'s out-of-root behaviour (see Decision 1).
- Deleting the existing `/tmp` residue — triaged, nothing unique (Decision 5).

## Tasks

### Phase 1: Reproduction (RED)

- [ ] ⬜ **Task 1.1**: Failing test proving a `Write` to an absolute path outside
  the repo root is allowed through the whole PreToolUse chain.
- [ ] ⬜ **Task 1.2**: Failing test proving the same for a Bash write target
  (`> /tmp/x`, `tee`, heredoc, and a `cp` target).

### Phase 2: The guard

- [ ] ⬜ **Task 2.1**: New PreToolUse handler denying out-of-root write targets,
  keyed on `get_file_path` and `get_bash_write_targets`.
- [ ] ⬜ **Task 2.2**: Register the rule ID and wire config options.
- [ ] ⬜ **Task 2.3**: Satisfy every enumerated handler meta-test.
- [ ] ⬜ **Task 2.4**: Deny message names `untracked/scratch/` and states why.

### Phase 3: The affordance

- [ ] ⬜ **Task 3.1**: Bootstrap `untracked/` + `untracked/scratch/` when absent,
  with the `*` / `!.gitignore` ignore file, and verify it is ignored.
- [ ] ⬜ **Task 3.2**: Document the scratch convention in the agent tree.

### Phase 4: Stop recommending /tmp

- [ ] ⬜ **Task 4.1**: `pipe_blocker._temp_file_block` (`:766`) emits an
  in-repo scratch path instead of `/tmp/output_$$.txt`.
- [ ] ⬜ **Task 4.2**: Replace the ambiguous *"an untracked location"* phrasing
  in `src/CLAUDE.md` and `tests/CLAUDE.md` with the named directory.
- [ ] ⬜ **Task 4.3**: Sweep remaining `/tmp` recommendations in agent-facing docs.

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: Full QA gate green.
- [ ] ⬜ **Task 5.2**: Daemon restarted and the guard verified live.
- [ ] ⬜ **Task 5.3**: Regenerate the generated docs surfaces.

## Technical Decisions

### Decision 1: a new handler, not a change to `markdown_organization`

Its out-of-root early return is correct **for its own premise** — markdown
*organisation* genuinely has nothing to say about a file that is not in the
project — and the behaviour is pinned by
`test_markdown_organization.py:697-711`. Containment is a separate premise and
gets its own handler, so no existing test is weakened to make room.

### Decision 2: the boundary is the repository root, not the sub-project root

`untracked/` lives at the repo root, so in a monorepo a sub-project writing to
the shared scratch directory must not be denied.

### Decision 3: deny-by-default with an empty allowlist

Owner ruling. The allowlist is configurable so a genuine need can be declared,
but nothing is pre-seeded — a declared exemption is a decision, an assumed one
is a hole.

### Decision 4: `exclude_paths` cannot express this, so the handler owns its config

For `/tmp/foo.md` against root `/workspace`, `os.path.relpath` yields
`../tmp/foo.md`, so `path_exclusion.py:107-121` drops the project-relative
candidate entirely and anchored patterns can never match out-of-repo paths.

### Decision 5: the existing residue is not swept by this plan

Triaged: the only authored file in `/tmp` outside tool directories was
`blacktest/provenance.py`, the pre-`black` copy of a tracked source file. There
is nothing to preserve, and deletion is the owner's call, not this plan's.

## Success Criteria

- [ ] A `Write` to `/tmp/anything` is denied, with a message naming the
  sanctioned location.
- [ ] `> /tmp/x`, `tee /tmp/x`, a heredoc to `/tmp/x` and `cp f /tmp/` are denied.
- [ ] A write anywhere inside the repo root is unaffected.
- [ ] Reading an out-of-root path is unaffected.
- [ ] `untracked/scratch/` exists and `git check-ignore` confirms it is ignored.
- [ ] No daemon-emitted guidance string recommends `/tmp` to an agent.
- [ ] The full QA gate is green and the daemon restarts cleanly.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
