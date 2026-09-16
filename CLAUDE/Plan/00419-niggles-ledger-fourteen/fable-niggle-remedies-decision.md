# Plan 00419 — rulings on the three owner-gated niggle remedies

Decision document for Tasks 1.4 (N2), 1.5 (N3) and 1.7 (N5). Each ruling
below states the decision, the evidence it rests on, its cost, the strongest
case against it, and whether anything genuinely still needs a human. The
findings themselves are in [NIGGLES.md](NIGGLES.md); this document does not
restate them. Nothing here changes the plan's status header or implements a
remedy — it decides.

A pattern runs through all three: each was recorded as owner-gated on a
premise about WHICH code the remedy would change, and in all three cases the
code says something different from the premise. N2's "sweep" never blocks in a
session; N3's second gate is a project handler, not a library one; N5's "goal
check" is not this repository's code at all.

---

## Task 1.4 — N2: the archive-aware plan-link resolver

### Decision

Build the archive-aware resolver as unconditional behaviour, with no config
flag; the default-off flag the plan offers is rejected.

### Reasoning

**The gating premise — "changes what `--sweep` blocks on across every
project" — does not survive contact with the code.**

- No plan-QA check resolves links at all. The check catalogue
  (`src/claude_code_hooks_daemon/plan_qa/checks/`) has no link check;
  `path-existence` is advise-only and exempts archived plans by design
  (`plan_qa/checks/path_existence.py:1-9`). That is why `plan-qa --sweep`
  reported `0 findings` over eight dead links: it was never looking.
- The check that DID notice is docs-QA's `pointer-resolves`
  (`src/claude_code_hooks_daemon/docs_qa/checks/pointer_resolves.py`). Its
  SWEEP half is always ADVISE (`:9-15`, `:175-188`). Its EDIT and STAGED
  halves can BLOCK only a link that is NEW in that edit or commit
  (`:169-171`, `:213-215`); a link that was already broken is reported ADVISE
  because "the edit did not introduce the problem".
- The plan-QA sweep mode is typed `Literal["advise", "off"]`
  (`config/models.py:682`, `:1000`) — the in-session sweep structurally cannot
  block. The only thing that "blocks" is the CLI's exit code
  (`plan-qa --sweep` exits 1 on findings, `CLAUDE/core/PlanWorkflow.core.md:407`),
  which is a CI convenience.

So the resolver change would (a) remove false positives from an advisory
surface, and (b) make an advisory sweep honest. Neither tightens any gate
anywhere. A guard that becomes MORE accurate without becoming more restrictive
is not the kind of change that needs an opt-in.

**The doctrine already decided the shape of the remedy.** "Truth is enforced on
LIVE plans, never on the historical record" (`PlanWorkflow.core.md:421-444`):
an archived plan is a record, and editing it to match today's tree "falsifies
the record". N2's own new evidence (`NIGGLES.md` N2, the `journal-append-only`
vs `pointer-resolves` contradiction on 00408's day-file) shows the same rule is
STRUCTURAL for journals, not merely doctrinal. The tooling therefore has to
learn that `](../00NNN-y/PLAN.md)` names plan 00NNN wherever it now lives —
exactly what `bin/hooks-daemon find-plan` already does for humans. The
archive directories are already configuration (`plan_workflow.qa.completed_dir`
/ `cancelled_dir`, `.claude/hooks-daemon.yaml:1163-1164`), so the resolver
needs no new config key.

**Why not the flag.** The plan's own analogy with N7 is instructive but points
the other way. N7 was dissolved by scoping the artefact so that NO client's
gate surface changed. A default-off flag does not achieve that here — it
achieves "the fix exists and nobody has it". This project names that shape:
`guard-self-disablement-unwatched` (`utils/guard_config_drift.py:3-6`: "an
action that changes what a future session's guards will do, judged by no gate
and recorded nowhere"), and Plan 00420 records that "the failure mode of a
permissive flag is that nobody turns it off" (`00420-.../PLAN.md:99-101`). A
default-off correctness fix is the mirror image: nobody turns it on. The flag
also buys nothing anyone could want — there is no project for which "report a
resolvable plan link as dead" is the preferred behaviour.

**Design constraints the implementer should honour** (recorded here so the
decision is not re-derived):

1. Resolution by plan number across the whole plan tree (root + every archive
   dir), applied when the literal path fails. A link to a plan that never
   existed still reports dead.
2. Source-sensitive severity. From an ARCHIVED source or a `JOURNAL/` day-file,
   a link that resolves only via the archive is not a finding (the record
   stays as written). From a LIVE `PLAN.md`, it is an ADVISE finding whose
   remediation names the new path — a live plan should state present truth and
   can be repointed. Never BLOCK: the edit under judgement did not move the
   target.
3. The plan-QA SWEEP should gain a link check at ADVISE so the sweep stops
   reporting a tree clean when it is not (the credibility point in N2). Do not
   register it at EDIT as BLOCK; docs-QA already blocks a NEW dead link at
   edit and commit, and a second blocking check on the same fact is the
   double-gate shape N3 is about.

### Cost, and who bears it

Cross-subsystem coupling: `docs_qa` must read the plan directory and archive
names from `plan_workflow` config, which today it does not. Daemon maintainers
bear the build; every client gets the fix on upgrade with nothing to do. A
live `PLAN.md`'s stale sibling link goes from a docs-QA advisory to a plan-QA
advisory with a better remediation — no one loses a signal.

### Strongest argument against

A link that resolves only through this daemon's tooling is still dead for a
human clicking it on GitHub or in an editor. True. The answer is that the
project has already accepted this for its archive by ruling that records are
not rewritten, and for journals it has no alternative; the resolver makes the
tooling agree with the ruling rather than nag about a state the ruling
mandates. Live `PLAN.md` files keep an advisory precisely so the human-clickable
case is still repaired where repair is legitimate.

### Does a human gate remain?

No. The one owner-flavoured question — "do you want tooling to tolerate links
that are dead on disk?" — has already been answered by the owner in the
recorded doctrine for archived records and by the append-only rule for
journals. Everything else is a technical question with a defensible answer.

---

## Task 1.5 — N3: the two plan-close gates are mutually exclusive

### Decision

None of the three listed remedies; instead move the `header-body-coherence`
"body claims completion" finding from BLOCK to ADVISE at the EDIT stage, and
add it as BLOCK at the STAGED (commit) stage, keeping SWEEP as is. This is a
defect fix, not a policy relaxation, and it is not owner-gated.

### Reasoning

**Mechanics, verified in code.**

- `header-body-coherence` (`plan_qa/checks/header_body_coherence.py`) is a
  LIBRARY check registered at EDIT and SWEEP as `Level.BLOCK` (`:91-96`). Its
  completion branch fires when `doc.tasks.all_checked` (`:57`), and
  `all_checked` counts EVERY template checkbox in the file, Success Criteria
  included (`plan_qa/model.py:110-117`, `:251-253`).
- `plan_done_requires_holding_area` is a PROJECT handler
  (`.claude/project-handlers/pre_tool_use/plan_done_requires_holding_area.py`,
  "PROJECT-ONLY" at `:4-8`), priority 51, after `plan_qa_edit` at 44 (`:84-93`).
  It judges the WHOLE prospective content of the write (`:47-64`).
- Consequence: with the Edit tool, which replaces one contiguous span, the
  header (line 3) and the Success Criteria (near the end) cannot change in one
  call. Tick the criterion first: body all-ticked under `In Progress`, library
  gate denies. Flip the header first: `Complete` with no criterion, project
  gate denies. The only single-call move is a whole-file `Write` — which is the
  exact operation `R-WRITE-CLOBBER` exists to make agents wary of, and the
  riskiest way to touch a `PLAN.md`.

**Why the three candidates fall.**

- Remedy (2) as written already holds: the project handler "already sees
  whole content", so a single `Write` carrying both changes passes today. What
  (2) would have to mean to change anything is "accept a `Complete` flip with
  no criterion", which disables the gate. Not a remedy.
- Remedy (3) documents the whole-file `Write` as sanctioned. It makes the trap
  learnable and leaves the design incoherent, and it recommends the write
  shape the project otherwise discourages.
- Remedy (1) hard-codes the holding-area criterion's prose into a library
  check. The criterion IS a deployed-template line (`PlanWorkflow.core.md:288-289`),
  so it is not purely project-specific, but a check that matches one sentence
  of English is brittle and still leaves the general shape: any LAST checkbox
  a plan ticks before flipping its header hits the same wall.

**Why the chosen shape is a fix and not a relaxation.** The EDIT stage judges a
single write. The state "every box ticked, header still `In Progress`" is the
MANDATORY intermediate on the legal close path when the writer is the Edit
tool, so denying it at EDIT denies the legal path — a gate that cannot be
satisfied by any sequence of legal moves is a defect. The check's own docstring
says its purpose is to catch "finished work still marked In Progress" rot
(`:5-8`); that rot is a COMMITTED or LINGERING state, which the STAGED and
SWEEP stages see. Today `header-body-coherence` has no STAGED registration
(`:91-96`), so a plan committed in the all-ticked-`In Progress` state is caught
only by the next session's sweep. Adding STAGED at BLOCK closes that hole,
which means the invariant is enforced at least as strongly as today against
history, while the single-edit path becomes possible: tick the last box
(advisory: "flip the header next"), flip the header (project gate satisfied
because the criterion is present), commit (both `terminal-state-atomic`,
`plan_qa/checks/terminal_state_atomic.py:1-8`, and the new STAGED coherence
check judge the final shape).

The "Not Started with some boxes ticked" branch (`:74-86`) is not part of the
sequencing problem and stays BLOCK at EDIT.

### Cost, and who bears it

A library check changes severity at one stage and gains a registration at
another, for every client — a release-bound truth change that belongs in
`CLAUDE/UPGRADES/UNRELEASED/truth-changes/` (the holding-area step the
project's own gate enforces). `document_rule_checks` in `plan_qa/checks/common.py`
may need to learn a STAGED slot if it currently maps only EDIT and SWEEP. An
agent that ticks a plan's last box and walks away now gets an advisory instead
of a denial; the commit gate denies the same state on the next `git commit`.
Maintainers bear the change; agents lose two denials and a forced re-read per
plan close.

### Strongest argument against

"Advisories are skimmed; the block is what made agents flip the header." Fair,
and it is the reason the block is MOVED rather than removed: the very next
thing an agent does after ticking the last box is commit, and the commit gate
blocks. Also fair: this touches every client's edit-time behaviour, and the
ledger's instinct that library-gate relaxations should be asked for is a good
one in general. It does not apply to a gate whose legal path is impossible.

### Does a human gate remain?

No. "Should a gate be satisfiable on its own legal path?" has one answer. The
release-bound consequence (truth-changes entry) is process, not a decision.

---

## Task 1.7 — N5: the goal check counts idle teammates as running

### Decision

Remedy (1) is not available in this repository — the goal check is Claude
Code's own `/goal` evaluator, not the supervisor's and not the daemon's — so it
is recorded as an upstream finding. Do remedy (2) now (document teammate
reaping), and add an ADVISORY (never blocking) Stop-stage nudge grounded in the
`background_tasks` field the Stop payload carries, RED-first against a captured
payload.

### Reasoning

**Where the check actually lives.** The ledger attributes the refusals to "the
ccy supervisor's goal check". The supervisor only TYPES the goal:
`handlers/post_tool_use/goal_injection.py:5-12` describes the daemon writing a
`goal-intent` signal and "the standalone ccy PTY supervisor (the actuator)
consumes the signal and types `/goal ...` into the foreground chat" (Plan
00269). `.claude/ccy/claude-supervise.py` contains no `background_tasks` or
running-status logic (grep: every hit is the supervisor's own idle-tick
gating), and no module under `src/` reads `background_tasks` at all (grep: 0
hits; the field appears only in the vendored contract JSON,
`contracts/claude-code-hooks/Stop.json:27`, `:41`).

The primary source settles it. `https://code.claude.com/docs/en/goal`
(fetched today): "`/goal` is a wrapper around a session-scoped prompt-based
Stop hook ... Claude Code sends the condition and the conversation so far to
your configured small fast model"; and under "Background work defers
evaluation": "If a subagent or a background shell command is still running
when a turn ends, Claude Code skips the evaluation for that turn." The
running-vs-idle bookkeeping is Claude Code's. The raw hooks doc fetched today
says the same (`untracked/scratch/hooks-raw.md:2537`). Nothing in this
repository can teach that evaluator anything.

**So the "safety control" premise dissolves.** Task 1.7 was gated because
remedy (1) "changes when a stop is allowed". No change this repository can
make alters when Claude Code allows a stop. What remains local is:

1. **Documentation (remedy 2).** `worktree-reap` is documented; teammate
   reaping is not (`NIGGLES.md` N5). The natural end state of a correct
   parallel workflow — every branch merged, every teammate idle and still
   registered — is a session `/goal` cannot release. Record in the dispatch /
   agent-isolation guidance that a teammate whose work has been harvested is
   `TaskStop`ped, and why: an idle teammate is still "background work" to the
   `/goal` evaluator, and it holds context.
2. **An advisory the daemon can ground.** The Stop payload the daemon receives
   carries `background_tasks` (`Stop.json:41`; the contract warns that an
   ABSENT list means unknown, never empty, `:27`). A Stop-stage advisory —
   `AdvisoryResult`, so it cannot construct a deny — that says "the payload
   lists N background tasks; if these are finished teammates, `TaskStop` them
   or `/goal` cannot evaluate" changes no stop control and turns four refused
   stops into one message. The N4 lesson applies in full: the exact shape of an
   idle teammate's entry (does it appear? with what `status`?) must be read
   from a captured payload via `payload_capture` before a line of handler is
   written. If the capture shows idle teammates are NOT in the list, the
   advisory is not built and this document is wrong about (2); the
   documentation remedy stands regardless.
3. **Upstream.** Whether an idle in-process teammate should count as "still
   running" for `/goal` is a question for Claude Code's tracker. Filing it is
   the one thing here that is not this repository's engineering.

### Cost, and who bears it

Documentation: negligible, borne by whoever edits the guidance. The advisory:
one Stop handler plus a payload capture session; a Stop advisory fires on
every stop, so it must be silent when the list is absent or empty and
rate-limited like `background_process_tracker` (`:46-48`). Agents bear one
extra line of Stop context when they have unreaped teammates — the situation
in which they most need it.

### Strongest argument against

"The daemon should not paper over an upstream defect with advisories; every
such nudge is more context on every Stop." Fair. The counter is that the
advisory is grounded in a field Claude Code itself sends and fires only when
that field is non-empty, and that the alternative — four refused stops and a
full turn each — is the more expensive context bill. If the capture shows the
field does not distinguish the case, the advisory is dropped and only the
documentation remains.

### Does a human gate remain?

One, small and honest: whether to file the finding upstream with Anthropic.
That is the owner speaking for the project on a third-party tracker, and it is
theirs. Everything else — documenting the reap, an advisory that cannot block
— has a defensible technical answer and needs no one's permission.
