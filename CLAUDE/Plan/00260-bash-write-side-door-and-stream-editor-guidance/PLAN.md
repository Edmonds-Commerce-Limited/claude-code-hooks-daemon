# Plan 00260: The Bash write side-door, and `sed_blocker`'s inaccurate guidance

**Status**: In Progress
**Created**: 2026-08-19
**Owner**: Unassigned
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A field report (`REPORT-2026-08-18-original.md`, filed alongside this plan) raised
two independent findings against v3.53.1. Both were verified against the source
and against the live daemon socket before this plan was written; the per-claim
verdicts are recorded at the top of that report. One finding was confirmed and
found to be *worse* than reported; the other was confirmed exactly, including its
handler count.

**Finding 1 — guidance, not behaviour.** `sed_blocker` blocks strictly more than
its `get_claude_md()` admits. The resident guidance lists `sed -i` / `sed -e` as
blocked and offers an "Allowed (read-only, no file modification)" section. In
fact `sed -n` is blocked, a bare flagless `sed` at a command head is blocked, and
a pure stdout pipe stage is blocked too unless a `grep` or `echo` also appears
somewhere in the same command. So `cat f | sed 's/x/y/' | grep z` is allowed
while `cat f | sed 's/x/y/' | wc -l` is denied — a distinction the guidance never
hints at, and whose only surviving example happens to fall on the allowed side.

**Finding 2 — an architectural blind spot.** 22 handlers key on the `Write`/`Edit`
tool names. (The field report said 21. Task 2.3's enumerating test found a 22nd,
`write_clobber_guard`, which shipped a day after the report was written — which
is the argument for a test over a hand-written census.) A file that reaches disk through a Bash heredoc, redirect or `tee` is
seen by none of them. This has always been true, but it used to be a theoretical
gap because agents reached for `Write`/`Edit` by default. It is now routinely
reachable: Claude Code injects a `system-reminder` in `bypassPermissions` mode
that explicitly directs agents to make file changes "with `sed`, heredocs, or
short scripts, rather than using the dedicated Read, Edit, or Write tools". The
daemon cannot suppress that instruction, and for projects where
`bypassPermissions` is permanent it is a standing condition of every session.

The two findings share one root: **the handler's model of "a write" is a tool
name, and the guidance it publishes describes a rule narrower than the one it
enforces.** Core Standard 15 (DBF) names this shape directly — a guard that only
fires at write time does not cover what arrives by another route.

## Goals

- Make `sed_blocker`'s `get_claude_md()` describe the rule the code actually
  enforces, including the pipe-stage-plus-`grep`/`echo` condition.
- Establish and document, per handler, whether it can see a Bash-mediated write.
- Decide (with a recorded rationale) which of the three candidate remedies for
  the side-door to adopt, and implement what is chosen.
- Leave the daemon's *behaviour* on `sed` unchanged unless a deliberate decision
  says otherwise — Finding 1 is a documentation defect, and the surprising
  pipe-stage behaviour is locked in by passing tests.

## Non-Goals

- **Not** a blanket shell parser in every handler. Shell is hard to parse safely;
  `pipe_blocker`'s own guidance shows how much nuance one command string already
  demands (`$( )` nesting, quoted vs unquoted heredocs, git `-m` exemptions).
- **Not** loosening `sed_blocker`. The false-positive string matching is
  deliberate and load-bearing for acceptance testing (see `CLAUDE.md`).
- **Not** re-litigating `bypassPermissions`. The harness instruction is a given.
- **Not** the commit-gate/`mv` half of this problem — Plan 00252 owns that.

## Context & Background

Verification evidence (full detail in the moved report's verdict table):

- `_SED_WITH_EXECUTION_FLAG` is `\bsed\s+-[a-z]*[ien]` (`sed_blocker.py:53-56`) —
  `n` is in the character class, so `-n` is blocked by design.
- `_SED_AS_COMMAND_HEAD` is `(?:^|;|&&|\|\|)\s*sed\b` (`:45-48`) — a flagless
  `sed` at a command head is blocked regardless of arguments.
- `_is_safe_readonly_command` (`:244-285`) returns `False` on its final line when
  neither `grep` nor `echo` appears, so a bare pipe stage is denied. This is
  intentional and tested: `test_matches_bash_sed_in_pipeline_without_grep` and
  `test_is_safe_readonly_command_rejects_cat_pipe_sed`.
- Live-socket probes reproduced all three denials, and confirmed that heredoc,
  redirect and `tee` writes carrying a `shell=True` call, a hardcoded AWS key, a
  `noqa` suppression, an error-suppression idiom, a new source file with no test,
  a relative path, a lock-file overwrite and a misplaced markdown file **all pass
  with no decision**.
- `markdown_organization` is the only handler that inspects Bash for write
  targets (`_bash_memory_write_target`, `:653-663`), and only for Claude
  auto-memory paths (Plan 00131).

**Relationship to Plan 00252**: 00252 addresses the sibling case — content
arriving by `mv` and reaching a commit unexamined by `sensitive_content` — and
fixes it at the *commit gate*. This plan addresses the PreToolUse surface and the
other 20 handlers. The two should be read together and must not duplicate work;
if 00252 lands a staged-content check first, Task 3.1 should reuse it rather than
build a parallel mechanism.

## Tasks

### Phase 1: Correct the `sed_blocker` guidance

- [x] ✅ **Task 1.1**: Rewrite `get_claude_md()` in `sed_blocker.py` so the
  blocked list includes `sed -n`, and a bare `sed` as a command head with or
  without flags.
- [x] ✅ **Task 1.2**: Retitle the "Allowed (read-only, no file modification)"
  section to describe the real rule — a pipe stage, and only when a `grep` or
  `echo` also appears in the command. State the `wc -l` counter-example
  explicitly so the boundary is not inferred from one lucky example.
- [x] ✅ **Task 1.3**: Add a test asserting the guidance text names `-n` and the
  command-head case, so the description cannot silently drift from the code
  again (DBF: the missing guard here is "nothing checks that guidance matches
  behaviour"). Delivered as `TestGuidanceMatchesBehaviour` in
  `tests/unit/handlers/test_sed_blocker.py` — five tests that assert the real
  VERDICT and the guidance text together, so changing either alone fails.
- [x] ✅ **Task 1.4**: Decided — see Decision 2. The behaviour is an ARTEFACT,
  not a design, but it stays; only the guidance changed.
- [x] ✅ **Task 1.5** — **premise disproved by measurement; no `re.MULTILINE`
  change made.** The task claimed a flagless `sed` inside a heredoc body evades
  the block because `_SED_AS_COMMAND_HEAD` anchors to start-of-STRING. Tested
  directly (`TestHeredocWrittenShellScripts` in
  `tests/unit/handlers/test_sed_blocker.py`): the flagless heredoc **is already
  blocked**. It never reaches that pattern. `matches()` Case 1 blocks any Bash
  command merely MENTIONING sed unless it is a git/gh command or
  `_is_safe_readonly_command` finds a `grep`/`echo` in it — and
  `cat > x.sh <<'EOF'` has none, so the catch-all denies it long before any
  anchor is consulted. Adding `re.MULTILINE` would therefore have changed
  nothing for this case, while widening an already-broad pattern. See Decision 3
  for the real defect the test found instead.

### Phase 2: Map the blind spot

- [x] ✅ **Task 2.1**: Enumerate every handler keying on `ToolName.WRITE` /
  `ToolName.EDIT` (21 at v3.53.1) and record, per handler, whether a
  Bash-mediated write can reach the same premise it guards.
  - Input map (all 21 read and verified): [BASH-BLINDSPOT-MAP.md](BASH-BLINDSPOT-MAP.md).
    It corrects the provisional split used in Task 3.1 below — `lint_on_edit`
    and `validate_eslint_on_write` are PATH-keyed (they read from disk, so a
    path-only utility restores them outright), `plan_time_estimates` is NOT
    path-keyed, and `absolute_path` should be dropped from Task 3.1's list
    because extending it to Bash would block ordinary relative-path shell use.
- [x] ✅ **Task 2.2**: Name the boundary in the resident guidance. Delivered
  differently from the brief, and the difference is the point — see
  [DECISIONS.md](DECISIONS.md). The harm was not a missing sentence but a
  FALSE CLAIM: eight sections opened with an unqualified "Writing X is
  blocked", so an agent read a clean Bash write as evidence of safety. Each
  claim was made route-accurate (no extra words; appending a disclaimer would
  have left the wrong sentence standing), and the class-wide fact is stated
  ONCE in the shared guidance intro rather than 22 times. The intro also names
  the guards that are UNAFFECTED — a reader told only that Bash bypasses the
  content guards could conclude Bash is unguarded generally, which is false and
  more dangerous than the gap being described. Two sections earned an explicit
  sentence because they IMPLY coverage rather than merely omitting it:
  `sensitive_content` (documents its git-metadata Bash handling) and
  `markdown_organization` (claims the bash side-doors are shut when two
  spellings of many are).
- [x] ✅ **Task 2.3**: `tests/integration/test_bash_write_blindness_coverage.py`
  — 37 tests. Enumerates rather than audits, in the spirit of
  `test_claude_md_guidance_coverage.py`, and forces a verdict plus a reason per
  handler. It immediately found `WriteClobberGuardHandler`, which shipped one
  day earlier with exactly this hole and is absent from the Task 2.1 map
  because that map predates it — so the guard has already done the job a
  hand-written sweep could not.

### Phase 3: Choose and build a remedy

- [x] ✅ **Task 3.1**: Evaluated and **adopted**. The evaluation that produced
  this — the seven PATH-only handlers a path utility restores, the two
  corrections to the Task 2.1 map (`absolute_path` and `plan_time_estimates`
  are off the list), and the 15-shape measurement showing
  `_bash_memory_write_target` is not fit to generalise — is in
  [BASH-BLINDSPOT-MAP.md](BASH-BLINDSPOT-MAP.md); the resulting scope decisions
  are [DECISIONS.md](DECISIONS.md) Decisions 5b and 5c.

- [x] ✅ **Task 3.1a** (BLOCKER for 3.1): done by MEASUREMENT — every handler
  called with a real Bash payload, rather than read. Two findings, both in
  [DECISIONS.md](DECISIONS.md) Decision 4, and both make the remedy narrower:

  - The explicit-ALLOW trap is **18 handlers of 22**, not the one the map
    found. `matches()` is False for all 22 today (no live bug), but
    `handle()` returns ALLOW for 18 if it is ever reached. Reading finds only
    `validate_instruction_content`, whose reason string makes the
    fall-through legible; the other 17 allow silently.
  - A **second trap the map did not identify**: even without an explicit
    ALLOW, feeding a PATH with no CONTENT makes a handler that WOULD have
    denied report nothing. Demonstrated on `security_antipattern` and
    `error_hiding_blocker` — DENY with content, no match with it stripped.
  - Consequence: the Group 1 / Group 2 split is now a **safety boundary**.
    Group 2 must never be routed a Bash event without real content, and for
    `>`/`tee` that content does not exist at PreToolUse.

- [x] ✅ **Task 3.1b**: fixed the blindness at its actual source. It was not 21
  independent decisions: `get_file_path()`/`get_file_content()` return `None`
  for anything that is not Write/Edit, so a handler CANNOT opt in even if it
  wanted to. `get_bash_write_targets()` now sits beside them in
  `core/utils.py`, tokenising with `shlex` (`punctuation_chars=True`) so the
  prose false positive is structurally impossible rather than filtered, and
  resolving relative targets against the event's `cwd`. Covered by
  `tests/unit/core/test_bash_write_targets.py` (37 tests). Contract is
  CONSERVATIVE — a target needing an expansion the daemon cannot perform yields
  nothing, because a wrong path is worse than no path.

- [x] ✅ **Task 3.2**: Evaluated and **declined** — see
  [DECISIONS.md](DECISIONS.md) Decision 5. Phase 2 put this statement in the
  shared guidance intro, which is resident in `CLAUDE.md` and read in full at
  the start of every session. That is the same reach a SessionStart advisory
  would have, for no extra handler and no second copy to drift. Reversal
  condition recorded.

- [x] ✅ **Task 3.3**: Decisions recorded — [DECISIONS.md](DECISIONS.md) 5b
  (Phase 3 splits at the DENY line) and 5c (the accessor is conservative, so
  the legacy regexes stay unioned beside it, and `~` is expanded rather than
  declined).

- [x] ✅ **Task 3.4**: `markdown_organization` migrated onto the accessor,
  closing six measured bypasses — `>|`, quoted paths containing spaces,
  `dd of=`, `cp`/`mv`/`install` destinations, and every `tee` operand after the
  first. The two raw-string regexes are KEPT and unioned rather than replaced:
  the accessor declines `$HOME/...` as unexpandable, and that spelling has
  always been blocked, so deleting them would have reopened a bypass in the
  commit meant to close them. Guidance updated to state the new, wider
  coverage and the narrower remaining gap.

- [ ] ⬜ **Task 3.5** (NOT started — needs a human decision): wire
  `lint_on_edit` and `validate_eslint_on_write` to fire on Bash-authored files.
  Deliberately excluded from Phase 3 — see [DECISIONS.md](DECISIONS.md)
  Decision 5b. Both handlers DENY, so this creates a denial surface that has
  never existed, and post-hoc: the write has already landed, so the deny is a
  failure report the agent must repair. That is a product decision about how
  intrusive the daemon is, not an engineering one. **Consequence recorded
  honestly**: until this is decided, the blind spot is NARROWED, not closed,
  and the verdict table in
  `tests/integration/test_bash_write_blindness_coverage.py` still describes
  live behaviour.

### Phase 4: Verify and close

- [x] ✅ **Task 4.1**: Full QA — 23/23 PASSED (12,730 tests, 95.2% coverage) on
  the exact committed tree.

- [x] ✅ **Task 4.2**: Daemon restarted, RUNNING, no load errors; every
  previously-bypassing shape re-probed live through the deployed forwarder and
  now DENIES, while prose containing `>`, reads of memory and ordinary project
  writes still ALLOW. Per-shape verdict table, and the quoted-space case that
  proved itself by denying its own probe: journal `26-08-19`.

- [x] ✅ **Task 4.3**: Two `truth-changes` entries staged in
  `CLAUDE/UPGRADES/UNRELEASED/truth-changes/vUNRELEASED.yaml` — one for the
  guidance truth (eight handlers had claimed Bash writes were content-guarded)
  and the enforcement truth (seven memory-path spellings now deny; the seventh,
  a copy INTO a memory directory, came from Task 4.4). Phase 1's `sed`
  reframing falls under the first entry — same class of false claim.

- [x] ✅ **Task 4.4**: Differential-tested the accessor against a real shell,
  AFTER 4.1–4.3 passed — three code defects, including a live bypass (a copy
  INTO a guarded directory), plus one artefact of the test itself.
  Directory destinations now resolve to the file actually written, and the
  harness is TRACKED at
  `tests/integration/test_bash_write_targets_vs_real_shell.py` (28 cases, exact
  equality with bash), because fixing defects while leaving the METHOD blind is
  what DBF exists to prevent. Detail: Decisions 5d/5e, journal `26-08-20`.

**Phase 4 does not close this plan.** Task 3.5 is open and needs a human
decision, so the status stays In Progress. Verification here covers what was
built, not the whole brief.

## Dependencies

- Related: Plan 00252 (same DBF shape, commit-gate surface, `mv` route). Sequence
  Task 3.1 after 00252's staged-content work if that lands first, and reuse it.
- Related: Plan 00131 (introduced the memory-path bash side-door closure that
  Task 3.1 generalises).
- Corroborated by: Plan 00257's `JOURNAL/00257-Journal-26-08-19.md`, where
  Finding 1 was hit independently and live during the v3.54.0 release (a
  `sed -n` range-read was denied) before this report was verified. That entry
  reaches the same conclusion by a different route and reasons the same way
  about the remedy — fix the guidance, do not loosen the guard — which is worth
  noting because two independent arrivals at one conclusion is the strongest
  evidence here that the defect is real and the fix is the documented one.
  It also records the aggravating factor: the harness instruction pushing
  agents toward Bash-first editing was observed in that same session, so
  Finding 2's premise is not hypothetical.

## Technical Decisions

Recorded in full, with their reasoning, in **[DECISIONS.md](DECISIONS.md)**:

1. **Guidance fix and behaviour change are separate** — a guidance defect must
   never justify a silent safety change.
2. **The pipe-stage-needs-`grep` condition is an artefact, and it stays** — it
   is over-narrow rather than wrong, and loosening it is a policy call for a
   human, not a rider on a documentation fix.
3. **The Bash branch is STRICTER than the Write branch** — the real Task 1.5
   defect, found by disproving the predicted one: a heredoc writing `.md` is
   blocked while `Write` to `.md` is explicitly allowed. Routed to Task 3.1
   rather than special-cased, and pinned meanwhile as `xfail(strict=True)`.

## Success Criteria

- [ ] `sed_blocker`'s guidance names `-n`, the command-head case, and the
  `grep`/`echo` condition, and a test pins that.
- [ ] Every Write/Edit-keyed handler has a recorded verdict on Bash blindness,
  enforced by a test.
- [ ] The chosen side-door remedy is implemented, or explicitly declined with a
  recorded rationale.
- [ ] No duplicate implementation of bash-write-target detection remains.
- [ ] Full QA passes and the daemon restarts RUNNING.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow goes in JOURNAL/. -->

- Filed from a verified field report; verification evidence in
  `REPORT-2026-08-18-original.md`.
