# Plan 00595: secret guard search string option value bold colon

**Status**: In Progress
**Created**: 2026-11-10
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #200

## Overview

`secret_file_guard` (R-SECRET-BASH-MENTION) denies three Bash shapes that read no
file, because it judges text that is not a path as a protected path or a path glob
(GitHub #200):

- **(a) A git search string.** `git log --oneline -1 -S org.freedesktop.secrets | cat`
  is denied on token `org.freedesktop.secrets` against `*.secret*`. `_opens_files`
  treats every git subcommand except `config` as file-opening, so the value of a
  pickaxe or grep option (`-S`, `-G`, `--grep`, `--author`, …) counts as an opened file.
- **(b) An option value.** `grep -rl zz <dir> --include=* | wc -l` is denied on token
  `*`. The `*` is the value of `--include`, a basename filter under `<dir>`, yet it is
  judged as a bare wildcard read from the cwd.
- **(c) A colon split.** In a Python heredoc, `print("**Option 2:** build" in s)` is
  denied on token `2:**`. `_colon_path_parts` (meant for git object and `host:path`
  syntax) splits it at the colon and the leftover `**` is judged as a glob. This recurs
  whenever an agent edits plan markdown through a Python heredoc.

Each is a misreading, not a policy question: none of these texts names, opens or
globs a file. The fix narrows the READING, as #142, #143 and #145 did; a protected
path that is genuinely named or opened still denies.

## Goals

- The three shapes in #200 are allowed, each pinned by a test.
- Every existing deny in the secret guard suites still denies.

## Non-Goals

- Changing which paths are protected, or the trusted-consumer allowlist.

## Tasks

### Phase 1: Fix (TDD)

- [ ] ⬜ **Task 1.1**: (a) the value of a git search option (`-S`, `-G`, `--grep`,
  `--author`, `--committer`, and the attached forms) is a search string, not a file
- [ ] ⬜ **Task 1.2**: (b) the value of a grep/rg filename filter (`--include`,
  `--exclude`, `--exclude-dir`, `-g`/`--glob`) is a basename filter scoped to the
  searched path, not a read of the cwd; a filter that can match a protected file
  under a searched directory still denies
- [ ] ⬜ **Task 1.3**: (c) a colon split in `_colon_path_parts` yields no `**`-only (or
  wildcard-only) part as a path; a real `host:path` or `rev:path` naming a protected
  file still denies
- [ ] ⬜ **Task 1.4**: release note

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: independent adversarial review, merge, main CI green, close #200

## Success Criteria

- [ ] The three reproductions in #200 are allowed; the controls are unchanged
- [ ] No existing secret guard deny test changes verdict
- [ ] Release-bound consequences in the holding area: a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`

## Delivery & Milestones

- <!-- delivery commit hash -->
