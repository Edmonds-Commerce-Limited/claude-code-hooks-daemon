# Plan 00345: harness payloads for shell and call syntax tests

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00243 built the acceptance harness and it works: 94 of the playbook's 228
dispatchable blocks now run automatically through the production hook wrappers,
asserting the decision AND the deny reason. The other 134 are reported as
skipped with a reason, and 129 of those give the same reason — the block
declares no `tool_payload`.

**107 of those 129 are convertible, and were left behind by a scoping accident
rather than a decision.** Task 1.2's audit counted 119 PROSE tests, because
prose was where the guessing problem lived: five English grammars expressing one
Write payload. A test whose `command` was already a literal shell string was
never in scope, on the reasonable ground that a human could paste it as-is.
Building the harness changed that ground without anyone re-deriving the
residual. A harness needs a declared payload just as much for `echo "git reset --hard ..."` as for a sentence, so the prose-era number was carried into a
post-harness world where it no longer described the gap.

Converting them roughly doubles automated coverage, from 94 to about 201 of 228
— which matters because every block that stays manual is a block a human
re-executes on every release, and RELEASING.md Step 12's whole cost is that
manual pass.

## Goals

- Declare a `tool_payload` on the 107 convertible blocks so the harness
  dispatches them instead of skipping them
- Keep `command` a literal, pasteable string for shell tests — the human route
  must not get worse in exchange for the machine route getting better
- Add an agreement invariant for Bash payloads, so the human and the harness
  are provably running the same command

## Non-Goals

- **Inferring a payload from the `command` string.** A Bash payload happens to
  be an identity mapping (`{"command": <the string>}`), which makes inference
  look free — but the classifier is what would be inferred, not the mapping,
  and it is exactly the guessing Plan 00243 removed. See Decision 1
- Converting the 22 English-prose blocks. Those are Plan 00243's documented
  deliberate skips in three categories, still correct and still permanent
- Changing the harness's verdict logic, which is settled and unit-tested

## Tasks

### Phase 1: Measure before converting

- [ ] ⬜ **Task 1.1**: Re-derive the residual per handler file and record it,
  so the conversion is driven by a list rather than by a grep at edit time

  - [ ] ⬜ **The first classification attempt was wrong, and cheaply so.** A
    naive filter (`not command.startswith("Use the "/"Create "/"Write ")`)
    reported all 104 as shell commands. It missed `Write(` — no space — so
    `ErrorHidingBlockerHandler`'s call-syntax probes counted as shell. The
    corrected split is below; re-derive it in the task rather than trusting
    these numbers, since handlers change
  - [ ] ⬜ Measured split of the 129: **79 shell command**, **18 shell-shaped
    but unusual** (`python3 -c "..."`, `[[ "..." == 0 ]]`), **10 `Write(...)`
    call syntax**, **22 English prose** (out of scope, see Non-Goals)
  - [ ] ⬜ 14 of the shell blocks carry `setup_commands`/`cleanup_commands` and
    16 are multi-line. Both need a decision in Task 1.2 before bulk conversion

- [ ] ⬜ **Task 1.2**: Decide how the harness treats `setup_commands` /
  `cleanup_commands`, which no converted block has needed so far

  - [ ] ⬜ The harness currently makes the world match the event's claim for a
    FILE (create for PostToolUse, remove for PreToolUse) and nothing else. A
    block with setup commands is asserting a precondition the harness does not
    establish, so it would probe a state that never existed
  - [ ] ⬜ Options: run them, or SKIP those 14 with a reason naming the
    unestablished precondition. Skipping is the safe default — Plan 00243's
    rule is that a false FAILED is worse than no coverage

### Phase 2: The 10 call-syntax blocks (the Task 1.2 miss)

- [ ] ⬜ **Task 2.1**: Convert the `Write(...)` blocks to Write payloads
  - [ ] ⬜ These are the sixth grammar, and the audit named five. The
    conversion pass keyed on English sentences and never saw call syntax, so
    they sat in the residual looking like shell commands
  - [ ] ⬜ **They must not receive a Bash payload.** Dispatching
    `{"command": "Write(\n  file_path=..."}` probes a Bash handler with a
    string no file-write handler matches: the probe goes green while testing
    nothing. That is the precise failure the harness exists to prevent, and it
    is silent
  - [ ] ⬜ Render `command` from the payload here (`as_instruction()`), unlike
    the shell blocks — call syntax is not pasteable into anything, so there is
    no human route to preserve

### Phase 3: The shell blocks

- [ ] ⬜ **Task 3.1**: Add `ToolPayload(tool_name=ToolName.BASH, tool_input={"command": <the existing command string>})` to the shell blocks

  - [ ] ⬜ Keep `command` byte-identical. For a shell test the bare command is
    already the best thing a human can be handed; `as_instruction()` would
    render `Use the Bash tool with command='echo "git reset --hard ..."'`,
    which is strictly harder to paste
  - [ ] ⬜ Delegable per handler file, as Plan 00243 Task 1.2 was

- [ ] ⬜ **Task 3.2**: Add the agreement invariant to
  `tests/integration/test_acceptance_tool_payload_agrees_with_prose.py` — for a
  Bash payload, `tool_input["command"]` must equal the block's `command`

  - [ ] ⬜ The Write-payload half of that file checks `file_path` appears in
    the command; this is the same guarantee for the other tool, and it is what
    makes "the human and the harness run the same thing" checkable rather than
    merely intended

### Phase 4: Verify the coverage actually moved

- [ ] ⬜ **Task 4.1**: Run the harness and confirm the executable count rose
  and no new failure appeared
  - [ ] ⬜ **Run it TWICE.** Plan 00243's harness passed once and then failed
    on `lsp_enforcement`, a `block_once` handler whose session had already
    spent its block. A single green run does not establish repeatability
  - [ ] ⬜ Raise the floor in `test_a_substantial_share_of_blocks_are_executable`
    so a regression that silently stops reading the field is caught

## Success Criteria

- [ ] The harness dispatches ~201 of 228 dispatchable blocks, up from 94
- [ ] Every remaining skip still carries a reason, and each reason is either a
  permanent boundary or names what would make it convertible
- [ ] Two consecutive harness runs are green on a clean tree
- [ ] A Bash payload cannot disagree with the command a human is shown

## Technical Decisions

### Decision 1: Declare the payload, never infer it from the command

**Context**: A Bash payload is `{"command": <the exact string>}` — an identity
mapping. Having the harness build one automatically for any block whose command
"looks like shell" would convert 97 blocks with no edits at all.

**Options Considered**:

1. Infer at dispatch time from the command string's shape.
2. Declare explicitly at each site.

**Decision**: Option 2. The mapping is not what would be inferred — the
CLASSIFIER is, and the classifier is precisely what Plan 00243 removed. The
evidence is already in hand: the first attempt at exactly this classification,
run to size the work, put 10 `Write(...)` blocks in the shell bucket because
they start with `Write(` rather than `Write `. Under inference those 10 become
Bash probes that no file-write handler matches, and a deny test that stops
matching its handler reports ALLOW-by-not-matching — which the harness correctly
treats as a pass. Ten tests would go green while testing nothing, and nothing in
the report would say so.

**Date**: 2026-09-07

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00345-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Follows Plan 00243 (Complete, archived), which built `ToolPayload`, the
  harness, and converted the 97 prose tests
