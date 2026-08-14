# Plan 00241: v3.53.0 Review Findings — Terminal-ALLOW Shadowing and Verdict-Log Retention

**Status**: Complete
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

The release ABORTED at Step 10 on the blocker below, and resumed once every
finding here was fixed. All of them shipped in v3.53.0.

**Already fixed inside the gate, before this plan existed**: `comment_changelog`
and `comment_size` were terminal while carrying an advisory ALLOW path, so an
ordinary English phrase in a comment ended the PreToolUse chain at priority
31/33 and silently disabled `tdd_enforcement` and every higher-numbered
handler; and `audit_untracked_permissions` iterated `rglob("*")`, which never
yields the root, so a world-writable `untracked/` — the exact artefact
`umask(0)` created — was invisible to `check-permissions`.

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

The narrow warn-mode guard built in Phase 2 is deliberately not the general
invariant. Plan 00242 carries that: the chain already implements the merge
semantics that would make `terminal` unnecessary, and `terminal` overrides
them.

## Tasks

### Phase 1: Remaining terminal-ALLOW instances

- [x] ✅ **Task 1.1**: `ancestry_preserving_merge` — make non-terminal
  - [x] ✅ It never passes `terminal`, so it defaults True, and its `warn`
    mode returns ALLOW at priority 19, shadowing everything above it
  - [x] ✅ Add `terminal=False`; confirm block mode still denies
- [x] ✅ **Task 1.2**: `git_stash` — same shape, same fix, same confirmation
- [x] ✅ **Task 1.3**: Sweep for the pattern "terminal AND a configurable
  warn/advisory mode" and fix whatever it finds — the sweep found exactly
  these two beyond the pair already fixed in the gate

### Phase 2: The guard

- [x] ✅ **Task 2.1**: Add a guard for the shadowing class
  - [x] ✅ A first attempt asserting "no terminal PreToolUse handler may
    return a non-restrictive decision" flagged 23 handlers and was
    discarded: most (`destructive_git`, `sudo_pip`, ...) carry a defensive
    ALLOW in `handle()` that `matches()` makes unreachable, and a guard
    failing on 23 handlers on day one gets disabled within a day
  - [x] ✅ Implemented the precise rule instead, as
    `tests/integration/test_advisory_mode_handlers_are_not_terminal.py`: it
    AST-walks the PreToolUse handler modules, finds those assigning
    `self._mode`, and asserts each passes `terminal=False`. A configurable
    warn/advisory MODE is the property that actually separates a designed
    ALLOW from a defensive one
  - [x] ✅ Paired with `tests/integration/test_stop_chain_terminal_shadowing.py`,
    which pins ordering on the Stop chain; this pins entitlement on PreToolUse

### Phase 3: Verdict log

- [x] ✅ **Task 3.1**: `append_verdicts` never passes `retain_bytes`
  - [x] ✅ `cap_log_file` then retains the full `max_bytes`, so the file lands
    just under the ceiling and the NEXT append breaches it again — a full
    rewrite on every hook event once the log fills
  - [x] ✅ Reported measurement at the 10 MiB default: three consecutive
    appends cost 40.2 / 45.4 / 43.1 ms, against an advertised ~1.8 ms
    dispatch; with `retain_bytes=max_bytes//2` the next call returned in
    0.015 ms without trimming
  - [x] ✅ Defaulted to `max_bytes // 2`, matching both the
    `VerdictLogConfig` docstring ("oldest half is trimmed") and the sibling
    call site in `handlers/stop/auto_continue_stop.py`
  - [x] ✅ VERIFIED the measurement independently before acting on it, and
    pinned it with `TestAtCapSteadyState`
- [x] ✅ **Task 3.2**: The trim is a non-atomic read-modify-replace running
  inside the dispatch ThreadPoolExecutor
  - [x] ✅ Reported: 8 threads x 30 dispatches left 660 lines where the
    single-threaded control left 2035; concurrent threads each replace the
    file with a snapshot predating the other's appends, and race on a shared
    fixed temp name
  - [x] ✅ Serialised the append+cap pair under one module-level
    `threading.Lock`, so the read-modify-replace can no longer interleave
  - [x] ✅ VERIFIED independently and pinned with `TestConcurrentAppends`;
    Task 3.1 is what keeps this path hot
- [x] ✅ **Task 3.3**: Pseudo-event handlers are permanently "never fired"
  - [x] ✅ `_record_verdicts` runs BEFORE the pseudo dispatch, and
    `merge_pseudo_results` merges `HookResult`, which carries no per-handler
    verdict — yet pseudo handlers were counted in the registered roster
  - [x] ✅ Excluded them from the roster as Status renderers already are, so
    the two enumeration surfaces agree. This is the class Plan 00237 closed,
    reappearing in the new report

### Phase 4: Smaller findings

- [x] ✅ **Task 4.1**: `comment_size._region_before` decoded the existing file
  as UTF-8 unguarded; a latin-1/CP1252 source (common in PHP and C# trees,
  both in this handler's registry) raised out of `handle()`. Fixed with
  `errors="replace"` — NOT with a `try/except` returning `None`, which the
  `error_hiding` QA check correctly rejected as swallowing a real failure
- [x] ✅ **Task 4.2**: `init_config` emitted `comment_changelog` and
  `comment_size` TWICE into the same `pre_tool_use:` mapping. PyYAML tolerates
  duplicate keys (last wins, values identical) so runtime was unaffected, but
  every generated config failed a strict loader or `yamllint`. Guarded with a
  `yaml.compose` node-tree check — a loader cannot see this, by definition
- [x] ✅ **Task 4.3**: `pipe_blocker` git whitelist entries anchored on
  `^git\s+`, so `git -C <path> log` piped to `head` was blocked while the bare
  spelling was allowed. Now built from the shared `GIT_INVOCATION` fragment
- [x] ✅ **Task 4.4**: `pipe_blocker` did not recognise `|&`, so that
  spelling bypassed it entirely
- [x] ✅ **Task 4.5**: `pipe_blocker.get_claude_md` stated "Single-quoted text
  substitutes nothing, so it is never treated as a pipe". True only of `$( )`
  inside single quotes — an ordinary single-quoted ARGUMENT containing a pipe
  to `head` is still scanned and blocked. The code was right; the shipped
  sentence was wrong, and now scopes the exemption to SUBSTITUTION only

## Dependencies

- Blocked: the v3.53.0 release, which resumed once Phases 1 and 2 landed
- Related: Plan 00242 generalises Phase 2's narrow guard

## Success Criteria

- [x] No handler is terminal while carrying a configurable advisory mode
- [x] A guard exists that is precise enough not to be disabled
- [x] The verdict log's cost and coverage match its documentation
- [x] Every finding above is fixed, or explicitly closed with evidence

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                       |
| -------------------------------------------------------- | ------ | ----------- | -------------------------------------------------------------------------------- |
| Findings inherited from sub-agents are wrong             | Medium | Medium      | Each task says VERIFY independently; the three already fixed were confirmed live |
| Halving the retained window surprises someone reading it | Low    | Medium      | It is what the docstring already promises; state it in the changelog             |
| A guard too broad gets disabled                          | High   | Medium      | Phase 2 records exactly why the first attempt was discarded                      |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. -->

- Findings raised during the v3.53.0 Step 10 gate; three fixed within that gate
- Phase 1 + Phase 2 + permission-audit root blindness delivered at `53cb6743`
- Phases 3 and 4 delivered at `54757f46`
- Shipped in v3.53.0, tagged `033de9ec`
