# Plan 00419 — Niggles

The full write-up for each entry in ledger fourteen. `PLAN.md` carries the
status and the tasks; the reasoning, evidence and candidate remedies live
here, because they are findings rather than plan state.

### N1 — `debug_hooks.sh` cannot work in the repository that dogfoods it

Found by a sub-agent following Plan 00418 Task 1.1, which names
`scripts/debug_hooks.sh` as the way to capture real hook payloads.
`CLAUDE/DEBUGGING_HOOKS.md` says the same, and `CLAUDE/HANDLER_DEVELOPMENT.md`
tells handler authors to debug first rather than guess at `hook_input`'s shape.
The script fails on this repository, and has two independent defects.

**Defect 1 — it looks in the wrong place for a self-install.**
`scripts/debug_hooks.sh:32` searches
`$PROJECT_ROOT/.claude/hooks-daemon/untracked/`. That directory **does not
exist here**: in self-install mode the daemon IS the project, and its sockets
live at `$PROJECT_ROOT/untracked/` — verified, two are there now
(`untracked/daemon-*.sock`). The comment above the line says it "supports both
suffixed (container) and unsuffixed (desktop) paths", which is true and beside
the point: it handles two socket NAMES and only one LAYOUT.

**Defect 2 — it dies before reaching its own fallback.** The line is

```bash
SOCKET_PATH=$(find "$PROJECT_ROOT/.claude/hooks-daemon/untracked/" -name "daemon*.sock" 2>/dev/null | head -n1)
```

under `set -euo pipefail`. `find` on a missing directory exits 1; `pipefail`
carries that through `head`'s success; the assignment therefore fails and
`set -e` kills the script — **before** the `CLAUDE_HOOKS_SOCKET_PATH` fallback
five lines below. So the env-var escape hatch is unreachable on exactly the
layout that needs it, and the failure is silent: no message, no non-zero
explanation, just nothing.

Reproduced directly rather than reasoned about, and the first attempt to
reproduce it was WRONG in an instructive way: running the pipeline bare in a
subshell reaches the next line and exits 0. It only dies in the ASSIGNMENT form,
because that is what makes the pipeline's status the statement's status. A
reproduction that drops the assignment concludes there is no bug.

**Why it matters more than a broken script.** Three documents route an agent
here as the sanctioned alternative to guessing at payload shapes. An agent that
follows that instruction gets silence, concludes the tool is unavailable, and
falls back to inference — which is precisely the failure mode Plan 00418 exists
to avoid, since the handler it is rebuilding was deleted the first time because
the project reasoned about a hook field from documentation instead of capture.

### N2 — archiving a plan silently breaks every link it makes to a sibling

Archiving moves `CLAUDE/Plan/NNNNN-x/` to `CLAUDE/Plan/Completed/NNNNN-x/`, one
level deeper. Every `](../00NNN-y/PLAN.md)` the plan contains then resolves to
`Completed/00NNN-y/...`, which does not exist — so a plan's OUTBOUND links all
break at the moment it is archived.

Found the day 00413 was archived: eight dead links across its `PLAN.md` and
`NIGGLES.md`, every one pointing at a plan that had graduated out of it
(00414, 00415, 00416). Those pointers are the entire reason a reader opens an
archived ledger, so the links that break are the load-bearing ones.

**Two separate gaps, and the second is the more interesting:**

1. **The archival procedure does not repoint outbound links.** The Plan
   Completion Checklist covers the `git mv`, the index row, the statistics and
   the retention window — all of which are about the plan's INBOUND references
   and the index. Nothing addresses the links pointing the other way.

2. **`plan-qa --sweep` reports the tree CLEAN with eight dead links in it.**
   Verified: the sweep was run immediately after the archival and again after
   this was found, and reported `0 findings` both times. Only docs-QA notices,
   as an ADVISORY — which is how it reached a sub-agent's QA run as unexplained
   noise in an unrelated worktree rather than reaching the person who broke it.

The inbound direction is already handled better, which is what makes the gap
easy to miss: links pointing AT an archived plan were caught the same day by a
docs-QA block on an edit. Direction determines whether you find out.

**Remedy is not yet decided** and it is a real fork: repoint links during
archival (mechanical, but rewrites an archived document), or teach `plan_qa` to
resolve links so the sweep stops reporting clean when it is not. The second is
the better guard — it catches the case regardless of how the links broke — but
it does not fix the eight that already broke, and it is the sweep's own
credibility at stake: a sweep that says "clean" while a tree is not is worse
than no sweep, because it is believed.

**New evidence, and it narrows the fork to one option.** Archiving 00409 broke
two inbound links in Plan 00408 — one in `PLAN.md`, one in a `JOURNAL/`
day-file. Repointing the `PLAN.md` one was uneventful. Repointing the JOURNAL
one tripped `journal-append-only`, because a journal is append-only and a
repoint is by definition a rewrite of an earlier entry. Leaving it dead tripped
`pointer-resolves` at BLOCK. Both were observed as real handler output, in that
order, rather than reasoned about.

So the two rules genuinely contradict each other on a journal link, and no
archival procedure can satisfy both: **"repoint outbound links at archival
time" is not a remedy a JOURNAL can accept.** That leaves teaching the resolver
that a plan may have moved to `Completed/` as the only option which fixes the
class without rewriting an append-only record — and it is independently the
better guard. The fork this ledger recorded as open is closed by the
constraint, not by preference.

### N3 — the two plan-close gates are mutually exclusive on the legal close path

Closing a plan legitimately requires two changes to `PLAN.md`: a ticked
holding-area success criterion, and a terminal status header. Each gate refuses
the other's change when it arrives first:

- `plan_done_requires_holding_area` refuses the status flip while no
  holding-area criterion is present.
- `header-body-coherence` refuses a fully-ticked body under a non-terminal
  header — which is exactly what adding the criterion first produces.

So neither order works. Both gates are individually correct and neither is
wrong about the state it refuses; the defect is that no sequence of single
edits satisfies both, because each is judging an intermediate state that only
exists on the way to a valid one.

The escape is a single whole-file `Write` carrying both changes, so the content
is judged once in its final shape. That works, but nothing says so — an agent
discovers it by being blocked twice and inferring it. This happened three times
in one session (00409, 00417, and once more before that), each time costing two
blocked calls and a re-read of the file.

**Candidate remedies**, none chosen:

1. Have `header-body-coherence` ignore the holding-area criterion specifically
   when judging "the body claims completion" — it is a step TOWARDS closing,
   not a claim of being closed.
2. Have `plan_done_requires_holding_area` accept a status flip when the
   criterion is being added in the same write (it already sees whole content).
3. Document the whole-file `Write` as the sanctioned close move, and have
   whichever gate fires second say so in its remediation.

(3) is the cheapest and the weakest: it makes the workflow learnable without
making it sound. (1) looks most correct — the criterion is a precondition of
closing, so reading it as a completion claim is the actual category error.

### N4 — `cron_stop_enforcer` wedged this session on the day it merged

The handler blocked every Stop reporting the `issue-sdlc` job missing, while
`CronList` showed that job present at the declared schedule. Diagnosed from a
real `Stop` payload captured with `payload_capture`, not from inference:

- `schedule` arrived byte-identical: `23 * * * *`.
- the DECLARED prompt is 576 characters, paragraphs separated by one `\n`.
- the DELIVERED prompt is 580 characters — the same words, with blank lines
  inserted between most paragraphs.

Nothing truncated it (580 is far below the 1000-char cap), so the cap
normalisation the module was built around could not help. The prompt is
re-rendered somewhere between the advisory an agent READS and the `CronCreate`
that agent makes, and `cron_is_asserted` compared the two byte for byte.

**This is severe, not untidy, and it compounds.** The match can never succeed,
so the block is permanent; and an agent obeying the block's own instruction
creates a SECOND cron from the same re-rendered text, which also never
matches, and which then costs an hourly model turn of its own. Following the
guidance makes it strictly worse. Any client project that declares a cron
would have hit this on first use.

**The evidence that fixed it also settled how to fix it.** The same capture
showed the three live crons disagreeing with EACH OTHER — the failsafe job
kept single newlines, the other two did not. Delivered whitespace is not a
stable property of the wire, so it cannot be part of an identity test.
Matching now normalises layout away (strip each line, drop blank lines) and
compares the WORDS; `schedule` stays an exact comparison, because that is a
five-field expression where any difference is a real one.

**The lesson worth keeping.** The module's docstring names three contract
constraints, each carefully established, and the code honours all three — the
defect is in a fourth nobody thought to ask about. Every constraint was about
what the WIRE does to a field. None was about what the round trip through a
rendered advisory and an agent's own retyping does to it, and that round trip
is the only way this field is ever populated. Reasoning about a delivery
mechanism is not the same as reasoning about a delivery PATH.

**It also argues the guard was too sharp for its first outing.** A handler
whose failure mode is "no stop is ever possible again" should not have shipped
straight to blocking. A warn-first period — the shape Plan 00418 was
deliberately given — would have surfaced this at zero cost.

### N5 — the supervisor's goal check reads `background_tasks` as live when they are finished

The ccy supervisor's stop-condition evaluation refused three consecutive
legitimate stops, each time citing "7 background_tasks with status 'running'"
and concluding work was in flight.

Nothing was in flight. Established four independent ways, none agreeing with
the field:

- `bin/hooks-daemon harvest-background`: `NO RUNAWAYS DETECTED` (twice, minutes
  apart).
- `ps`: zero `sleep`/`pytest`/`llm_qa` workers; **10 processes total** in the
  container, which is the daemon, its listeners and the probing shell.
- `ListAgents`: all 7 teammates `idle`, not running.
- The session's own notification history: all seven Bash background tasks had
  already delivered terminal notifications (five completed, two exit-144 from
  kills I issued deliberately).

So the field reports a task as `running` after it has finished. The count
matches the number of background tasks STARTED this session, which is the shape
of a list that is appended to and never reconciled on completion.

**The entries are IDLE TEAMMATES, not stale bash tasks, and that changes the
diagnosis.** The first version of this entry concluded no action available to
the agent could clear the flag. That was wrong, and it was wrong because the
claim was asserted rather than tested. The seven are in-process teammates that
had finished their work and gone idle; `TaskStop` on each terminated it
cleanly, and `ListAgents` then reported no agents at all. The flag cleared.

So the field is not lying about existence — those tasks were genuinely still
registered. It is conflating **idle** with **running**. `ListAgents` reports
the distinction correctly and the goal check does not consume it.

**Why it still matters.** An agent that spawns teammates and harvests all their
work is left with registered idle teammates and no prompt to reap them. Nothing
in the worktree or dispatch guidance says a teammate must be `TaskStop`ped once
its branch is merged — the worktree reap is documented, the teammate reap is
not. So the natural end state of a correct parallel workflow is a session that
cannot satisfy its own stop condition, which took four refused stops to
discover here.

**Two candidate remedies**, neither chosen:

1. Have the goal check treat `idle` as not-in-flight, which is what
   `ListAgents` already reports and what the words mean.
2. Document teammate reaping as the counterpart to `worktree-reap`, so the
   registered set empties as work completes rather than accumulating for the
   life of the session.

(1) is the fix; (2) is worth doing anyway, because an idle teammate holds
context anyone can still message by name.

**The lesson is mine, not the tool's.** I asserted "no action available to the
agent can clear this" across three turns and then found the action on the
fourth by trying it. Re-verifying the same four read-only checks felt like
diligence and was not — the untested claim was the one load-bearing statement
in the entry, and it was the one I never checked.

Worth pairing with N4: two guards in one evening able to block a stop on a
false positive. But N4 was a genuine defect in a shipped comparison, and this
is a reporting mismatch plus a missing convention, so they want different
fixes.

### N6 — declaring `layout.source_dirs` silently disables the TDD file exclusions

**Found**: creating a new package for Plan 00412 Task 2.1. Writing
`src/claude_code_hooks_daemon/routines/__init__.py` was DENIED by
`tdd_enforcement`, demanding a `test___init__.py`.

The first signal that the rule rather than the write was wrong: this
repository has 49 `__init__.py` files and 7 files named `test___init__.py`. A
rule that almost every existing instance violates is mis-specified.

**Proven, not inferred** (the N5 lesson): driving the real handler directly,
with only the layout changed between the two calls.

| project layout                | `matches()` for `…/routines/__init__.py` |
| ----------------------------- | ---------------------------------------- |
| zero-config                   | `False` — correctly exempt               |
| `layout.source_dirs: ["src"]` | `True` — wrongly gated                   |

**Cause.** `TddEnforcementHandler.matches` resolves in this order:

```python
if layout.is_test_path(file_path):        return False
if strategy.is_test_file(file_path):      return False
if layout.is_source_path(file_path):      return True     # ← short-circuits
return strategy.is_production_source(file_path)
```

`PythonTddStrategy.is_production_source` does exclude `__init__.py`, exactly
as the `TddStrategy` protocol docstring instructs ("Should also exclude
language-specific init files"). But the declared-layout branch returns True
first, so that exclusion is unreachable for any project that declares its
layout.

**The confusion is between two different questions.** The declared layout
answers *is this file in a source DIRECTORY?*; the gate needs *is this a
production source FILE?*. Consulting the declared layout first is right — a
project stating where its source lives outranks per-language inference — but
letting it answer alone throws away everything the language knows about
individual files.

**Not repo-specific.** Any client that declares `layout.source_dirs` loses
the exemption, and the more carefully a project describes itself, the more of
the language strategy it silently switches off. `layout:` reads as additive
configuration, so nothing warns that it subtracts.

**Fixed** with a RED-first reproduction. `TddStrategy` gains
`is_excluded_source_file(file_path)` — a file-level veto, independent of
location — consulted before either location rule. Python returns True for
`__init__.py` and its `is_production_source` now delegates to it rather than
re-testing, so the two cannot drift; the other ten languages have no such
file and return False.

Two guards had to pass before AND after, or the fix would have traded a false
positive for a gate that never fires: a real module under a declared
`source_dirs` is still gated, and an `__init__.py` under zero-config is still
exempt.

### N7 — the formatter of record is documented and unguarded, in a repository whose thesis is that this fails

**Found**: by doing it. Mid-way through Plan 00412 Phase 3 I ran
`python -m ruff format src/claude_code_hooks_daemon tests/unit` to tidy the
files I had just edited. Ruff is this project's LINTER; **Black is its
formatter**, and `scripts/qa/run_format_check.sh` runs Black auto-fixing.

`CLAUDE/QA.md:48` says so plainly — "**Format** (Black) / **Linter** (Ruff) —
both auto-fix via `./scripts/qa/run_autofix.sh`". So this is not a
documentation gap. I had read that file in this session and reached for the
wrong tool anyway.

**What it cost.** Commit `344ebf16` was meant to carry an eight-file fix. It
carried **163 files**, the other 155 being Ruff restyling every file it
touched. The next QA run reformatted 82 of them back to Black's style, which is
how it surfaced. An earlier commit, `5d70237f`, was the same thing in
miniature; at the time I recorded it as "the QA run's own formatter correcting
a file I had committed unformatted", which was wrong — the file was formatted,
just by the wrong formatter.

**Why it is a niggle and not merely my mistake.** Both formatters are installed
and both are a natural reach; `ruff format` succeeds, reports confidently, and
leaves a tree that passes `ruff format --check`. Nothing objects until a later
QA run rewrites the files, by which point the churn is already in pushed
history and mixed into an unrelated commit — so the review cost lands on
whoever reads that diff, not on whoever caused it.

This repository's whole argument is that a rule stated in prose and enforced by
nothing gets broken. Here is that argument, tested on its own author, a few
hours after reading the prose.

**Candidate remedies**, cheapest first:

1. A Bash guard denying `ruff format` (and `ruff --fix` where it restyles),
   naming `./scripts/qa/run_autofix.sh` in the deny message. Mirrors
   `enforce_llm_qa`, which already redirects `run_all.sh` to the LLM wrapper
   for exactly this kind of "right family, wrong entry point" error.
2. Configure `[tool.ruff.format]` to match Black, so the two agree and the
   trap stops existing. Weaker: it makes the wrong tool harmless rather than
   unavailable, and leaves two sources of truth for one decision.
3. Nothing, and rely on the QA run catching it. This is the current state, and
   the cost is that it catches it AFTER the commit is pushed.

**RESOLVED by (1), as a PROJECT-level handler.**
`.claude/project-handlers/pre_tool_use/ruff_format_blocker.py`, 20 tests.

The "owner-gated" note above was reasoning about a LIBRARY handler, and that
reasoning was sound — another project may legitimately use Ruff as its
formatter, so this must never ship to one. But the owner has already ruled on
this exact shape (Plan 00418): dogfood as a project handler first. A project
handler changes no installing project's gate surface, so the gate that made
this owner-gated does not apply to it. Promotion to the library would be a
separate decision, and the answer there is probably no.

`ruff check` and `ruff check --fix` are untouched — Ruff IS the linter here,
and the deny message says so, because the wrong lesson to take from the block
is "Ruff is banned". `ruff format --check` IS blocked: it writes nothing, but
it answers confidently about a tree Black owns, so passing it is a false
reassurance. Blocking only the writing form would have left the misleading
half of the trap in place.

Verified live after a daemon restart, both directions: `ruff format --check src` denied with the Black/`run_autofix.sh` guidance, `python -m ruff check`
still runs.

### N8 — the `Priority` constants are not the numbers a fresh install ships

**Found**: while preparing the v3.65.0 config-changes manifest. A sub-agent
reported `Priority.HOST_HOSTNAME = 6` against a template shipping
`priority: 7`, and called it a class-versus-template mismatch introduced by
Plan 00411. Checking it rather than taking it at face value gave a different
and larger answer: the whole `status_line` block diverges, and has for far
longer than that handler has existed.

| Segment                 | `constants/priority.py` | `daemon/init_config.py` template |
| ----------------------- | ----------------------- | -------------------------------- |
| `git_repo_name`         | 3                       | 5                                |
| `environment_indicator` | 4                       | absent                           |
| `account_display`       | 5                       | 6                                |
| `host_hostname`         | 6                       | 7                                |
| `model_context`         | 10                      | 10                               |

**Nothing misbehaves today, and that is the trap.** Relative order is preserved
across the divergence, so every segment renders where its author intended and
no test, no QA check and no user report can see a problem. The defect is
latent: `Priority.HOST_HOSTNAME`'s own comment states an intent ("beside the
environment indicator"), and `environment_indicator` is not in the template at
all, so the constant documents a relationship a fresh install cannot have.

**Why it is a niggle.** A constant that the shipped default ignores is a
constant that lies about its own authority. Someone re-ordering the status line
by editing `priority.py` — the obvious place, and the place the comments invite
you to reason in — changes nothing for any project that took the default
config. The feedback arrives never, which is the worst latency a change can
have.

It is also an instance of a class this project already names: a second source
of truth for one decision, with no check that they agree. The same shape as
`RETIRED_HANDLERS` being duplicated into `init_config.py` (Plan 00420's
Decision A), and as `get_default_enabled()` being duplicated there and welded
by `test_default_enabled_template_consistency.py` — which is the precedent for
the remedy, because that test exists precisely because the same duplication
bit once already.

**Candidate remedies**, cheapest first:

1. Extend the existing `test_default_enabled_template_consistency.py` idea to
   PRIORITIES: assert every handler the template names ships the priority its
   `Priority` member declares. Cheap, and it fails red today.
2. Generate the template's priority values from the constants, so the
   duplication stops existing. Better, and larger — the template is a hand-
   maintained string with comments per line.
3. Nothing. The current state: the two agree by luck and stay agreeing only
   while nobody edits either.

Remedy owner-gated — (1) makes a currently-silent divergence loud across the
whole template, which may surface more than the status-line block and is a
scope decision rather than a bug fix.

**Graduated to [00422 N1](../00422-niggles-ledger-fifteen/NIGGLES.md)**: not
terminal when this ledger closed, so it was re-filed in full rather than
counted.

### N9 — worktree creation was dead in this repository, and the seed list said why

Every `WorktreeCreate` in this checkout failed. Four `isolation: "worktree"`
agents were dispatched at once and all four came back with the same line:

```
HOOKS DAEMON: WorktreeCreate produced no worktree path
(is the worktree_create handler enabled?)
```

The handler was enabled, at priority 50, and had matched the event. It ran and
RAISED:

```
WorktreeSeedError: Cannot seed worktree — 1 configured entry is unusable:
  '.claude/block-words.secret': no such file or directory at the repository root
```

**The config comment sitting directly above that entry states the exact reason
the failure is wrong**: "Gitignored, so a worktree lacks it — and
`sensitive_content` does not fail without it, it goes silently INERT."
`secret-meta` confirms `exists: false`. So one subsystem's *legitimately
absent* was another subsystem's *fatal*, and the seed config had no vocabulary
to say which it meant.

Seeding had ONE policy for an absent source, and the fail-fast rationale in
`worktree_seeding.py` is sound for the case it was written for: a typo'd path
that silently seeds nothing is the failure the feature exists to prevent. What
was missing is that "seed this" and "seed this if it exists" are two different
intentions, and only one of them was expressible.

**Fixed** (RED first, 9 failed / 24 passed): `SeedEntry` gains `optional`,
defaulting to `False` so an unmarked entry keeps today's behaviour. It excuses
ABSENCE ONLY — an optional entry that is absolute, traverses upwards or
resolves outside the repository is still fatal, each pinned by its own test.
A non-boolean `optional:` is warned about and treated as REQUIRED, because the
loose coercion would only ever fail in the weakening direction.

**Why nobody noticed.** Nothing exercises `WorktreeCreate` until an agent needs
a worktree, so the break was invisible from the day the secret file stopped
existing. This is the class the niggles ledger keeps meeting: a guard whose
failure mode is silence until the moment you depend on it.

### N10 — a handler exception is reported as a configuration question

The transport turned the traceback above into "is the `worktree_create`
handler enabled?" — naming the one cause that was provably false, and omitting
the real error text, which the daemon had already logged in full.

The cost is not hypothetical: it sent the first diagnostic step to
`hooks-daemon handlers` to check a registration that was never in doubt. A
message that confidently names the wrong cause is worse than one that names
none, because it is actionable in the wrong direction.

**The rule this breaks.** A hook whose stdout is parsed as a VALUE cannot print
JSON, so the diagnostic goes to stderr — and that is exactly where the
handler's own exception message could have gone. The daemon HAS the reason at
the moment it fails to produce a path; nothing forwards it.

**Candidate remedies**, cheapest first:

1. Have the WorktreeCreate response carry the handler's failure reason, and
   the forwarder print it on stderr. The agent then reads the seeding error
   directly instead of a guess about config.
2. Failing that, drop the parenthetical. "Produced no worktree path" alone is
   less useful but not misleading.

Not owner-gated: a diagnostic that names a false cause is a defect, and both
remedies are strictly additive to an error path.

**Fixed** (RED first, 4 failed / 3 passed — the three that passed are the
guards that had to hold before AND after: the happy path still prints the raw
path, stdout stays EMPTY on failure, and unparseable output still fails rather
than echoing `{}`). `print_worktree` now reports `systemMessage` (a crashed
handler's exception) or `reason` (a deliberate refusal), and when neither is
present says so and names the logs instead of guessing.

The test extracts the function from `init.sh` and runs it in a SUBPROCESS,
which pins the code that actually ships rather than a copy, and exercises the
real stream separation — stdout is parsed by Claude Code as the worktree path,
so a diagnostic leaking there would become a directory name.

### N11 — the linter runs on gitignored scratch output

Extracting the embedded python rung from `init.sh` into
`untracked/scratch/rung.py` to compile-check it tripped `R-LINT-FAILURE` on
`UP041` — in code that is not mine, in a file that is gitignored, disposable,
and was never going to be committed.

`untracked/` is the project's own sanctioned scratch location: `project_containment`
actively pushes working notes there, and `pipe_blocker` names it as the
supported way to capture output. So the guards disagree with each other about
what that directory is for — one directs you to it, another lints what you put
in it.

**Why it is a niggle rather than a bug.** Nothing broke; the write landed and
the report was accurate about the code it read. The cost is a false signal at
the exact moment a scratch file is being used as a throwaway probe, which is
when the reader is least interested in its style.

**Candidate remedies**, cheapest first:

1. Add `untracked/` to `lint_on_edit`'s `exclude_paths` (or the project-wide
   `daemon.exclude_paths`). One line, and it matches how every other guard
   already treats that directory.
2. Nothing. Accept the noise on the grounds that a scratch file containing
   real code is still code — which is the argument against, and it is weak
   here, because the file is gitignored and cannot reach review.

Not owner-gated: this is a scope question about one project's own exclude list,
and remedy (1) turns nothing off for any file that can reach history.

**Graduated to [00422 N2](../00422-niggles-ledger-fifteen/NIGGLES.md)**: not
terminal when this ledger closed, so it was re-filed in full rather than
counted.

### N12 — a committed future-dated entry makes the journal permanently uncorrectable

Found by hitting it, minutes after N9 and N10, in this plan's own day-file.

Three rules meet and cannot all hold at once once a future-dated entry is
committed:

- `journal-append-only` — a correction is a NEW entry at the BOTTOM, never a
  rewrite.
- `journal-entry-ordering` — times increase down the file.
- `journal-entry-future-dated` — a timestamp ahead of the clock is wrong.

Correcting a future-dated entry means appending an entry whose HONEST
timestamp is numerically EARLIER than the wrong ones above it. So the
correction is reported out of order:

```
[advise] journal-entry-ordering: entries are out of chronological order:
`10:50` appears after `11:18`
```

The only ways to silence it are to move the correction out of the append
position (violating append-only) or to stamp it later than the entry it
corrects (perpetuating the false reading). **There is no legal move that
satisfies all three** — the same shape as N3, where two correct gates left no
satisfiable path, and the reason N3's remedy is the precedent here.

**Both advisories are ADVISE, so nothing is blocked** — this costs a confusing
report, not a wall. That is why it is a niggle and not a bug.

**Candidate remedies**, cheapest first:

1. Teach `journal-entry-ordering` that an entry which is out of order *only*
   with respect to entries the file itself flags as future-dated is not a
   finding. Narrow, and it fires exactly where the contradiction is real.
2. Give a correction entry an explicit grammar (e.g. a `correction` category)
   that `journal-entry-ordering` exempts. More honest to read, and it makes
   the correction legible as a correction rather than as another entry.
3. Nothing. The ordering advisory is noise in a rare case, and the day-file
   still reads correctly to a human.

Not owner-gated: (1) and (2) both narrow an advisory that is firing on a state
the other two rules force into existence, and neither weakens any gate.

**The upstream cause is worth separating from the remedy.** The entries only
became uncorrectable because they were appended with a `cat >> … <<'EOF'`
heredoc, which is not seen by the Write/Edit-time guards — CLAUDE.md states
exactly this ("a Bash write that drew no complaint is NOT a write that passed
those checks"). The identical mistake in plan 00411's journal went through
`Write` and was caught and fixed *before it landed*, seconds apart, in the same
session. `journal-entry-future-dated` is also deliberately EDIT-only (a batch
scan meets the entry when the append-only rule forbids acting on it), so a
heredoc append is not caught late either — it is caught never.

**Graduated to [00422 N3](../00422-niggles-ledger-fifteen/NIGGLES.md)**: not
terminal when this ledger closed, so it was re-filed in full rather than
counted. Its advisory against this plan's own day-file is still live, and is
the regression case for whichever remedy 00422 builds.

### N13 — a cron cannot be both cancelled for a session and declared in config

**Found**: by obeying the owner. The instruction was to cancel the `issue-sdlc`
cron, and `CronDelete` removed it. The next `Stop` BLOCKED.

`cron_stop_enforcer` (Stop, priority 7 — `.claude/hooks-daemon.yaml:970-972`)
compares the session's `session_crons` against every job declared under
`persistent_crons`, and `issue-sdlc` is declared there
(`.claude/hooks-daemon.yaml:1129-1144`). A declared job the session does not
have is precisely the state that handler exists to refuse, and it refused it
correctly.

**So a session-scoped cancellation is unexpressible.** There are two moves and
each fails the other's test: obeying the owner fails the stop gate, satisfying
the stop gate disobeys the owner. The cron was re-created to clear the block —
which restored the very thing that had just been asked to stop — and the
conflict was surfaced for a ruling rather than settled by whoever happened to
be standing in front of it.

**The knob that does exist is a different and larger act.** Removing the
`issue-sdlc` job from `persistent_crons`, or setting `enabled: false` on it,
genuinely stops the enforcement, because enforcement is downstream of the
declaration. But that is committed config: it stops the job for every session,
on every branch, until someone puts it back. "Cancel it for now" and "we no
longer run this job" are different decisions with different blast radii, and
only the second one has a spelling.

**THE CLASS, and this is the third sighting.** N3 (the two plan-close gates),
N12 (the three journal rules) and now this: a gate that no legal sequence of
moves can satisfy. Three occurrences in three unrelated subsystems inside one
ledger is a class, not a coincidence. The shape is the same each time — a guard
judging a STATE correctly, in a workflow where that state is a legitimate
INTERMEDIATE (N3's all-ticked body) or a legitimate TEMPORARY (N12's honest
out-of-order correction, this one's pause). The guard is right about the state
and wrong about the moment. N3's remedy is the precedent worth copying: it did
not relax the check, it moved it to the stage where the state is settled.

**Candidate remedies**, cheapest first:

1. A session-scoped pause the enforcer honours, recorded the way the Stop
   handler already records "blocked only on human input" — a marker the daemon
   writes and expires on its own, not a config edit. It gives "cancelled for
   now" a spelling, and leaves the declaration intact so the next session
   re-creates the job.
2. Have the enforcer's deny text name the config knob and say plainly that a
   session-scoped cancellation has no spelling, so whoever is blocked learns
   the wall is real instead of inferring it from two failed attempts. The
   N3-(3) shape: cheapest, and weakest, because it makes an unsatisfiable gate
   learnable rather than satisfiable.
3. Nothing. An owner instruction to cancel a declared cron is rare, and the
   cost is one blocked stop plus a re-creation.

Remedy owner-gated — (1) hands a session the ability to switch off a guard the
project itself declared, which is a decision about that guard's authority
rather than a bug fix, and the thing it would be overriding is the owner's own
instruction.

**Graduated to [00422 N4](../00422-niggles-ledger-fifteen/NIGGLES.md)**: not
terminal when this ledger closed, so it was re-filed in full rather than
counted. 00422 also owns naming the class this entry shares with N3 and N12,
so a fourth sighting is filed against the class rather than as a new niggle.

### N14 — the security-downgrade scan descended into linked worktrees

**Found**: a full QA run on this repository with four merged agent worktrees
still open under `.claude/worktrees/`. `check_security_downgrade_flags.py`
reported 28 violations and failed
`test_the_shipped_inventory_matches_the_shipped_tree`. Every one of the 28 was
a file the same scan had already judged at its real path.

**Cause.** The excluded-directory set matches a path COMPONENT, and a linked
worktree's components are `.claude`, `worktrees` and the agent BRANCH NAME —
none of them in the set — so the walk descended into a complete second checkout
of the repository and counted it as new findings.

**Client-facing, not our local mess.** Pruning the four worktrees cleared the
symptom, which is exactly why the exclusion has to exist: the next worktree
brings it straight back. The gate fails for ANY installing project that has a
worktree open when QA runs, citing paths that vanish with the worktree and that
the project cannot fix by editing any file it owns. The only move such a client
has left is to switch the check off, which is the worst outcome a security gate
can produce.

**Fixed**, RED first, in commit `2778206f`: `worktrees` joins `_EXCLUDED_DIRS`
in `scripts/qa/check_security_downgrade_flags.py`, pinned by
`TestScope::test_a_linked_worktree_is_excluded` (43 passed). The comment above
the set records why this entry is the one that bites a CLIENT, so the next
reader does not have to re-derive it. Consequent, measured on the same tree:
the check goes from 28 findings to 0, and pyright stops analysing 9,656 files
for a tree that holds about 1,667.

**The class.** An exclusion expressed as a NAME rather than as a fact about the
tree — the walk asks "is this directory called something I skip?" when the
question it needs answered is "is this a second checkout of the repository I am
already scanning?". Same family as N6, where a declared `layout.source_dirs`
answered *is this file in a source DIRECTORY?* for a gate that needed *is this
a production source FILE?*. Both are a proxy standing in for the real predicate
and quietly disagreeing with it.

### N15 — an owner gate whose premise had expired ten days before it was filed

**Found**: while ruling on it.
[`DECISION-secret-guard-module-path-false-positive.md`](../00412-jobs-recurring-work-and-security-review/DECISION-secret-guard-module-path-false-positive.md)
recorded that `secret_file_guard` matches the dotted module path of the
daemon's own redaction utility (`utils/secret_redaction`) against the shipped
`*.secret*` glob, concluded that "any edit that re-authors one of those import
lines is therefore denied", and on that basis held worklist row **F-PRIV-4** as
unbuildable pending an owner choice between four options.

Import STATEMENTS have been exempt since `b149808f` (2026-09-06) — TEN DAYS
before the document was filed on 2026-09-16. The guard blanks the module-path
span of every line-anchored `from|import` statement before it tokenises at all.
So the gate holding F-PRIV-4 rested on a condition that was already false when
it was written, and it stayed up for the whole of its life.

**What made it invulnerable.** The observation underneath it was real: a write
WAS denied, and the token the deny echoed WAS the dotted path. Only the CONTEXT
was inferred — and the document elided the token's surroundings, so the
spelling that actually tripped the guard cannot be recovered from the document
at all. The ruling
([`fable-secret-guard-module-path-decision.md`](../00412-jobs-recurring-work-and-security-review/fable-secret-guard-module-path-decision.md))
settled it by EXECUTING the guard rather than reading it: two live `Write`s in
one session against the running daemon — the `try:` plus `from … import …`
shape ALLOWED, a dotted string literal handed to `sys.modules` DENIED — plus 17
tests that already drew exactly that boundary.

**THE CLASS.** A decision document is a snapshot of a belief about the world,
and nothing re-checks it. An expired premise is indistinguishable from a live
one for as long as it is blocking, because it blocks exactly as effectively: no
error, no failing test, no signal of any kind. The work simply does not happen
and the row simply stays gated — and the longer a gate holds, the more
confidently it gets cited by everything downstream of it.

**Pair it with N10**, which is the same failure one level down. N10 was a
diagnostic that confidently named a cause that was provably false ("is the
`worktree_create` handler enabled?" while the handler was enabled and had
already raised), and it sent the first diagnostic step to check a registration
nobody doubted. This is a decision document that confidently named a blocker
that had already been removed, and sent a worklist row to an owner instead of
to a developer. Both cost more than silence would have, because both were
actionable and both actions were wrong. Confidently wrong beats silent, in the
bad direction.

**Candidate remedies**, cheapest first:

1. A decision document cites the commit and `file:line` its blocking premise
   was read out of, so the next reader can re-verify the premise in one command
   instead of inheriting it. This document's premise would have failed that
   check on the day it was written.
2. Establish a "the guard denies X" premise by EXECUTING the guard — a scratch
   `Write` against the running daemon — rather than by reading its globs. That
   is what the ruling did, and it cost two writes.
3. Nothing, and rely on the ruling stage to catch it. That is what happened
   here and it worked; the cost is that the gate held for ten days first, and
   finding out took a dispatched ruling rather than a glance.

Not owner-gated: (1) and (2) are authoring conventions for this repository's
own decision documents, and neither changes any gate. The INSTANCE is closed —
F-PRIV-4 is unblocked, the guard is unchanged, and nothing needs building for
that to stay true.
