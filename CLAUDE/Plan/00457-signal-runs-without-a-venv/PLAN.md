# Plan 00457: signal runs without a venv

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**GitHub Issue**: #55
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration (worktree, TDD). Starts once
Plan 00456 merges, because both plans change the same part of
`bin/hooks-daemon`.

## Overview

The operator-signal channel (Plan 00417) carries a warning from the host
to idle sessions, for example "the machine reboots in N minutes". Its
caller runs on the host. But `bin/hooks-daemon` resolves a venv before it
reads the subcommand. For a project whose sessions run in a container, the
venv was built inside that container: its slug does not match the host
path, and its interpreter cannot run on the host. So `signal` is refused on
the host for exactly the deployment the channel exists for. An external
session manager then cannot warn any session on that machine.

The writer, `utils/operator_signal.py`, imports only the standard library,
and so does its helper `utils/temp_names.py`. The command that calls it,
`cmd_signal` in `daemon/cli.py`, is different: it first calls
`ProjectContext.initialize` to find the untracked directory, and both
modules import the full package. **So a venv-free `signal` needs its own
small entry point that uses only the standard library.** It must work out
the untracked directory exactly as `ProjectContext.daemon_untracked_dir()`
does in each install mode, then call the existing writer.

Plan 00456 adds a way for the wrapper to handle a subcommand before it
resolves a venv, starting with `repair`, and is building it so other
commands can be added. `signal` becomes the second command it handles.

## Goals

- From a host where no venv resolves for the project,
  `bin/hooks-daemon signal <kind> [--minutes N] --all-sessions --project-root <root>`
  writes one signal per live session, into the directory the supervisor
  watches.
- The validation is unchanged: the closed `kind` set, the bare positive
  integer, refusal of a malformed request, and the supervisor re-validating
  what lands on disk.
- There is one definition of each rule. The venv-free entry point reuses
  the writer's own constants and functions and does not re-implement
  them.

## Non-Goals

- Making any other command work without a venv.
- Changing the signal format or the supervisor's reading side.

## Tasks

### Phase 1: TDD in a worktree

- [x] ✅ **Task 1.1**: Establish how `ProjectContext.daemon_untracked_dir()`
  resolves in client and self-install mode, including any slug or
  environment override. Check whether the sidecar directory the container
  supervisor watches is the same directory the host sees through the
  shared mount, with no path-keyed name in between. Record the evidence in
  the journal.
- [x] ✅ **Task 1.2**: A standard-library-only entry point for `signal`,
  runnable with the system `python3`, that parses the same arguments as
  `cmd_signal` and calls the existing writer, with parity tests against
  `cmd_signal`. Add a test that importing it pulls in no third-party
  module.
- [ ] ⬜ **Task 1.3**: Handle `signal` in `bin/hooks-daemon` before venv
  resolution, using Plan 00456's mechanism. When a venv does resolve, the
  normal path stays as it is. State the minimum `python3` version the
  entry point needs and check for it.
- [ ] ⬜ **Task 1.4**: Docs for the operator-signal channel and a release
  note. Full QA green.

### Phase 2: Deliver

- [ ] ⬜ **Task 2.1**: Merge `--no-ff`, verify ancestry and CI, and restart
  the daemon.
- [ ] ⬜ **Task 2.2**: Comment on #55 and close it.

## Success Criteria

- [ ] Integration test: a project whose only venv has a non-matching slug.
  `bin/hooks-daemon signal reboot-warning --minutes 3 --all-sessions` writes
  one valid signal per session sidecar and exits 0, without resolving a
  venv.
- [ ] Malformed requests are still refused, as they are today.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00457-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Not yet delivered.
