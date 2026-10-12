# Plan 00515: per host handler overrides

**Status**: Not Started
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #93

## Overview

Issue #93 asks for a project to vary any handler's `enabled` flag, priority and options by host or role from one config file. The use case is an operator on a laptop and an unattended worker on a server. The daemon already resolves an effective hostname (`HOOKS_DAEMON_HOSTNAME`, then `CCY_HOST_HOSTNAME`, then the system hostname; `utils/host_identity.py`). Three selectors already match against it: `persistent_crons` job `hosts`, the top-level `hosts:` block (usage ceiling) and `autonomy.hosts`. No handler setting can be selected that way. Reproduced on main at d2b7d822f: a `hosts` key on a handler entry fails `config-validate` with `extra_forbidden`.

The owner has already ruled the shape of host config in Plan 00479: hosts are the TOP-LEVEL key, entries keyed by label, each with an optional `fnmatch` `pattern`, and each holding its own settings. This plan would extend that block rather than add a second host schema. The coordinator's candidate design is a per-host `handlers:` overlay with the same shape as the top-level `handlers:` section. It is deep-merged over the base when the host matches, applies to every handler with no per-handler code, and leaves the base unchanged when nothing matches:

```yaml
hosts:
  sdlc-worker:
    pattern: "cchd-sdlc-*"
    handlers:
      stop:
        some_handler:
          enabled: false
      pre_tool_use:
        some_other_handler:
          options:
            some_option: value
```

## Owner Decisions Needed

This is a feature request, and it lets one host switch a guard off, so the coordinator has not ruled.

1. **Build it at all?**
2. **Guards.** May an overlay disable or weaken a blocking guard, for example `destructive_git` or `secret_file_guard`, or only enable, tighten and tune? Under the "careless, not hostile" threat model an overlay is the owner's own config, but a stray glob could silently disarm a guard on every worker.
3. **Shape.** Should this be the per-host `handlers:` overlay inside 00479's `hosts:` block, as sketched above, or some other form?
4. **Several matching hosts.** Several entries can match one hostname. Plan 00479 settled "lowest ceiling wins" for the usage ceiling, which does not generalise. Should overlays merge in file order, or should more than one match be an error?
5. **Merge semantics for options.** Should a key replace or deep-merge, especially for lists such as `exclude_paths` and `public_patterns`?
6. **Visibility.** Should `hooks-daemon check` (or the status line) state which host overlays are active, so a role's effective config is not invisible?

## Goals

- One config file gives different handler settings per host or role, with no per-handler code.
- The host matching rules are exactly those of the existing selectors, reusing `utils/host_identity.py` and `cron_hosts.hostname_matches`.
- `config-validate` reports an overlay naming an unknown handler or option, and a host entry that selects nothing, as it does for cron host lists.

## Non-Goals

- Folding `persistent_crons` host lists into the `hosts:` block. That is Plan 00479's open follow-on, for the next major.
- Per-session (runtime) modes. That is Plan 00501.

## Tasks

### Phase 0: Owner decisions

- [ ] ⬜ **Task 0.1**: The owner answers the questions under Owner Decisions Needed.

### Phase 1: Implement per the decisions

- [ ] ⬜ **Task 1.1**: Write tests red first for: an overlay applied on a matching host, base values on a non-matching host, the multiple-match rule, and the validation errors.
- [ ] ⬜ **Task 1.2**: Add the config model and overlay merge in the config loader, before handler registration.
- [ ] ⬜ **Task 1.3**: Add the `config-validate` checks and the visibility surface per question 6.
- [ ] ⬜ **Task 1.4**: Write the docs: the configuration guide and the example config.

## Success Criteria

- [ ] The owner's decisions are recorded in this plan's JOURNAL/.
- [ ] If built: #93's reproduction validates, and the overlay changes the effective handler set only on the matching host.
- [ ] Release-bound consequences are in the UNRELEASED holding area (a release note), or this plan records that it has none because the owner declined it.

## Delivery & Milestones

- Filed from GitHub #93 by the coordinator; awaiting owner decisions.
