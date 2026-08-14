# Plan 00241: v3.53.0 Review Findings — Terminal-ALLOW Shadowing and Verdict-Log Retention

**Status**: Not Started
**Created**: 2026-08-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The v3.53.0 release code-review gate (RELEASING.md Step 10) produced findings
verified against the live daemon. Three were fixed inside that gate; the rest
are captured here, because Plan 00157's rule is that a review finding is
either fixed before the release ships or tracked as a MUST-FIX — never left in
scrollback.

The release was ABORTED at Step 10 on the blocker described below, and is not
tagged.

**Already fixed, not in scope here**: `comment_changelog` and `comment_size`
were terminal while carrying an advisory ALLOW path, so an ordinary English
phrase in a comment ended the PreToolUse chain at priority 31/33 and silently
disabled `tdd_enforcement` and every higher-numbered handler; and
`audit_untracked_permissions` iterated `rglob("*")`, which never yields the
root, so a world-writable `untracked/` — the exact artefact `umask(0)`
created — was invisible to `check-permissions`.

## Goals

- Close the remaining instances of the terminal-ALLOW shadowing class
- Make the verdict log record what it claims, at the cost it claims
- Give the shadowing class a guard precise enough to survive

## Non-Goals

- Re-litigating verdict-log retention semantics beyond the documented intent
- Rewriting the acceptance playbook

## Context & Background

`core/chain.py` breaks on ANY terminal match regardless of the decision, so a
terminal handler returning ALLOW does not merely decline to act — it ends
dispatch and disables every higher-priority-number handler. Nothing reports
it, because a shadowed handler and a handler that never matched are
indistinguishable from outside. `Handler.__init__` defaults `terminal=True`,
so this is the shape a handler gets by saying nothing.

A non-terminal DENY is not a weaker deny: `core/chain.py` keeps the most
restrictive decision seen, so a later advisory ALLOW cannot wash it out (the
Plan 00144 regression). `plan_qa_edit` already ships blocking and
non-terminal.

## Tasks

### Phase 1: Remaining terminal-ALLOW instances

- [ ] ⬜ **Task 1.1**: `ancestry_preserving_merge` — make non-terminal
  - [ ] ⬜ It never passes `terminal`, so it defaults True, and its `warn`
    mode returns ALLOW at priority 19, shadowing everything above it
  - [ ] ⬜ Add `terminal=False`; confirm block mode still denies
- [ ] ⬜ **Task 1.2**: `git_stash` — same shape, same fix, same confirmation
- [ ] ⬜ **Task 1.3**: Sweep for the pattern "terminal AND a configurable
  warn/advisory mode" and fix whatever it finds

### Phase 2: The guard

- [ ] ⬜ **Task 2.1**: Add a guard for the shadowing class
  - [ ] ⬜ A first attempt asserting "no terminal PreToolUse handler may
    return a non-restrictive decision" flagged 23 handlers and was
    discarded: most (`destructive_git`, `sudo_pip`, ...) carry a defensive
    ALLOW in `handle()` that `matches()` makes unreachable, and a guard
    failing on 23 handlers on day one gets disabled within a day
  - [ ] ⬜ Implement the precise rule instead: a handler with a configurable
    warn/advisory MODE must be non-terminal. That is the property which
    actually separates a designed ALLOW from a defensive one
  - [ ] ⬜ Pair it with `tests/integration/test_stop_chain_terminal_shadowing.py`,
    which pins ordering on the Stop chain; this pins entitlement on PreToolUse

### Phase 3: Verdict log

- [ ] ⬜ **Task 3.1**: `append_verdicts` never passes `retain_bytes`
  - [ ] ⬜ `cap_log_file` then retains the full `max_bytes`, so the file lands
    just under the ceiling and the NEXT append breaches it again — a full
    rewrite on every hook event once the log fills
  - [ ] ⬜ Reported measurement at the 10 MiB default: three consecutive
    appends cost 40.2 / 45.4 / 43.1 ms, against an advertised ~1.8 ms
    dispatch; with `retain_bytes=max_bytes//2` the next call returned in
    0.015 ms without trimming
  - [ ] ⬜ Default it to `max_bytes // 2`, matching both the
    `VerdictLogConfig` docstring ("oldest half is trimmed") and the sibling
    call site in `handlers/stop/auto_continue_stop.py`
  - [ ] ⬜ VERIFY the measurement independently before acting on it
- [ ] ⬜ **Task 3.2**: The trim is a non-atomic read-modify-replace running
  inside the dispatch ThreadPoolExecutor
  - [ ] ⬜ Reported: 8 threads x 30 dispatches left 660 lines where the
    single-threaded control left 2035; concurrent threads each replace the
    file with a snapshot predating the other's appends, and race on a shared
    fixed temp name
  - [ ] ⬜ Serialise the append+cap pair, or give `cap_log_file` a unique temp
    name plus a lock across read to replace
  - [ ] ⬜ VERIFY independently; note Task 3.1 is what keeps this path hot
- [ ] ⬜ **Task 3.3**: Pseudo-event handlers are permanently "never fired"
  - [ ] ⬜ `_record_verdicts` runs BEFORE the pseudo dispatch, and
    `merge_pseudo_results` merges `HookResult`, which carries no per-handler
    verdict — yet pseudo handlers are counted in the registered roster
  - [ ] ⬜ Either record their verdicts, or exclude them from the roster as
    Status renderers already are. This is the enumeration-surfaces-disagree
    class Plan 00237 closed, reappearing in the new report

### Phase 4: Smaller findings

- [ ] ⬜ **Task 4.1**: `comment_size._region_before` decodes the existing file
  as UTF-8 unguarded; a latin-1/CP1252 source (common in PHP and C# trees,
  both in this handler's registry) raises out of `handle()`. Fail-open turns
  that into user-visible exception text; `strict_mode` turns it into a hard
  deny of a legitimate write
- [ ] ⬜ **Task 4.2**: `init_config` emits `comment_changelog` and
  `comment_size` TWICE into the same `pre_tool_use:` mapping. PyYAML tolerates
  duplicate keys (last wins, values identical) so runtime is unaffected, but
  every generated config fails a strict loader or `yamllint`
- [ ] ⬜ **Task 4.3**: `pipe_blocker` git whitelist entries anchor on
  `^git\s+`, so `git -C <path> log` piped to `head` is blocked while the bare
  spelling is allowed. Build them from the shared `GIT_INVOCATION` fragment
- [ ] ⬜ **Task 4.4**: `pipe_blocker` does not recognise `|&`, so that
  spelling bypasses it entirely
- [ ] ⬜ **Task 4.5**: `pipe_blocker.get_claude_md` states "Single-quoted text
  substitutes nothing, so it is never treated as a pipe". True only of `$( )`
  inside single quotes — an ordinary single-quoted ARGUMENT containing a pipe
  to `head` is still scanned and blocked. The code is right; the shipped
  sentence is wrong

## Dependencies

- Blocks: the v3.53.0 release (aborted at Step 10 pending Phases 1 and 2)

## Success Criteria

- [ ] No handler is terminal while carrying a configurable advisory mode
- [ ] A guard exists that is precise enough not to be disabled
- [ ] The verdict log's cost and coverage match its documentation
- [ ] Every finding above is fixed, or explicitly closed with evidence

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                       |
| -------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------- |
| Findings inherited from sub-agents are wrong             | Medium | Medium      | Each task says VERIFY independently; the three already fixed were confirmed live |
| Halving the retained window surprises someone reading it | Low    | Medium      | It is what the docstring already promises; state it in the changelog             |
| A guard too broad gets disabled                          | High   | Medium      | Phase 2 records exactly why the first attempt was discarded                      |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. -->

- Findings raised during the v3.53.0 Step 10 gate; three fixed within that gate
