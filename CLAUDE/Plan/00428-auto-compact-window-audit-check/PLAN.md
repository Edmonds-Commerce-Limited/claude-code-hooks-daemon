# Plan 00428: auto compact window audit check

**Status**: Not Started
**Created**: 2026-09-17
**GitHub Issue**: #46
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #46 asks for a seventh check in `optimal_config_checker`, auditing
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` alongside the six Claude Code environment
settings that handler already covers: warn when unset, and warn when the value
exceeds a per-project ceiling defaulting to 600000.

**The reported gap is real.** Verified at triage rather than taken on trust:
`_run_checks()` runs exactly six checks and the handler is 423 lines, as the
issue states; `explain-handler optimal_config_checker` declares no rules and no
options, so no configuration can produce this check; and
`git log -S "AUTO_COMPACT_WINDOW"` across all refs returns nothing, so this was
never built and never reverted. The string appears nowhere in the tree.

**This plan is a QUESTION for the owner, not an implementation brief.** It is a
feature request, the default ceiling is a product-intent call, and — the reason
the issue-sdlc loop stopped rather than building it — the specification rests on
a foundation this repository cannot currently verify.

## The reason this is not simply actionable

### The issue retracts its own specification, and the replacement is inferred

The body asked for a normaliser over three spellings (`600k`, `600000`, `600`)
and for `auto` to be treated as a warn-worthy value. The reporter's own comment
withdraws that: the environment variable takes plain digits only, `auto` belongs
to the separate `autoCompactWindow` SETTING and its slash command, and the
resolved value is floored at 100,000 and capped at 1,000,000.

Retracting a wrong spec before anyone builds it is exactly right, and the
correction is almost certainly closer to the truth than the body was. The
difficulty is its PROVENANCE: it is derived by reading a compiled CLI bundle.

### What triage could and could not confirm

The shipped bundle for the cited version is present on the dogfood machine
(`@anthropic-ai/claude-code` 2.1.274, a single ~220 MB compiled `claude.exe`),
so the claim was tested rather than accepted.

**Corroborated** — the variable exists in that build, a distinct
`autoCompactWindow` setting exists, and the variable takes precedence over it
("`CLAUDE_CODE_AUTO_COMPACT_WINDOW` is set and takes precedence. Unset it to
change this setting."). A resolver vocabulary is visible in the strings —
`window_source_auto`, `window_above_boundary`, `resolve_failed`, cap
enforcement, and per-model defaults — which matches a real precedence chain
rather than a single read of `os.environ`.

**NOT confirmed** — the digits-only parse, the 100,000 floor, or the 1,000,000
cap. Those are parser BEHAVIOUR, and strings extracted from a compiled binary
cannot establish behaviour. A `Couldn't parse ... Expected 'auto' or 1...`
string is present, which is consistent with the correction's claim that `auto`
belongs to the setting rather than the variable — and equally consistent with
the variable accepting it too. Neither reading can be settled by grep.

### Why that matters more here than it usually would

A check that warns is advice the daemon gives every install at every session
start. If its thresholds encode a parser we inferred and that parser differs —
now, or after any Claude Code release — the handler does not fall silent. It
confidently advises a ceiling that is not the ceiling, and nothing in this
repository would notice, because the assertion is about someone else's binary.

That is the failure shape this project keeps paying for: a guard right about the
state it judges and wrong about the thing it judges against. The floor claim
makes it concrete — the reporter states they shipped `600k`, had it silently
become 100,000, and ran at a sixth of their intended ceiling without noticing. A
check built on an inferred parse could reproduce that error rather than catch
it.

## The decisions this plan is waiting on

### 1. Should the daemon audit a variable whose semantics it cannot verify?

Every existing check in this handler tests a value the daemon itself consumes,
or a boolean whose meaning is not in question. This would be the first to assert
a NUMERIC THRESHOLD against another product's parser. That is a new category for
the handler, not a seventh instance of an existing one, and it is the owner's
call whether the handler takes it on.

If yes, the honest form may be narrower than the ask: report the variable's
value and whether it is set, WITHOUT asserting a ceiling — which delivers most
of the issue's value (three materially different configurations stop being
indistinguishable) while claiming nothing the daemon cannot stand behind.

### 2. What is the default ceiling, and does unset warn?

600000 is the reporter's project preference. A default ceiling ships to every
install, and a warning that most installs cannot act on becomes scenery. Whether
UNSET should warn is the sharper half: unset is the default state of almost
every Claude Code install, so warning on it warns nearly everyone by default.

### 3. Is there a verifiable source for the grammar?

If Claude Code documents this variable publicly, the vendored remote-docs tree
(`hooks-daemon remote-docs add <url>`) is the route to a citable source, and
decision 1 largely dissolves. Worth one search before treating the semantics as
unknowable — this plan asserts only that TRIAGE could not verify them from the
compiled bundle, not that no source exists.

## Goals

- Record the owner's answer to each decision above.
- If the answer is "build it": implement against a source that can be cited,
  and pin the ceiling and the unset behaviour to that answer rather than to the
  issue's suggested defaults.

## Non-Goals

- Implementing the check before decision 1 is answered.
- Re-deriving the variable's grammar by reading the compiled CLI further. That
  is what triage already did, and it reached its limit.
- Anything touching the `autoCompactWindow` SETTING, which the issue's own
  correction establishes is a different parser with different rules.

## Tasks

### Phase 1: Owner decisions

- [ ] ⬜ **Task 1.1**: Rule on whether the handler audits a variable whose
  semantics this repository cannot verify, and if so whether it asserts a
  ceiling or only reports the value.
- [ ] ⬜ **Task 1.2**: Rule on the default ceiling and on whether unset warns.
- [ ] ⬜ **Task 1.3**: Establish whether a citable public source for the
  variable's grammar exists.

### Phase 2: Build (only if Phase 1 says build)

- [ ] ⬜ **Task 2.1**: `_check_auto_compact_window` modelled on
  `_check_max_output_tokens`, appended to `_run_checks()`, RED test first, with
  the ceiling and unset behaviour taken from Phase 1 rather than the issue.

## Success Criteria

- [ ] Each decision above is recorded here with its reasoning.
- [ ] #46 carries a comment pointing at the ruling, so it is not re-triaged
  from scratch by a later tick.

## Delivery & Milestones

- Filed by the issue-sdlc loop from issue #46; triaged needs-human, no code
  written.
