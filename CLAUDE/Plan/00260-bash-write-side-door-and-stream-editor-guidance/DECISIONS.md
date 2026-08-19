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
