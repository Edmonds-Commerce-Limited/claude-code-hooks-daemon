# Plan 00333: no writes outside project root

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Failing test proving a `Write` to an absolute path outside
  the repo root is allowed through the whole PreToolUse chain. The result was
  sharper than expected: `handlers_matched=[]` — nothing even considered it.
- [x] ✅ **Task 1.2**: Failing test proving the same for a Bash write target
  (`> /tmp/x`, `tee`, heredoc, and a `cp` target).

### Phase 2: The guard

- [x] ✅ **Task 2.1**: New PreToolUse handler denying out-of-root write targets,
  keyed on the named target of Write/Edit/NotebookEdit and on
  `get_bash_write_targets`.
- [x] ✅ **Task 2.2**: Register the rule ID and wire config options.
- [x] ✅ **Task 2.3**: Satisfy every enumerated handler meta-test — 14 of them,
  including the command-respelling evasion triage a survey of the test tree
  had missed.
- [x] ✅ **Task 2.4**: Deny message names `untracked/scratch/` and states why.
- [x] ✅ **Task 2.5**: Allow Claude Code's own state directory (owner ruling),
  configurable off, without re-opening untracked Claude auto-memory.

### Phase 3: The affordance

- [x] ✅ **Task 3.1**: Bootstrap `untracked/` + `untracked/scratch/` when absent,
  with the `*` / `!.gitignore` ignore file, and verify it is ignored.
- [x] ✅ **Task 3.2**: Document the scratch convention in the agent tree
  (`DirectoryRoles.md`, the canonical per-directory ruleset).

### Phase 4: Stop recommending /tmp

- [x] ✅ **Task 4.1**: `pipe_blocker._temp_file_block` emits an in-repo scratch
  path instead of `/tmp/output_$$.txt`, from a shared `ProjectPath` constant so
  the denying and recommending handlers cannot drift apart.
- [x] ✅ **Task 4.2**: Replace the ambiguous *"an untracked location"* phrasing
  in `src/CLAUDE.md` and `tests/CLAUDE.md` with the named directory.
- [x] ✅ **Task 4.3**: Sweep remaining `/tmp` recommendations in agent-facing docs
  (7 snippets across the debugging, QA, install and update guides).
- [x] ✅ **Task 4.4**: Migrate the acceptance-test corpus off `/tmp`. Larger
  than first scoped: 15 handler modules AND 49 strategy modules. Not cosmetic —
  containment is terminal at priority 14, so a `mkdir -p /tmp/fixture` setup
  command is denied outright and a Write to `/tmp` is denied by containment
  rather than by the handler under test, making the expected patterns
  unmatchable. Paths must land absolute (Decision 10).
- [x] ✅ **Task 4.5**: Catch destination-naming bashisms — `curl -o|--output`,
  `wget -O`, `tar` creating an archive, `mkdir`, `rsync`/`scp`, and any of them
  nested inside `sh -c`/`bash -c`. Handler-local rather than a widened shared
  accessor (Decision 7), command-keyed rather than generic (Decision 8).
  Interpreter one-liners remain out of scope: resolving them needs execution,
  which a PreToolUse hook must never do.
- [x] ✅ **Task 4.6**: Pin the Claude Code `permissions.deny` backstop to
  `ProjectPath.EPHEMERAL_ROOTS` by test, in both directions, so the two layers
  cannot drift (Decision 9).

### Phase 5: Verify

- [x] ✅ **Task 5.1**: Full QA gate green.
- [x] ✅ **Task 5.2**: Daemon restarted and the guard verified live.
- [x] ✅ **Task 5.3**: Regenerate the generated docs surfaces.

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

### Decision 6: Claude Code's own state directory is allowed

Owner ruling. It is not scratch, and where it is mapped into the bind mount it
has the durability this guard protects, so the reason the temp directory is
refused does not apply. Independent of `markdown_organization`'s block on
untracked auto-memory: containment asks whether a path is DURABLE, that rule
asks whether it is REVIEWABLE, and memory fails the second while passing the
first. Configurable off for an environment that does not map it durably.

### Decision 7: destination extraction is handler-local, not a widened accessor

`get_bash_write_targets` answers "what content did this command AUTHOR", which
is why Plan 00260 excluded `cp`/`mv` from the content linters: a copy relocates
bytes it did not write, so blaming it would report a defect it did not
introduce. Containment asks a different question — a file lands outside the
repository just as thoroughly whether the command authored it or fetched it.

Two different premises want two different target sets, so the extra
destinations (`curl -o`, `wget -O`, `tar -cf`, `mkdir`, `rsync`/`scp`, nested
`sh -c`) are resolved in the handler. Widening the shared accessor to serve
containment would have changed the verdicts of 22 dependent handlers — a
linter would start firing on `curl -o x.py`, a file it did not author, which is
precisely the mistake Plan 00260 documented.

### Decision 8: output flags are command-keyed, never generic

`-o` does not mean "output file" everywhere. `grep -o` is only-matching and
takes no argument, so a blind "token after `-o`" rule reads grep's PATTERN as a
destination and denies a command that writes nothing. Likewise `tar -xf`
extracts FROM a path and is a read; only a create flag makes the archive a
destination. Same contract as the shared accessor: a wrong path is worse than
no path.

### Decision 9: the Claude Code layer is a backstop, not a second whitelist

Verified against the official documentation: a write-whitelist is **not
expressible** in Claude Code settings. Rules evaluate deny → ask → allow with
the first match winning, so a broad `Edit(//**)` deny cannot carry an allow
exception for the project; there is no negation syntax; and there is no writes
counterpart to `blockReadsOutsideWorkingDirectories`. Enumeration is the only
available shape there, which is exactly why the daemon handler — deny-by-default
and whitelist-shaped — remains the control. The enumeration is pinned to
`ProjectPath.EPHEMERAL_ROOTS` by test so the two layers cannot drift.

### Decision 10: a migrated fixture path must stay ABSOLUTE

The first cut of Task 4.4 moved `/tmp/fixture` to `untracked/scratch/fixture`
and kept it relative. That preserved the location and lost the property that
made the original work. The playbook renders each `AcceptanceTest.command`
verbatim for an agent to follow, so a relative `file_path` in a Write
instruction is denied by `AbsolutePathHandler` (terminal, priority 12) before
the handler under test is ever reached — the test then observes
R-ABSOLUTE-PATH-REQUIRED and can never pass. `/tmp` worked *because* it was
absolute, not merely because it existed.

`scratch_path()` resolves the live project root, landing on the same side of
the split `utils/cli_command` documents as `daemon_cli_command`: the playbook
is generated on demand for the machine it runs on and is not a tracked
artefact, so resolving is correct rather than a leak.

The inverse holds for `get_claude_md()`, and it is the half a bulk migration
gets backwards: that text IS committed, so it keeps the relative
`ProjectPath.SCRATCH_DIR`. `tests/integration/test_generated_docs_are_path_agnostic.py`
is the guard. A `setup_commands` entry is Bash run from the project root, so
relative is correct there too.

### Decision 11: the guard's own false positive was fixed, not exempted

Committing Task 4.4 was denied by `curl_pipe_shell`, because the commit
message described the anti-pattern it was fixing. The body sat in a
quoted-delimiter heredoc, which bash never parses — it was data.

Fixed in `shell_segmentation` (`quoted_heredoc_receivers`) rather than in the
handler, because that module exists precisely to stop two handlers deriving
opposite halves of a shell rule (Plan 00200 Task 3.7). The exemption stops at
the receiver: `bash <<'EOF'` executes the body, so blanking it would have
turned a documentation fix into a bypass of a safety-critical handler.

## Success Criteria

- [x] A `Write` to `/tmp/anything` is denied, with a message naming the
  sanctioned location. Verified live against the restarted daemon.
- [x] `> /tmp/x`, `tee /tmp/x`, a heredoc to `/tmp/x` and `cp`/`mv` targets are
  denied. `mv` verified live; the rest by test.
- [x] A write anywhere inside the repo root is unaffected.
- [x] Reading an out-of-root path is unaffected. Verified live.
- [x] `untracked/scratch/` exists and `git check-ignore` confirms it is ignored.
  Created by the daemon at start, verified live.
- [x] Claude Code's own state directory is writable, and untracked auto-memory
  is still blocked by its own rule. Verified live.
- [x] The guard's Bash coverage is stated exhaustively, naming what it does not
  resolve, so a clean command is not read as evidence of containment.
- [x] No daemon-emitted guidance string recommends `/tmp` to an agent.
- [x] The full QA gate is green and the daemon restarts cleanly.

## Delivery & Milestones

- `040160e5` — plan filed, after triaging the existing residue rather than
  assuming its contents.
- `bfe6e61a` — the guard: both surfaces, 14 enumerated meta-tests, verified
  live.
- `71b0371e` — the affordance: scratch created at daemon start, and the daemon
  stops recommending what it now blocks.
- `1dccc0c4` — the convention gets a canonical home in `DirectoryRoles.md`.
- `383ac603` — skill SOURCES (not the gitignored deployed copies) and the debug
  capture follow the rule too.
- `89ae6417` — the Bash limit declared rather than implied.
- `a4a498a0` — first migration pass: 14 handler modules off `/tmp`, plus four
  handlers that actively recommended it now emit `ProjectPath.SCRATCH_DIR`.
- `3b05019c` — `curl_pipe_shell` fix: a quoted-heredoc commit body is data, not
  a command, so describing the anti-pattern in a commit message must not deny
  the commit that fixes it.
- `a8bc987c` — full corpus migration: 49 strategy modules + 15 handler modules,
  landing on an absolute `scratch_path()` so the acceptance playbook stays
  runnable after `AbsolutePathHandler`.
- `75572df4` — Phase 5: 25/25 QA gate green, daemon restarts clean, generated
  docs regenerated.
