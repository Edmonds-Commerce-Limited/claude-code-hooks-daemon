# Plan 00260 — Technical Decisions

Supporting document for [PLAN.md](PLAN.md). Decisions and their reasoning live
here so `PLAN.md` stays lean enough to read in full every session; this file is
read only when a task links to it.

### Decision 1: Guidance fix and behaviour change are separate

**Context**: Finding 1 reads as a bug, but the surprising behaviour is asserted
by passing tests, so changing it is a deliberate behaviour change, not a fix.

**Options Considered**:

1. Fix guidance only — honest immediately, leaves a rule that is arguably
   over-broad.
2. Loosen the handler so any pipe stage is allowed — changes safety behaviour on
   the strength of a documentation complaint.

**Decision**: Option 1 for Phase 1; Task 1.4 raises the behaviour question
explicitly rather than resolving it by accident. A guidance defect must never be
the justification for a silent safety change.

**Date**: 2026-08-19

### Decision 2: the pipe-stage-needs-`grep` condition is an artefact, and it stays

**Context**: Task 1.4 asked whether `_is_safe_readonly_command` returning
`False` when neither `grep` nor `echo` appears is *wanted* or merely *tested*.
Concretely: `cat f | sed 's/x/y/' | grep z` is allowed and
`cat f | sed 's/x/y/' | wc -l` is denied, though neither can modify a file.

**Finding**: it is an **artefact**, not a design. The handler's stated rationale
is that sed can silently destroy files. A pipe stage after a single `|` carrying
no `i`/`e`/`n` flag cannot write to a file at all, so the rationale does not
reach it. The `grep`/`echo` test is a proxy for "this looks read-only" that is
simply over-narrow — it asks whether a *particular other command* is present
rather than whether sed can write.

**Options Considered**:

1. Leave the behaviour, fix only the guidance.
2. Loosen `_is_safe_readonly_command` so any non-writing pipe stage is allowed.

**Decision**: Option 1 — the behaviour stays unchanged and only the guidance
was corrected. Three reasons, in order of weight:

1. **The cost of the false positive is near zero.** The agent uses `Read`, or
   adds the `grep` it probably wanted anyway. Nothing is unachievable; one tool
   call replaces another. A guard whose worst outcome is a marginally less
   convenient route is not worth loosening.
2. **Loosening widens where sed is permitted, which is the wrong direction for
   this plan.** Finding 2 is that agents are being pushed toward shell-first
   file manipulation; relaxing the stream-editor guard in the same release that
   documents that pressure would be working against ourselves.
3. **It is locked in by passing tests** (`test_matches_bash_sed_in_pipeline_without_grep`,
   `test_is_safe_readonly_command_rejects_cat_pipe_sed`). Changing it is a
   deliberate behaviour change needing its own tasks, not a rider on a
   documentation fix.

**Open for a human**: if the blunt rule is judged to cost more than it saves,
Option 2 is a small change — replace the `grep`/`echo` proxy with the real
question (can this invocation write?). That is a decision about policy, not a
defect to fix, which is why it is recorded here rather than actioned.

**Date**: 2026-08-19

### Decision 3: the Bash branch is STRICTER than the Write branch, and that is the real Task 1.5 defect

**Context**: Task 1.5 predicted a hole — a flagless `sed` in a heredoc body
slipping past `_SED_AS_COMMAND_HEAD`'s start-of-string anchor. Writing the test
disproved it: that case is already blocked, and not by the anchor at all.

**What the test actually found**, running the three heredoc shapes through
`matches()`:

| Bash heredoc writes…        | Verdict     | Same content via `Write` |
| --------------------------- | ----------- | ------------------------ |
| `deploy.sh`, flagless `sed` | BLOCKED     | BLOCKED — agrees         |
| `deploy.sh`, `sed -i`       | BLOCKED     | BLOCKED — agrees         |
| `NOTES.md`, prose about sed | **BLOCKED** | **ALLOWED** — disagrees  |

The mechanism is `matches()` Case 1: any Bash command mentioning sed is denied
unless it is a git/gh command or `_is_safe_readonly_command` spots a
`grep`/`echo`. A `cat > NOTES.md <<'EOF'` has none of those, so it is denied —
while `matches()` Case 2 returns `False` for `.md` explicitly, by design.

**Why this matters more than the predicted hole.** This plan's whole thesis is
that the Bash route is *more permissive* than the Write route. Here it is more
RESTRICTIVE, and inconsistently so: identical content and identical destination
get opposite verdicts depending on which tool an agent reaches for. It is also
a live instance of the Finding 1 class Phase 1 just fixed — `get_claude_md()`
promises sed is allowed in `.md` documentation, and for the Bash route that
promise is false. This repository writes prose about sed constantly, so the
guard blocks its own documentation.

**Decision — the two halves are split, and only ONE is deferred.**

**Guidance half: FIXED IMMEDIATELY.** Decision 1 of this plan says a guidance
defect is corrected at once and never used to justify a silent behaviour change.
That rule was applied to the `-n`, command-head and `grep`/`echo` cases in Phase
1 and then, inconsistently, NOT applied to this one — it was initially deferred
wholesale alongside the behaviour, which left `get_claude_md()` publishing a flat
"`.md` documentation files" allowance that is true for `Write` and false for a
Bash heredoc. An agent following it gets denied and learns the guard is
unreliable, which is precisely the harm Finding 1 is about. The guidance now
states that the exemption is **Write-tool-only**, names the heredoc case that is
denied, and gives the Bash form that genuinely works
(`echo 'avoid sed' > NOTES.md`, allowed because `echo` reaches
`_is_safe_readonly_command`). Pinned by two tests asserting verdict and guidance
together.

**Behaviour half: deferred to Task 3.1.** Do NOT bolt on a `.md` special case in
the Bash branch. It would be a second, weaker implementation of exactly the
redirect-target parsing Task 3.1 exists to centralise, and it would still have to
keep a compound command blocked
(`cat > x.md <<'EOF' … EOF && sed -i 's/a/b/' real.py`), which is the analysis
Task 3.1 is scoped to do once.

Pinned meanwhile as `xfail(strict=True)` in `TestHeredocWrittenShellScripts`,
so it flips to a plain pass the moment Task 3.1 lands and fails loudly if it is
ever "fixed" by accident.

**Lesson recorded, because the miss is the interesting part**: having written
Decision 1, I still deferred a guidance defect on the grounds that its
*behaviour* fix was expensive. The two are separable and the cheap half should
never wait for the expensive one — nothing published should stay false while a
code change is pending.

**Date**: 2026-08-19

### Decision 4: the ALLOW-trap is 18 handlers of 22, not one — and there is a second trap underneath it

**Context**: Task 3.1a was filed as a blocker on the strength of ONE handler.
Note E of [BASH-BLINDSPOT-MAP.md](BASH-BLINDSPOT-MAP.md) found that
`validate_instruction_content.handle()` ends with an explicit
`Decision.ALLOW` for any tool that is not Write/Edit, and reasoned that routing
a Bash event there would manufacture a false all-clear.

**Settled by measurement, not by reading.** Every discovered handler was called
with a real Bash payload and its actual return recorded. Reading `handle()`
would have found the one handler whose *reason string* makes the fall-through
visible ("Tool type not handled by validator"); the others reach the same
outcome silently, with no reason text to notice.

| Bash payload result      | Count | Handlers                                                                   |
| ------------------------ | ----- | -------------------------------------------------------------------------- |
| `matches()` False        | 22    | ALL of them — so there is no live bug today                                |
| `handle()` returns ALLOW | 18    | the trap, if `matches()` were ever flipped                                 |
| `handle()` returns DENY  | 3     | `absolute_path`, `sed_blocker` (own Bash rules), and `plan_time_estimates` |
| `handle()` returns None  | 1     | —                                                                          |

So the hazard is **eighteen times larger than the map recorded**, and the map
found the one instance that was legible from source. Silence and ALLOW are not
the same answer, and here almost nothing returns silence.

**The second trap, which the map did not identify at all.** Even a handler with
no explicit ALLOW is unsafe to feed a PATH without CONTENT. Demonstrated by
running each Group 2 handler twice on the same file path, once with dangerous
content and once with it stripped — which is exactly what a path-only utility
would deliver:

| Handler                | With content | Content stripped | Effect              |
| ---------------------- | ------------ | ---------------- | ------------------- |
| `security_antipattern` | DENY         | no match         | **false all-clear** |
| `error_hiding_blocker` | DENY         | no match         | **false all-clear** |

A guard that would have denied instead reports nothing. That is worse than the
blindness it replaces, because the blindness at least produces no verdict.

**Decision — Task 3.1's utility is re-scoped, and the split is now a SAFETY
boundary rather than a convenience one.**

1. **Group 1 (PATH-only, 7 handlers) may be routed a Bash write.** They decide
   from the path, and the three PostToolUse members read the bytes off disk
   themselves — where, being PostToolUse, the bytes are genuinely there. Two of
   them DENY (`lint_on_edit`, `validate_eslint_on_write`), so this slice
   restores two denying guards with no content plumbing.
2. **Group 2 (CONTENT-required, 11 handlers) must NEVER be routed a Bash event
   without real content.** Not "should prefer not to" — routing them path-only
   converts a silent gap into a positive all-clear, and the two rows above are
   the proof.
3. **For `>` redirect and `tee`, content does not exist at PreToolUse**, so
   Group 2 can never be safely served on those routes at that event. A heredoc
   body IS in the command string and is the exception. Any utility must
   therefore return content as `str | None` and callers must treat `None` as
   "do not decide", never as "nothing found".

**Why this does not reopen Decision 1.** The guidance half shipped in Phase 2
and does not depend on any of this: the resident block now states the boundary
once and eight false claims were corrected. This decision governs only the
behaviour half.

**Date**: 2026-08-19

### Decision 5b: Phase 3 splits at the DENY line — the utility ships, the new denials do not

**Context**: Phase 3 was written as one task: give handlers a Bash write
accessor and wire them to it. Building it made the two halves plainly
different in kind.

**Decision**: ship the accessor (`get_bash_write_targets`) and migrate
`markdown_organization` onto it. Do NOT wire `lint_on_edit` or
`validate_eslint_on_write` to fire on Bash writes without the user asking.

**Why the line is at DENY, not at effort.** Migrating
`markdown_organization` changes nothing about *what is allowed* — the policy
already forbids those writes, and the migration only stops six spellings from
evading a rule that was already in force. Wiring the two linters is a
different act: both handlers DENY, both currently see only `Write`/`Edit`, and
pointing them at Bash writes would create a denial surface that has never
existed. Every `>` into a `.py` file in every project using this daemon would
become lintable, and a lint failure there is a *post*-hoc denial — the write
has already landed, so the deny is a failure report the agent must then repair.
That is a product decision about how intrusive the daemon is, and it belongs to
the human who runs it.

**Consequence recorded honestly**: the blind spot is therefore NARROWED, not
closed. Phase 2's guidance still tells the truth for the handlers that remain
Write/Edit-keyed, and `tests/integration/test_bash_write_blindness_coverage.py`
still carries a verdict for each of them. This decision is why that file must
not be read as a to-do list.

**Reversal condition**: an explicit request to lint Bash-authored files, or a
measured incident where a `>`-authored source file shipped a defect the linter
would have caught.

**Date**: 2026-08-19

### Decision 5c: the shared accessor is CONSERVATIVE, so the legacy regexes stay unioned beside it

**Context**: `markdown_organization` detected memory writes with two
unanchored regexes over the raw command string. The obvious migration was to
delete them and call the new accessor.

**Decision**: call the accessor AND keep the regexes; union the results.

**Why**: the accessor declines any target needing an expansion the daemon
cannot perform, because a wrong path is worse than no path — it would attribute
a write to a file that was never touched. `$HOME/.claude/projects/x/memory/y.md`
is exactly that case, and the raw-string scan has always caught it. Replacing
the regexes would have quietly REOPENED a spelling the policy already blocked,
in the same commit whose stated purpose was closing bypasses. The union is safe
from the regexes' known prose false positive (`echo 'the arrow > file thing'`
yields the target `file`) because every candidate from either source is
filtered through `_is_claude_memory_path` before it can deny anything.

**A related sub-decision**: `~` was initially grouped with `$VAR` and globs as
"unexpandable" and declined. That was measured as a regression before the
migration landed — Claude's memory files live at `~/.claude/projects/*/memory/`,
so the most natural spelling of the policy's own target would have stopped
being blocked. A leading tilde is HOME by definition and the daemon can expand
it exactly, unlike a shell variable whose value it can only guess. It is now
expanded; `~otheruser` is still declined.

**Date**: 2026-08-19

### Decision 5: Task 3.2's SessionStart advisory is superseded by the Phase 2 intro

**Context**: Task 3.2 proposed a `bypassPermissions`-aware SessionStart advisory
announcing that the harness pushes toward Bash-first editing and that
write-time guards do not cover it.

**Decision**: do not build it. Phase 2 put that statement in the shared
guidance intro, which is resident in `CLAUDE.md` and read in full at the start
of every session — the same reach a SessionStart advisory would have, for no
extra handler, no extra dispatch and no second copy to drift. Adding it would
violate single-source-of-truth to buy nothing.

**Reversal condition**: if the guidance block is ever made opt-in or trimmed
per-project, the intro stops being guaranteed-resident and this should be
revisited.

**Date**: 2026-08-19
