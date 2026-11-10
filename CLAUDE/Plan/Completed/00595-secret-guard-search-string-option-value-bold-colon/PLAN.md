# Plan 00595: secret guard search string option value bold colon

**Status**: Complete (2026-11-10)
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

- [x] ✅ **Task 1.1**: (a) the value of a git search option (`-S`, `-G`, `--grep`,
  `--author`, `--committer`, and the attached forms) is a search string, not a file
- [x] ✅ **Task 1.2**: (b) the value of a grep/rg filename filter (`--include`,
  `--exclude`, `--exclude-dir`, `-g`/`--glob`) is a basename filter scoped to the
  searched path, not a read of the cwd; a filter that can match a protected file
  under a searched directory still denies. As shipped, it is relaxed only when it is
  written attached or as one whole quoted literal, every searched root (and a
  symlinked cwd) resolves inside the project, and no link-following flag is given.
- [x] ✅ **Task 1.3**: (c) a colon split in `_colon_path_parts` yields no `**`-only (or
  wildcard-only) part as a path; a real `host:path` or `rev:path` naming a protected
  file still denies
- [x] ✅ **Task 1.4**: release note 045

### Phase 2: Delivery

- [x] ✅ **Task 2.1**: independent adversarial review, merge, main CI green, close #200.
  Four review rounds closed seven ways the first version printed a protected file.
  The causes were roots outside the project, symlink roots, link-following flags,
  unquoted separate globs, empty-quote prefixes (`''*`), a symlinked cwd, and
  `rg --follow … -g '*'` (already allowed on main). The final round approved. Merged
  at `eae5878e9`; main CI run 42912436475 green; #200 closed.

## Success Criteria

- [x] The three reproductions in #200 are allowed; the controls are unchanged
- [x] No existing secret guard deny test changes verdict (1969 secret-guard tests pass)
- [x] Release-bound consequences in the holding area: release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/045-secret-guard-search-string-option-value-and-bold-colon.md`

## Delivery & Milestones

- Merged at `eae5878e9`. Fix commits: `b9a890c31`, `3c82c5377`, `2bc59046c`, `329ff869e`
  and `5d1aa22a1`. Main CI run 42912436475 green; GitHub #200 closed.
