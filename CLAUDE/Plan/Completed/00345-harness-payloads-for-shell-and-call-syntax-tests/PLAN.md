# Plan 00345: harness payloads for shell and call syntax tests

**Status**: Complete
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

Converting them roughly doubles automated coverage — which matters because every
block that stays manual is a block a human re-executes on every release, and
RELEASING.md Step 12's whole cost is that manual pass.

**Delivered: 94 → 187 of 228.** The estimate here was ~201; the shortfall is
accounted for and deliberate. Eight blocks were converted wrongly and reverted
(prose that a blacklist classifier read as shell — see Task 3.1), and the
remainder are Phase 5's, where a shell-shaped command drives another tool or a
handler is gated by project configuration this checkout does not have.

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

- [x] ✅ **Task 1.1**: Residual re-derived per handler file and recorded, so
  the conversion was driven by a list rather than by a grep at edit time

  - [x] ✅ **The first classification attempt was wrong, and cheaply so.** A
    naive filter (`not command.startswith("Use the "/"Create "/"Write ")`)
    reported all 104 as shell commands. It missed `Write(` — no space — so
    `ErrorHidingBlockerHandler`'s call-syntax probes counted as shell
  - [x] ✅ Re-derived against the LIVE playbook at conversion time rather than
    trusting the recorded split, which had already moved: **94 shell + 25
    prose**, being the earlier 129 less Phase 2's 10, with three `Write ...`
    blocks reclassifying from shell to prose
  - [x] ✅ Dry-run of all 94 as Bash payloads BEFORE converting any: **78
    behave as declared**, 12 have unsatisfiable patterns, 2 need a fixture
    file authored, 2 are not Bash tests at all

- [x] ✅ **Task 1.2**: RUN `setup_commands` / `cleanup_commands` in the harness

  - [x] ✅ Done, but **the argument in this task was retired by measurement**
    and the honest record matters more than the tick. It claimed skipping
    "would have parked 17 convertible blocks". It would have parked NONE: all
    17 are converted and all 17 pass with their setup never running
  - [x] ✅ Audited across the 197 blocks carrying a payload: **79 carry setup,
    and 77 are nothing but `mkdir -p`** — which changes nothing for a Bash
    probe, since no file needs to pre-exist for a command to be judged. Only
    five have setup that AUTHORS a file, and only #149 among them is an ALLOW
    probe passing on silence
  - [x] ✅ **Zero** path tokens across every setup AND cleanup command reach
    outside `untracked/scratch/`, so the containment claim is measured rather
    than asserted
  - [x] ✅ Worth doing anyway for a STRUCTURAL reason rather than an
    arithmetic one: a Write probe gets its preconditions established by the
    harness and a Bash probe did not. #148 is exactly a PostToolUse Bash probe
    whose handler ends at `Path(file_path).exists()`
  - [x] ✅ **No shell.** Each permitted command is TRANSLATED into a
    `FixtureAction` (`mkdir` / `remove` / `write`) the harness performs as a
    plain filesystem call, so there is no command-injection surface to reason
    about at all. The permitted list is closed and each entry maps to an
    operation: a shape nobody has translated is a shape nobody runs
  - [x] ✅ Vetted while PLANNING, so a block carrying one unacceptable command
    becomes a SKIP with a reason rather than being half-executed. Containment
    is checked on the RESOLVED path — `untracked/scratch/../../etc` starts
    with the sanctioned prefix and is not inside it

### Phase 2: The 10 call-syntax blocks (the Task 1.2 miss)

- [x] ✅ **Task 2.1**: All 10 converted to Write payloads across the five
  `strategies/error_hiding/` files. Executable blocks **94 → 104**, and all 10
  dispatch against the live handler with the declared decision
  - [x] ✅ These were the sixth grammar, and the audit named five. The
    conversion pass keyed on English sentences and never saw call syntax, so
    they sat in the residual looking like shell commands
  - [x] ✅ Write payloads, not Bash — confirmed necessary rather than assumed:
    the Phase 3 dry run found 5 OTHER blocks that really do have shell-shaped
    commands but match a different tool, and every one returned no decision.
    That is what these 10 would have done under a Bash payload, and the deny
    half would have reported PASS via ALLOW-by-not-matching
  - [x] ✅ `command` rendered from the payload here, unlike the shell blocks —
    call syntax is not pasteable into anything, so there was no human route to
    preserve
  - [x] ✅ Escaping was the live risk and is checked: the old prose carried
    `\\n` (a literal backslash-n for a human to read), while the payload needs
    REAL newlines, since the content is what the handler pattern-matches. An
    assertion that no `content` contains a literal `\n` two-character sequence
    now guards it

### Phase 3: The shell blocks

- [x] ✅ **Task 3.0**: Fix the event `cwd` the harness gives a Bash probe

  - [x] ✅ Not in the original plan, and found by dry-running rather than by
    reading. The harness pointed the event's `cwd` at an isolated temp
    directory, so a RELATIVE path in a command resolved outside the repository:
    `mkdir -p CLAUDE/Plan/99999-probe` was answered by `project_containment` in
    `plan_number_helper`'s place — a deny that still read as a pass — and its
    sibling ALLOW probe denied outright
  - [x] ✅ Plan 00243 measured the isolation as "changing nothing" and the
    measurement was real, but it could not have found anything: all 94 probes
    then were WRITE payloads whose `file_path` is absolute, and an absolute
    path cannot notice its cwd. **A measurement taken over a population
    structurally incapable of showing the effect reads exactly like evidence of
    absence**
  - [x] ✅ Fixed by REMOVING the argument, not by passing a better value:
    `ExecutableProbe` carries the root it was planned against, so no caller has
    a cwd knob to get wrong

- [x] ✅ **Task 3.1**: The shell blocks carry Bash payloads. Executable rises
  **104 → 187** of 228 dispatchable, all green

  - [x] ✅ `command` stays byte-identical, and the payload is DERIVED from it
    via `dispatch_as_bash=True` rather than written out beside it. For a shell
    test the bare command is already the best thing a human can be handed;
    `as_instruction()` would render `Use the Bash tool with command='...'`,
    strictly harder to paste
  - [x] ✅ Still a per-site DECLARATION, not a classifier — nothing inspects a
    command's shape. Declaring it alongside an explicit `tool_payload` raises,
    which is what keeps the shell-shaped-but-another-tool blocks honest
  - [x] ✅ An `InitVar`, not a field: `test_playbook_generator_json_field_ coverage` requires every field to reach the JSON, and emitting the flag
    would invite a harness to read it INSTEAD of the payload, reopening the
    split the derivation closes. A pre-existing test caught this
  - [x] ✅ Converted by an `ast`-based script rather than text matching, after
    two failures worth recording: a literal `git clean -fd` in a transform
    script is itself denied by `destructive_git`, and matching on the command
    alone was both ambiguous (handlers declare two tests with an IDENTICAL
    command) and insufficient (several build `command` with an f-string)
  - [x] ✅ **Eight blocks were converted WRONGLY and had to be reverted**, and
    the count above is the corrected one. The conversion classifier was a
    BLACKLIST — "shell" meant "does not open with a known prose phrase" — so
    eight prose blocks opening `With`, `Simulate`, `Run any`, `Stage` and
    `WebFetch` fell through to shell by default
  - [x] ✅ Every one of the eight expected **ALLOW**, which is why nothing
    caught them: a prose string dispatched as Bash matches no handler, returns
    no decision, and `verdict` correctly reads that as an allow. The DENY
    siblings of the same handlers failed loudly and were held back — so a dry
    run exposes prose only when the test expects a refusal. **The danger is
    concentrated entirely in the allow half**
  - [x] ✅ Guarded now by `test_every_bash_payload_is_a_command_a_shell_could_run`,
    asked as a WHITELIST: the first token must be executable, or the command
    must carry a shell construct. Unrecognised shapes are reported for a human
    rather than assumed fine

- [x] ✅ **Task 3.2**: The agreement invariant is in
  `tests/integration/test_acceptance_tool_payload_agrees_with_prose.py` — for a
  Bash payload, `tool_input["command"]` must equal the block's `command`

  - [x] ✅ Derivation makes this true by construction, so what the test
    actually guards is a HAND-WRITTEN Bash payload. It earned its place
    immediately: `project_containment` #45 was showing prose around its command
    instead of the pasteable string

- [x] ✅ **Task 3.3**: Repair the 12 assertions no message could satisfy

  - [x] ✅ Seven case-only (all `destructive_git`: the pattern says
    `permanently destroys`, the message opens `Permanently destroys`), widened
    to a character class following Plan 00243's `[Tt]ime estimate` fix — the
    capital is a function of sentence position, not of the phrase
  - [x] ✅ Five wording rot, each now quoting the live message rather than
    paraphrasing: #41/#42 `FLAGGABLE CONTENT CHANNEL` → the hyphenated rule ID,
    #78 the reworded worktree message, #83 the words the message actually uses,
    #110 `EXECUTED` → `command substitution` (the assertion had drifted to the
    rule TABLE's summary, which the verbose block does not repeat)
  - [x] ✅ PRE-EXISTING, not caused by this work. They passed all along because
    a human reads the message for MEANING and ticks it — only a literal matcher
    notices, and nothing ran one over these blocks until they gained payloads

### Phase 4: Verify the coverage actually moved

- [x] ✅ **Task 4.1**: Harness run, executable count risen, no new failure
  - [x] ✅ **Run TWICE**, both green. Plan 00243's harness passed once and then
    failed on `lsp_enforcement`, a `block_once` handler whose session had
    already spent its block, so a single green run establishes nothing
  - [x] ✅ Floor in `test_a_substantial_share_of_blocks_are_executable` raised
    90 → 185, so a regression that silently stops reading the field is caught
  - [x] ✅ Also measured what the green MEANS: 123 denies where the handler
    denied, 32 allows where it spoke without deciding, 39 silent allows. The
    silent ones are mostly NEGATIVE tests where declining to match IS the
    assertion — see the journal, so the number is not misread later

### Phase 5: The blocks that are not Bash tests

- [x] ✅ **Task 5.1**: #245 `DispatchDeclaration` needs the daemon
  reconfigured rather than a different event, so it carries that reason; its
  two siblings (#244, #246) are dispatched as `Agent` payloads. #217/#218
  `RemoteDocsRouting` both carry a reason instead — this checkout has no
  vendored tree, so the deny is unreachable and the near-miss would pass
  whether or not the handler ran
- [x] ✅ **Task 5.2**: #115 `ValidateEslintOnWrite` carries a reason naming the
  environmental precondition. `harness_cannot_produce` turned out to be the
  right field after all: this task assumed it meant "the input cannot be
  rewritten", but `plan_probe` reads it as the general "do not dispatch, here
  is why", and a second concept would have split one question across two fields
- [x] ✅ **Task 5.3**: Every remaining prose block carries a SPECIFIC reason —
  the generic "declares no tool payload" family is empty. It resolved into four
  boundary shapes, recorded in the journal: guarded material, a contract path
  the scratch rule forbids aiming at, the real staged tree, and assertions
  about a side-effect FILE rather than about the hook's answer

## Success Criteria

- [x] The harness dispatches 199 of 228 dispatchable blocks, up from 94
- [x] Every remaining skip still carries a reason, and each reason is either a
  permanent boundary or names what would make it convertible
- [x] Two consecutive harness runs are green on a clean tree
- [x] A Bash payload cannot disagree with the command a human is shown

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
