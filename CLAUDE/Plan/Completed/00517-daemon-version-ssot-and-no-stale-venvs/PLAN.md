# Plan 00517: daemon version ssot and no stale venvs

**Status**: Complete
**Created**: 2026-10-13
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner, 2026-10-13: stale venvs misreporting the daemon version are "a total failure of SSoT", venvs "must be
cleaned up", and "we need to not have crap floating around". Venvs with missing or unreadable metadata are to be
investigated by the running agent and removed once confirmed safe.

What main does today:

- **The installed version has two sources.** `daemon_upgrade_detector` (`handlers/user_prompt_submit/daemon_upgrade_detector.py`, `_resolve_installed_daemon_version`) reads the INSTALLED version from the selected
  venv's `.daemon-metadata.json` `daemon_version`, a copy written when the venv was built, and compares it with the
  running `version.__version__`. A venv whose metadata disagrees with the source it serves reports a version that is
  not installed. Release note 037 (#84) made the scan prefer the venv whose `lock_hash` matches, which narrows the
  window but leaves the copy as the source.
- **"Stale" has four definitions.** `prune-venvs --stale` removes venvs whose stamped daemon version differs;
  `prune-venvs --all-except-current` removes every venv whose interpreter fingerprint differs from the current one;
  the upgrade cleanup (release note 043, `paths.py list-stale-venvs`, called through `eager_cleanup_stale_venvs` in
  `scripts/install/venv.sh`) removes a venv only when its `lock_hash` is readable and differs; and daemon start's
  `_stale_venv_advisory` (`cli.py`) counts `_reclaimable_venv_entries` and deletes nothing.
- **The running venv is not protected (ledger 00474 N456).** In this repository the only venv, the one the running
  daemon uses, is `workspace-py311-81c29529` while `list-venvs` reports the current fingerprint as
  `workspace-py311-2a519198`, and `prune-venvs --all-except-current --dry-run` lists it for removal. The Plan 00184
  guard `_resolver_active_venv_realpath` calls `.resolve()` on the venv's `bin/python`, a symlink to the system
  interpreter, so it resolves to `/usr` and never matches the venv.
- **Removal runs only on upgrade**, and keeps a venv with missing or unreadable metadata, or another checkout view's
  slug, logging `Kept venv:`. Nothing removes those later; restart, provision and session start remove nothing.

## Goals

- One source for the installed daemon version: the installed source tree's `version.py`. Venv metadata keeps what
  tells venvs apart (`lock_hash`, `python_path`) and is never read as the version.
- One definition of a stale venv, used by the upgrade cleanup, `prune-venvs`, `disk-usage` and any session-start
  report. Never removes the venv the running daemon uses.
- No unexplained venv stays on disk. A venv the code cannot prove stale (missing or unreadable metadata) is surfaced
  to the running agent with the facts needed to judge it (what process, if any, uses it; its interpreter; its age; its
  slug), and the agent removes it once it has confirmed it is safe.
- The check runs where stale venvs appear: after upgrade, on daemon restart, on `provision`, and as a SessionStart
  advisory, not only on upgrade.

## Non-Goals

- Changing the venv naming scheme (slug and fingerprint), Plan 00099/00124 territory.
- Removing another checkout view's venv (a host and a container sharing one checkout) without the same safety proof:
  it is reported, and the agent confirms it is unused before removing it.
- Plan 00100's residue (Phase 5 upgrade-cycle test, Phase 6 docs). Coordinate with it, do not absorb it.

## Tasks

### Phase 1: Inventory

- [x] ✅ **Task 1.1**: List every reader of a daemon version (the venv metadata `daemon_version`, `version.__version__`,
  the generated-doc header in `utils/deployed_version.py`, shell readers in `scripts/`), and every staleness test
  (`prune-venvs` flags, `list-stale-venvs`, `eager_cleanup_stale_venvs`, `disk-usage`). Record which should read
  `version.py` and which define stale, in a supporting doc `INVENTORY.md`.

### Phase 2: Version SSoT (TDD)

- [x] ✅ **Task 2.1**: `daemon_upgrade_detector` reads the installed version from the installed source tree's
  `version.py` (the clone under `.claude/hooks-daemon/`), not from venv metadata. Test: a venv whose metadata names a
  different version than the source reports nothing; a source upgraded underneath a running daemon still reports.
- [x] ✅ **Task 2.2**: Every other reader from Task 1.1 that takes a version from venv metadata moves to the same
  reader. Metadata's `daemon_version` stays only as a build record, if anything still needs it.

### Phase 3: One staleness rule (TDD)

- [x] ✅ **Task 3.0** (first, and releasable alone): the running-venv guard identifies the live venv by the venv
  directory itself (the running interpreter's `sys.prefix`, and the venv path without resolving `bin/python`'s
  symlink), so no `prune-venvs` mode can remove it. Test over a real venv whose `bin/python` is a symlink to a system
  interpreter and whose fingerprint differs from the current one. Ledger 00474 N456.
- [x] ✅ **Task 3.1**: One function decides stale (current `lock_hash` and this view's slug, never the venv the
  running daemon or the resolver currently selects), shared by the upgrade cleanup and `prune-venvs`; the flags that
  test fingerprint or stamped version are removed or made to call it. `paths.classify_venv` is the function;
  `--all-except-current` is removed with a message, `--stale` calls the rule.
- [x] ✅ **Task 3.2**: A venv with missing or unreadable metadata, or another view's slug, is classed UNPROVEN, not
  kept silently. `list-venvs`/`prune-venvs --dry-run` show each UNPROVEN venv with the evidence: processes whose
  executable lives in it, interpreter and version, last-modified time, slug and the view it belongs to.
  (`/proc` scan reads `exe`, `cwd` and `argv[0]`: a venv's `bin/python` is a symlink, so `exe` alone misses it.)
- [x] ✅ **Task 3.3**: `prune-venvs --unproven <path> --force` removes one named UNPROVEN venv, refusing when a live
  process uses it or it is the resolver's current choice.

### Phase 4: Where it runs

- [x] ✅ **Task 4.1**: Daemon restart and `provision` run the stale cleanup (proven-stale only, never UNPROVEN).
  Coordinate with Plan 00477 Task 2.2 (provision) and Plan 00100 Phase 4's venv lock. Restart (`cmd_restart`),
  provision (`init.sh` start, `bin/hooks-daemon restart`) and plain start all reach `cmd_start`, so the cleanup lives
  in `_reap_stale_runtime_files`; it holds the venv build lock, skips a venv a process uses, and is fail-open.

- [x] ✅ **Task 4.2**: The existing daemon-start `_stale_venv_advisory` is rebuilt on Task 3.1's rule (no second
  advisory), and a SessionStart advisory lists UNPROVEN venvs with the evidence and the exact removal command,
  telling the agent to investigate and remove each once confirmed safe; silent when there are none. (New handler
  `unproven_venv_advisor`, priority 72; its text is `paths.unproven_report_lines`, shared with `list-venvs`.)

- [x] ✅ **Task 4.3**: The same rule for the daemon's per-host runtime files. Socket and pid paths are hostname-keyed
  (`untracked/daemon-<hash>.{sock,pid,sock.start.lock,socket-path}` and `untracked/events-<hash>/`), so every container
  restart leaves the previous host's set behind; on 2026-10-13 this repository held 24 dead sets beside the live one,
  removed by hand after a connect probe refused every dead socket. Daemon start sweeps a set only when its socket
  refuses a connection and its pid is not a live process here (a host sharing the checkout keeps a listening socket,
  so it is never swept), logging each removal.

### Phase 5: Release

- [x] ✅ **Task 5.1**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, and a post-upgrade task telling
  the upgrading agent to clear any UNPROVEN venvs the new advisory lists. (Release note 055; post-upgrade task 01.)
- [x] ✅ **Task 5.2**: This repository's own `untracked/` and every worktree's venvs checked with the new tool. On
  2026-10-14 there were two venvs: the main venv the daemon uses (`81c29529`, marked current) and one worktree venv
  (`2a519198`, created that day). `prune-venvs --stale --dry-run` found nothing to prune and nothing UNPROVEN was
  listed. The header and marker still disagree on which fingerprint is current; that is filed as ledger 00474 N460.

## Success Criteria

- [x] No code path reads the installed daemon version from venv metadata (grep and test). A grep of `src/` and
  `scripts/` for `daemon_version` finds only the metadata model's validator, the metadata writer and the issue-report
  fields; Task 2.1's tests pin the detector.
- [x] One staleness function; `prune-venvs` and the upgrade cleanup both call it; the running venv is never removed.
  The function is `paths.classify_venv`. `scripts/install/venv.sh` reaches it through `paths.py list-stale-venvs`,
  and Task 3.0 guards the running venv.
- [x] An UNPROVEN venv is surfaced at session start with evidence and a removal command, and removed once confirmed
  (`unproven_venv_advisor`; `prune-venvs --unproven <path> --force`).
- [x] After upgrade, restart or provision, `untracked/` holds no proven-stale venv. Task 5.2 on 2026-10-14, after a
  host reboot and daemon restart: `prune-venvs --stale --dry-run` found nothing to prune.
- [x] Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/` (release note and post-upgrade task):
  `release-notes/055-venvs-are-judged-by-one-staleness-rule-and-unproven-ones-are-surfaced.md` and
  `post-upgrade-tasks/01-clear-unproven-venvs.md`.
- [x] Full QA green: full CI run 38491817681 on 42f6de85a passed on Python 3.11, 3.12 and 3.13.

## Delivery & Milestones

- Filed from the owner's direction of 2026-10-13. Related: Plan 00100 (venv SSoT history, Phase 4 lock), Plan 00477
  (provision), release notes 037 and 043.
