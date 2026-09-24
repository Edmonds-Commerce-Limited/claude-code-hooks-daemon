# Plan 00455: self install exposes the conventional cli path

**Status**: Complete
**Created**: 2026-09-24
**Owner**: dev
**GitHub Issue**: #54
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD)

## Overview

Every hooks-daemon project should expose the daemon CLI at the same public
path, `.claude/hooks-daemon/bin/hooks-daemon`. External session managers
(for example, the reboot warning) look for it there, and refuse to signal
anyone if any live project lacks it. This repository's own checkout, which
runs the daemon in self-install mode, has the CLI at `bin/hooks-daemon`
only, so it is the one project that fails. **Owner decision: fix it here, so
no external tool needs a special case for this repo.**

**Why the link is generated, not tracked.** The issue proposed a tracked
relative symlink. Clients install the daemon by cloning this repo into
`<client>/.claude/hooks-daemon/`, so a tracked link would land in every
client at `.claude/hooks-daemon/.claude/hooks-daemon/`. `init.sh:445` treats
that exact directory as a nested install, errors and exits on every hook,
with no exemption. A client's `.claude/init.sh` is a copy refreshed only at
the end of an upgrade (`scripts/install/hooks_deploy.sh`), so a manual pull,
a half-finished upgrade, or the upgrade's own window would break that
client's hooks. A link the self-install daemon creates for itself, under the
already-gitignored `.claude/hooks-daemon/`, never reaches a client clone.

**The directory's existence is an install-mode signal in several places,
and the link breaks that assumption.** `scripts/install/mode_guard.sh`
treats the repo as self-install only while `.claude/hooks-daemon/` does NOT
exist. `ensure_normal_mode_only` is what stops `install_version.sh` and
`upgrade_version.sh` running inside the daemon repo. Checked on a minimal
layout, `get_install_mode` flips from `self-install` to `normal` once the
link's directory exists. Every such check must key on a REAL daemon clone
instead.

## Goals

- A running self-install checkout, main or worktree, has
  `.claude/hooks-daemon/bin/hooks-daemon` resolving to its own `bin/hooks-daemon`,
  and calling it from any working directory manages that checkout's daemon.
- The link is created idempotently by the daemon itself, is gitignored, and
  never overwrites a real file or a real client install.
- Every check that means "a daemon clone is installed here" tests for a real
  clone, not merely for the directory. The install/upgrade self-install guard
  keeps firing in this repo with the link present.

## Non-Goals

- **Tracking the link in git.** It would reach every client clone. See
  Overview.
- **Any change for client installs.** A client's `.claude/hooks-daemon/` is
  the real clone, and the path is already correct there.
- **Changing external session managers.** The point is that they need no
  special case.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: RED, then GREEN: `mode_guard.sh`'s `detect_self_install_mode`
  reports self-install with a link-only `.claude/hooks-daemon/bin/` present,
  and still reports normal for a real client clone.
- [x] ✅ **Task 1.2**: Audit every place that uses the existence of
  `.claude/hooks-daemon/` as a signal and re-key each one on a real clone,
  with a test per behaviour change. Known sites: `init.sh:445` (nested
  install, no exemption, unlike `validation.py:273-281`);
  `daemon/validation.py:210` (`validate_installation_target` walks parents
  and would refuse installs under this repo); `daemon/cli.py:333`;
  `scripts/install/project_detection.sh`. Report any further site found, and
  any site judged safe with the reason.
- [x] ✅ **Task 1.3**: The self-install daemon creates the link at startup:
  relative target, idempotent, never replacing a non-symlink, only in
  self-install mode. Tested, including from a worktree.
- [x] ✅ **Task 1.4**: Docs (`SELF_INSTALL.md` at least) describe the
  conventional path, and say why the link is generated rather than tracked.
  Release note. Full QA green.

### Phase 2: Deliver

- [x] ✅ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon to confirm the link appears.
- [x] ✅ **Task 2.2**: Comment on #54 and close it.

## Success Criteria

- [x] `.claude/hooks-daemon/bin/hooks-daemon status` works from outside the
  checkout, in the main checkout and in a worktree. Verified in this
  worktree: called from `/tmp`, reported the same PID and socket as
  `./bin/hooks-daemon status`.
- [x] With the link present, the install/upgrade guard still refuses to run
  in the daemon repo. Covered by
  `tests/integration/test_mode_guard_self_install_detection.py`.
- [x] No check that means "a clone is installed" is satisfied by the link alone.
  Audited and tested per Task 1.2.
- [x] Nothing is tracked under `.claude/hooks-daemon/`. Still covered by the
  existing `/hooks-daemon/` `.claude/.gitignore` entry; unchanged by this plan.
- [x] Full QA passes and CI is green in this worktree
  (`./scripts/qa/llm_qa.py all`: 35/35 PASSED, twice). CI on main is green
  at `002293ac` (run 35977500551), which contains the merge.
- [x] Every release-bound consequence is in the pending-release holding area:
  `UNRELEASED/release-notes/03-self-install-checkouts-now-expose-the-conventional-cli-path.md`

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00455-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Merged to main at `e6a11e19` (`--no-ff`, from `aba664a0`). The daemon was
  restarted after deleting the link, and it recreated the link.
