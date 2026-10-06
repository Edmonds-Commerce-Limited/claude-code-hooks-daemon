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

- [ ] ⬜ **Task 1.1**: A PreToolUse handler `write_protected_paths`, off by default, with option `paths` (globs,
  repository-relative). It denies:

  - `Write`, `Edit` and `NotebookEdit` on a listed path;
  - a Bash command that authors a listed path (redirect, `tee`, heredoc, `sed -i`, `dd of=`), relocates onto it
    (`cp`, `mv`, `install`, `ln`), or deletes or truncates it (`rm`, `truncate`, `: >`).

  Use `scan_bash_write_targets` (`core/utils.py`) with `authored_only=False`, not `get_written_file_paths`: that
  wrapper sets `authored_only=True`, which drops `cp`/`mv`/`install`/`dd`. The scan already covers redirects
  (including `: >`), `tee`, heredoc redirects, `cp`/`mv`/`install` and `dd of=`. `sed -i`, `ln`, `rm` and `truncate`
  are new verbs to add. Fail closed on the scan's `unreadable` and `unresolved` results when the command names a
  listed path. Reading is never denied. Tests first, through the real handler.

- [ ] ⬜ **Task 1.2**: Guidance (`get_claude_md()`), a rule ID and acceptance tests. The deny message says that the
  file is maintained outside the agent (IaC or a human), and to ask the human for any change.

- [ ] ⬜ **Task 1.3**: Enable it in this repository with `paths: [".claude/ccy/ccy.env.local"]`, and add a
  commented example to `.claude/hooks-daemon.yaml.example`.

### Phase 2: #88, corrected

- [ ] ⬜ **Task 2.1**: Nothing writes `ccy.env.local.dist` today: ccy 3.81.0 only adds its exception to the generated
  `.claude/ccy/.gitignore`, and the fedora-desktop clone documents the file but writes none. Install and upgrade
  write a tracked `.claude/ccy/ccy.env.local.dist` beside
  `claude-supervise.py`. Its first line is a version marker naming the daemon version that wrote it. Its first entry
  is the role override `HOOKS_DAEMON_HOSTNAME`, commented out, documented with:

  - the precedence: `HOOKS_DAEMON_HOSTNAME`, then `CCY_HOST_HOSTNAME`, then the system hostname;
  - how `persistent_crons` `hosts:`, the top-level `hosts:` block and `autonomy.hosts` match it.

  Then `HOOKS_DAEMON_HOST_HOSTNAME` (`utils/host_identity.py`), documented as the separate display-name ladder it
  is, not a role override. No secrets. The header says the real
  `ccy.env.local` is written by IaC or a human, never by an agent, and that its first line should record the dist
  version it is based on.

- [ ] ⬜ **Task 2.2**: A SessionStart advisory. It fires when a real `ccy.env.local` names an older dist version on
  its "based on" line, and tells the agent to report the new entries to a human. It never edits the file.

- [x] ✅ **Task 2.3**: Comment on #88 with the corrected scope and link this plan ("Addresses #88"). Done: the
  issue is claimed for this account and carries the correction.

### Phase 3: IaC hand-off

- [ ] ⬜ **Task 3.1**: Draft the fedora-desktop request for IaC to write this repository's `ccy.env.local` on the
  sdlc runner VM (`HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`, Plan 00479 owner ruling D8). The owner files or
  hands it on.

## Success Criteria

- [ ] An agent in this repository can read `.claude/ccy/ccy.env.local` but cannot create, edit, overwrite, move onto
  or delete it by any tool route covered by the tests.
- [ ] A project with no `write_protected_paths` config behaves exactly as before.
- [ ] Install and upgrade refresh `ccy.env.local.dist`, and never touch `ccy.env.local`.
- [ ] An older local copy produces one SessionStart advisory that tells the agent to ask a human.

## Delivery & Milestones

- Plan filed.
