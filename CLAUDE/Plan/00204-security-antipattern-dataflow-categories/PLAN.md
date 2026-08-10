# Plan 00204: Security Antipattern — the Three Data-Flow Categories

**Status**: Not Started
**Created**: 2026-08-10
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`security_antipattern` shipped guidance claiming it blocked **SQL injection**,
**weak cryptography** and **path traversal**. It does not, and never did — none
of the eleven language strategies contains a pattern for any of the three. The
v3.52.0 release corrected the guidance so it states what actually exists and
names what it cannot see. This plan is the other half: decide whether to
implement the three, and if so, how.

They were absent for a structural reason rather than an oversight. Every
pattern the handler owns matches a **construct** — `eval`, `shell_exec`,
`pickle.load`, `innerHTML`, a credential literal. The three missing categories
are properties of how a **value flows**: a concatenated SQL string is only a
vulnerability if the concatenated part is attacker-controlled; `md5()` is only
weak when it is hashing a password; a path join is only traversal when the
component came from outside. A regex sees the shape, never the provenance.

That makes naive patterns for these categories dangerous in a specific way:
they fire on the overwhelmingly common safe case. `"SELECT * FROM t WHERE id = " + str(row_id)` in a migration script is not an injection, and `md5(path, usedforsecurity=False)` is explicitly sanctioned by this project's own
security standards. A rule that cries wolf gets disabled — and disabling it
removes the categories that DO work.

## Goals

- Decide, per category, whether a construct-level regex can carry useful signal
  at a false-positive rate that will not get the handler switched off
- Implement the ones that can, with the same strategy/registry pattern
- Keep the guidance and the implementation in lockstep automatically

## Non-Goals

- Building taint analysis or a dataflow engine — out of proportion to a
  PreToolUse hook that must answer in milliseconds
- Reinstating the three guidance claims without implementation behind them
- Reproducing what a real SAST tool does; this handler is a fast tripwire

## Context & Background

Found during the v3.52.0 release acceptance gate: a string-concatenated SQL
query written at the live daemon was allowed. `eval()` at the same path was
blocked, proving the handler was live and the path not excluded — so the miss
was a genuinely absent pattern.

### What exists today

| Category               | Implemented? | Evidence                                                    |
| ---------------------- | ------------ | ----------------------------------------------------------- |
| Code injection         | Yes          | `eval`, `exec`, `new Function`, `__import__`, `yaml.load`   |
| Command injection      | Yes          | `os.system`, `shell=True`, `shell_exec`, `Runtime.exec`     |
| Unsafe deserialization | Yes          | `pickle.load`, `Marshal.load`, `unserialize`, `XMLDecoder`  |
| XSS                    | Yes          | `innerHTML`, `dangerouslySetInnerHTML`, `template.HTML`     |
| Hardcoded credentials  | Yes          | `secret_strategy`: AWS / GitHub / Stripe keys, private keys |
| **SQL injection**      | **No**       | zero patterns in any of the eleven strategies               |
| **Weak cryptography**  | **No**       | zero patterns                                               |
| **Path traversal**     | **No**       | zero patterns                                               |

### The precedent that matters

The `profanity` public pattern in `.claude/hooks-daemon.yaml` carries a comment
recording that `\w*` produced 1,308 false positives on its first scan, and that
`ass` and `hell` were deliberately excluded because `assert`/`assign`/`hello`
make them pure noise — "a rule that cries wolf gets disabled". That is the
exact failure mode these three categories invite, and the bar any proposed
pattern must clear.

## Tasks

### Phase 1: Decide feasibility per category

- [ ] ⬜ **Task 1.1**: SQL injection — measure a candidate pattern's false-positive
  rate against this repository and the dummy client fixture before writing any
  strategy code
  - [ ] ⬜ Try the narrow form: concatenation/interpolation **inside** an
    `execute`/`query`/`prepare` call, not assignment to a variable
  - [ ] ⬜ Record the hit count and hand-classify every hit as true or false
- [ ] ⬜ **Task 1.2**: Weak cryptography — decide whether it is detectable at all
  given `usedforsecurity=False` is sanctioned by this project's own standards
  and is invisible to a construct-level match
- [ ] ⬜ **Task 1.3**: Path traversal — assess whether anything beyond a literal
  `../` in a path-join argument carries signal
- [ ] ⬜ **Task 1.4**: Write the decision up per category: implement, or record
  as a deliberate non-goal with the measurement that justified it

### Phase 2: Implement what survives Phase 1 (TDD)

- [ ] ⬜ **Task 2.1**: Add patterns per language strategy, test file first
- [ ] ⬜ **Task 2.2**: Every new pattern needs a negative case — the safe form
  that must NOT match, mirroring `_MUST_NOT_MATCH` in the evasion suite
- [ ] ⬜ **Task 2.3**: Add the category to `CATEGORY_EVIDENCE` in
  `tests/unit/handlers/pre_tool_use/test_security_antipattern.py` and to
  `get_claude_md()` in the same commit
- [ ] ⬜ **Task 2.4**: Remove the category from the "does NOT detect" disclaimer
  and from the pinning assertion, in that same commit
- [ ] ⬜ **Task 2.5**: Full QA + daemon restart verification

### Phase 3: Coverage visibility

- [ ] ⬜ **Task 3.1**: Coverage varies by language and the guidance now says so
  without saying HOW. Generate a per-language/per-category matrix from the
  registry so the asymmetry is visible rather than implied
- [ ] ⬜ **Task 3.2**: Decide where it belongs — `docs/guides/HANDLER_REFERENCE.md`
  is a better home than the resident `CLAUDE.md`, which pays a per-session cost

## Dependencies

- Related: Plan 00203 (advisory handler guidance coverage) — same
  guidance-versus-reality theme, different failure mode

## Technical Decisions

### Decision 1: Correct the guidance first, implement separately

**Context**: The gap was found mid-release, with the QA and acceptance gates
already run.

**Options Considered**:

1. Implement the three categories immediately — a feature spanning eleven
   language strategies, each needing patterns plus false-positive cover, built
   under release pressure against categories whose naive form is known to
   misfire.
2. Make the guidance truthful now, track implementation separately.

**Decision**: Option 2, shipped in v3.52.0. An overstated guard is actively
harmful — it invites an agent to relax vigilance about something unguarded —
so the claim had to go immediately. The implementation is a feature and is
tracked here.

**Date**: 2026-08-10

## Success Criteria

- [ ] Each of the three categories is either implemented with negative-case
  cover, or recorded as a deliberate non-goal with the measurement behind it
- [ ] Guidance and implementation cannot drift — enforced by the existing
  `CATEGORY_EVIDENCE` completeness gate
- [ ] No new pattern raises the false-positive rate enough to make disabling
  the handler attractive
- [ ] All QA checks passing; daemon restart verified

## Risks & Mitigations

| Risk                                                    | Impact | Probability | Mitigation                                                                     |
| ------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------------------ |
| Naive SQL pattern fires on safe concatenation           | High   | High        | Phase 1 measures before implementing; every pattern ships a negative case      |
| False positives lead a project to disable the handler   | High   | Medium      | Losing the five working categories is the real cost — weigh it explicitly      |
| Guidance re-added without implementation                | Medium | Low         | `CATEGORY_EVIDENCE` gate plus the by-name pinning assertion already block it   |
| Weak-crypto rule contradicts project security standards | Medium | Medium      | Task 1.2 checks `usedforsecurity=False` handling before any pattern is written |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes (git is the SSoT for "when"). -->

- Gap found and guidance corrected during the v3.52.0 release at `5795925f`
