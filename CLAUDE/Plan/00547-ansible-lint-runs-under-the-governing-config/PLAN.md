# Plan 00547: ansible lint runs under the governing config

**Status**: In Progress
**Created**: 2026-10-22
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #128

## Overview

The Ansible syntax check (`ansible-playbook --syntax-check`) needs the play's
governing `ansible.cfg` in effect. `module_context.find_module_root` finds it
only by walking up from the play. A play kept outside that config's directory
tree, such as a separate plays tree or a scratch play, resolves no root, and
the two gates then disagree:

- `lint_on_edit` runs the check from the workspace root.
- `staged_lint_gate` runs it with `cwd=None`, which is the daemon's own working
  directory.

Neither has the config, so a valid play that reads `CONFIG_FILE` or depends on
the inventory is denied for a context error that is not its own defect.

Prior art: Plan 00268 added the Ansible strategy and the `ansible.cfg` marker.
Plan 00525 made both gates share `resolve_module_context`. Plan 00464
(Not Started) is about which repository a commit gate judges, not lint roots,
so it is a neighbour and not a duplicate.

## Goals

- A project can declare the governing `ansible.cfg` for plays outside its tree.
  Both gates honour the declaration, through `module_context`, the one place
  where the run context is decided.
- When the check has a config, it runs under it: the working directory is the
  config's directory, and `ANSIBLE_CONFIG` names the config.
- Both gates resolve the same working directory when no marker is found.
- A failed check that ran with no governing config still denies. The reason
  says no `ansible.cfg` was in effect and names the option. Nothing is silently
  allowed.

## Non-Goals

- More than one marker per language, for example `.ansible-lint` (Plan 00268
  DESIGN section 4).
- Guessing a config from sibling directories.
- Which repository a commit gate judges (Plan 00464).

## Tasks

### Phase 1: Build (TDD)

- [x] ✅ **Task 1.1**: Write failing tests that reproduce #128: no root found,
  and the two gates use different working directories.
- [x] ✅ **Task 1.2**: Add the declared governing config, applied in
  `module_context` and read by both gates. Document the option. Delivered:
  `layout.ansible_configs` (play glob -> repo-relative `ansible.cfg`); a
  matching play runs from the config's directory with `ANSIBLE_CONFIG` set; a
  declared file that does not exist is denied as a configuration error.
- [x] ✅ **Task 1.3**: When a failure ran with no governing config, the deny
  reason names the missing context and the option.
- [x] ✅ **Task 1.4**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`018-ansible-lint-runs-under-the-governing-config.md`).

### Phase 2: Ship

- [ ] ⬜ **Task 2.1**: Targeted QA, merge, CI green, close #128.

## Success Criteria

- [ ] The reproduction from #128 (a play outside its config's tree that looks up
  `CONFIG_FILE`) passes both gates once the config is declared (tested).
- [ ] Without a declaration, both gates use the same working directory, and a
  failure's reason names the missing config (tested).
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (the
  pending-release holding area).

## Delivery & Milestones

- Merged to main in `acf6bbcc3` (branch head `51b0fd878`); targeted QA 40/40.
  `ansible-playbook` is not installed on the dev host, so the gates' tests fake
  the tool and assert the working directory and environment it is given.
