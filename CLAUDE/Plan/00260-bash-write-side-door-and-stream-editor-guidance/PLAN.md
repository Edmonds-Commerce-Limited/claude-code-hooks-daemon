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

**Finding 2 — an architectural blind spot.** 21 handlers key on the `Write`/`Edit`
tool names. A file that reaches disk through a Bash heredoc, redirect or `tee` is
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
- [ ] ⬜ **Task 2.2**: For each handler that is blind, add one sentence to its
  `get_claude_md()` naming the boundary — e.g. "this handler sees
  `Write`/`Edit` only; a file written via a Bash heredoc is not checked".
  This is remedy option 3 from the report and the cheapest real win: an agent
  that knows a guard is blind can compensate; one that assumes coverage
  cannot.
- [ ] ⬜ **Task 2.3**: Add a coverage test in the spirit of
  `test_claude_md_guidance_coverage.py` that fails when a Write/Edit-keyed
  handler carries no recorded verdict about its Bash blindness.

### Phase 3: Choose and build a remedy

- [ ] ⬜ **Task 3.1**: Evaluate a shared "is this Bash call a file write?"
  utility, returning target paths — and, where cheaply available, the heredoc
  body. The seven PATH-only handlers it fully restores are
  `lock_file_edit_blocker`, `markdown_organization`, `plan_workflow`,
  `tdd_enforcement`, `lint_on_edit`, `markdown_table_formatter` and
  `validate_eslint_on_write`. Four corrections from the Task 2.1 map, all
  verified against source:

  - **`absolute_path` is OFF this list.** Its premise is about a TOOL
    ARGUMENT, not a file on disk; a Bash-aware version would have to block
    `ls src/`. `plan_time_estimates` is off it too — it genuinely needs
    content.
  - **The three PostToolUse handlers are PATH-only, not content-keyed**, which
    is the opposite of the obvious reading: they take the path and read the
    bytes off disk themselves. Two of the three DENY, so a path-only utility
    fully restores two DENYING guards with no content plumbing at all. That is
    the strongest single argument for this task.
  - **Heredoc bodies are literally in the command string**, unlike redirect
    output and `tee` (unknowable at PreToolUse). A utility returning
    `(target_path, heredoc_body | None)` therefore also serves much of the
    CONTENT column — and heredocs are precisely the shape the
    `bypassPermissions` reminder pushes agents toward, so this is the high-value
    case rather than an edge one.
  - **This is NOT "move `_bash_memory_write_target` to a shared module".**
    Measured against 15 command shapes, it covers `>`, `>>` and `tee` (first
    target only), and misses `>|`, quoted paths with spaces, `"$OUT"`, `dd of=`,
    `cp`/`mv`/`install`, and any script that opens the file itself; it never
    resolves relative targets. Worse, it FALSE-POSITIVES on prose —
    `echo 'the arrow > file thing'` yields target `file` — and the Task 2.1
    agent was denied by exactly that while gathering evidence. Its narrow
    memory-path substring test is what makes that tolerable today; generalised
    to every path in the tree, `lock_file_edit_blocker` would start denying
    commits whose MESSAGE mentions a redirect. Scope this as quote/heredoc-aware
    scanning plus `shlex` tokenisation plus cwd resolution.

- [ ] ⬜ **Task 3.1a** (BLOCKER for 3.1, found by the Task 2.1 map): audit every
  candidate handler's `handle()` for an explicit non-Write/Edit ALLOW before
  routing any Bash event to it. `validate_instruction_content.handle()` ends
  with `else: return HookResult(decision=Decision.ALLOW, reason="Tool type not handled by validator")` (verified at
  `validate_instruction_content.py:99-103`). Routing a Bash event there
  path-only would not merely fail to help — it would convert a blind spot into
  a POSITIVE ALL-CLEAR, which is strictly worse than the status quo. Silence
  and ALLOW are not the same answer.

- [ ] ⬜ **Task 3.1b**: fix the blindness at its actual source. It is not 21
  independent decisions: `core/utils.py:36` `get_file_path()` returns `None`
  for anything that is not Write/Edit, and `get_file_content()` gates the same
  way, so a handler CANNOT opt in even if it wanted to. The new accessor
  belongs beside those two, not inside any one handler.

- [ ] ⬜ **Task 3.2**: Evaluate a `bypassPermissions`-aware SessionStart advisory
  stating that the harness will push toward Bash-first editing and that
  write-time guards do not cover it. Cheap, honest, no parsing — it converts
  a silent gap into a known one.

- [ ] ⬜ **Task 3.3**: Record the decision in Technical Decisions with the
  rationale, then implement whichever options are adopted under TDD.

- [ ] ⬜ **Task 3.4**: If the shared utility is adopted, migrate
  `markdown_organization` onto it so there is one implementation, not two
  (DRY / single source of truth).

### Phase 4: Verify and close

- [ ] ⬜ **Task 4.1**: Full QA — `./scripts/qa/llm_qa.py all`.
- [ ] ⬜ **Task 4.2**: Restart the daemon and confirm RUNNING; re-probe the
  socket cases from the report's verdict table and confirm the new expected
  outcomes.
- [ ] ⬜ **Task 4.3**: Add a `truth-changes` entry if any documented statement
  about `sed` usage or handler coverage becomes false for client projects.

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
