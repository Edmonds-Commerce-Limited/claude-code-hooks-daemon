# Plan 00499: write-protected paths, and the ccy.env.local.dist template

**Status**: In Progress
**Created**: 2026-10-06
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #88

## Overview

Owner rulings (2026-10-06):

- `.claude/ccy/ccy.env.local` is written by IaC (or a human) only, never by an agent. Agents and ccy may read it.
  The copy the coordinator had written was removed for that reason: "We need to know that the file is created by
  IAC."
- A generic guard for "agents may read this but never write it" is approved: "a generic handler would make sense".
  It is not urgent.

The daemon has no such guard today:

- `secret_file_guard` blocks reading as well as writing.
- `lock_file_edit_blocker` is hard-coded to package lock files and covers only the `Write`/`Edit` tools.
- Claude Code's own `permissions.deny` with `Edit(...)` misses every Bash write (`>`, `tee`, `cp`, `mv`, `rm`).

GitHub #88 asks the daemon to ship a tracked `ccy.env.local.dist` template beside the supervisor. Its scope is
corrected by the rulings above. The daemon writes the template and never the local file. An advisory about an
older local copy tells the agent to report it to a human, not to edit it.

## Goals

- A per-project list of path globs that agents may read but never create, change, move onto or delete.
- This repository protects `.claude/ccy/ccy.env.local` with it.
- #88 delivered with the corrected scope.

## Non-Goals

- Writing `ccy.env.local` from the daemon or from an agent, in any project.
- Protecting against a human, or against IaC running outside Claude Code.
- Changing what `secret_file_guard` protects.

## Tasks

### Phase 1: The guard

- [x] ✅ **Task 1.1**: A PreToolUse handler `write_protected_paths`, off by default, with option `paths` (globs,
  repository-relative). It denies:

  - `Write`, `Edit` and `NotebookEdit` on a listed path;
  - a Bash command that authors a listed path (redirect, `tee`, heredoc, `sed -i`, `dd of=`), relocates onto it
    (`cp`, `mv`, `install`, `ln`), or deletes or truncates it (`rm`, `truncate`, `: >`).

  Use `scan_bash_write_targets` (`core/utils.py`) with `authored_only=False`, not `get_written_file_paths`: that
  wrapper sets `authored_only=True`, which drops `cp`/`mv`/`install`/`dd`. The scan already covers redirects
  (including `: >`), `tee`, heredoc redirects, `cp`/`mv`/`install` and `dd of=`. `sed -i`, `ln`, `rm` and `truncate`
  are new verbs to add. Fail closed on the scan's `unreadable` and `unresolved` results when the command names a
  listed path. Reading is never denied. Tests first, through the real handler. Done: `write_protected_paths`
  (`handlers/pre_tool_use/write_protected_paths.py`). The scan gained an opt-in `include_mutations` flag
  (default off, so no existing caller's answer changes) reporting `sed -i`/`--in-place`, `ln`, `rm`, `truncate`
  and the source of `mv`; a directory holding a listed file is protected too. An unresolved or unreadable result
  is denied only when it visibly names a listed path. Tests: `tests/unit/core/test_bash_write_mutations.py`,
  `tests/unit/handlers/pre_tool_use/test_write_protected_paths.py`.

- [x] ✅ **Task 1.2**: Guidance (`get_claude_md()`), a rule ID and acceptance tests. The deny message says that the
  file is maintained outside the agent (IaC or a human), and to ask the human for any change. Done: rule
  `R-WRITE-PROTECTED-PATH`, resident guidance, an allow acceptance probe, and the deny probe declared undrivable
  (a live probe would write the real file were the handler not loaded); the deny is covered over temporary files.

- [x] ✅ **Task 1.3**: Enable it in this repository with `paths: [".claude/ccy/ccy.env.local"]`, and add a
  commented example to `.claude/hooks-daemon.yaml.example`. Done: enabled in `.claude/hooks-daemon.yaml`; the
  example, `init_config`, HANDLER_REFERENCE entry, release-note callout 003 and the v3.70.0 config-changes
  manifest are in. Takes effect after a daemon restart.

### Phase 1b: Hardening

Gaps the round 2 review found and the coordinator deferred at review round 2 rather than fix inside Phase 1. Each is also named in the handler's
guidance as a known gap.

- [x] ✅ **Task 1b.1**: Wrappers not on the handler's list (`flock`, `chronic` and the like) hide the verb they
  run. Consider inverting the check to a read-only allowlist: any command not known to only read, naming a listed
  path, is denied. Done: a command that names a listed path and is on neither `READ_ONLY_VERBS` nor the scan-judged
  verbs is denied; wrappers are read through to the command they run (`utils/simple_commands.py`).

- [x] ✅ **Task 1b.2**: Brace expansion (`rm .claude/ccy/ccy.env.{local,bak}`) is not expanded before the path is
  judged. Done: groups are spelled out (joined and per-spelling variants) with the shared expansion caps; past a cap
  the command is judged by whether it visibly names a listed path.

- [x] ✅ **Task 1b.3**: `bash -c '...'` / `sh -c` strings and absolute command paths (`/bin/rm`) are not read as
  commands. Done: `bash -c`, `sh -c`, `eval`, `flock -c` and `su -c` bodies are judged as commands to
  `MAX_SHELL_DEPTH` (3), and an absolute command path is reduced to its verb.

- [x] ✅ **Task 1b.4**: A `cd` carrying a redirect (`cd .claude 2>/dev/null && rm -rf ccy`) is not followed as a
  directory change, and a `for` loop over the path (`for f in <path>; do rm "$f"; done`) is not read. Done: a
  redirect is set aside before a `cd` is recognised, and a `for` loop body is written out once per word (32 at
  most, then a wildcard).

- [x] ✅ **Review round 1**: Done: the quadratic carry of assignments before a `cd` is bounded (32 names) and the
  shared perf sweep now configures this handler with `paths`; past the nesting limit any word naming the file, its
  directory or a wildcard that could reach it is denied; plain wrappers, `export`/`declare`/`local`/`readonly`
  assignments, `xargs`, `read` loops, `find -delete`/`-exec`, a listed file's own directory as a destination and
  readers used to write (`--output`, `-o`) are judged; the read-only allowlist now covers `sort`, `awk`, `xxd`,
  `hexdump`, `column`, `shellcheck` and the like, with input-file options (`--env-file P`) read as reads. Hostile
  respellings are named out of scope in the guidance. Report:
  `subagent-reports/261009-00499-phase1b-review-r1-opus.md`.

### Phase 2: #88, corrected

- [x] ❌ **Task 2.1**: The daemon writes a tracked `ccy.env.local.dist`. CANCELLED: ccy writes it on every launch
  (first seen 2026-10-06, "ccy.env.local.dist version 2"). Its header says commit it, never edit it, that IaC places
  `ccy.env.local`, and how to record the "based on" version. Its first entry is the `HOOKS_DAEMON_HOSTNAME` role
  override with the precedence ladder. The daemon writing a second copy would fight ccy's rewrite. This repository
  tracks ccy's file.

- [x] ❌ **Task 2.2**: A SessionStart advisory for an older "based on" version. CANCELLED: ccy reports that at
  launch ("When this dist's version moves on, ccy says so at launch").

- [x] ✅ **Task 2.3**: Comment on #88 with the corrected scope and link this plan ("Addresses #88"). Done: the
  issue is claimed for this account and carries the correction.

### Phase 3: IaC hand-off

- [x] ✅ **Task 3.1**: Draft the fedora-desktop request for IaC to write this repository's `ccy.env.local` on the
  sdlc runner VM (`HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`, Plan 00479 owner ruling D8). The owner files or hands it
  on. Done: [FEDORA-DESKTOP-REQUEST.md](FEDORA-DESKTOP-REQUEST.md). Its readability finding is resolved: from the
  2026-10-07 restore, the IaC-written file reads normally inside the container and holds the expected line.

## Success Criteria

- [ ] An agent in this repository can read `.claude/ccy/ccy.env.local` but cannot create, edit, overwrite, move onto
  or delete it by any tool route covered by the tests.
- [ ] A project with no `write_protected_paths` config behaves exactly as before.
- [x] `ccy.env.local.dist` is kept current, and nothing in the daemon touches `ccy.env.local`. Met by ccy, which
  rewrites the dist at launch and reports an older "based on" version.

## Delivery & Milestones

- Plan filed.
