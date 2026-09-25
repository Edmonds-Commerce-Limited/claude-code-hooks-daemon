# Blast-radius policy decision — and its application to Plans 00394, 00396, 00414, 00415

**Kind**: decision record (a supporting document of Plan 00394, which hosts it
because it is the oldest of the four stalled plans). It changes no task list.
Each of the other three plans carries a short `fable-blast-radius-policy-decision.md`
pointing here and naming its own sub-decision.

**Author**: Fable (Claude), dispatched by the session coordinator to settle a
standing question four plans were independently blocked on, and to apply it.

## The standing question

> For a fix that closes a real gap but changes behaviour in every installing
> project — is the house default "ship it on by default", "ship it default-off
> behind a config flag", or "fix this repo only"?

Each of the four plans has a Phase-1 task reading "owner picks", and the pick
is the whole design in every case. This document argues that the repository
has already answered the question, repeatedly and consistently, and that
the four sub-choices have defensible technical answers once that policy is
stated. It also says, per decision, whether anything genuinely unknowable
from the repository remains.

## The evidence

The house style is not written down anywhere as a rule. It is recorded as
several dozen individual shipping decisions, and they line up.

### What ships ON by default

Every entry marked `recommended: true, dormant: false` in the v3.64.0
manifest has the same shape: it is an **advisory, or a gate whose remedy is
its own message**, and it is **silent when the thing it watches for is
absent**.

| Key                                                                   | Shape                                  | Why on, in the manifest's own words                                                                                                                                                    |
| --------------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lsp_noise_checker` (`v3.64.0.yaml:6-47`)                             | SessionStart advisory                  | "silent otherwise and on a resumed session … A project using none of the five supported languages never hears from it"                                                                 |
| `reference_repos` (`v3.64.0.yaml:239-287`)                            | top-level block, ships `enabled: true` | "shipping it OFF would mean every project that DOES adopt it must first discover a switch before the protection does anything, **which is exactly the reported failure**" (`:257-259`) |
| `merge_qa_report`, `daemon_sync_after_merge` (`v3.64.0.yaml:127-194`) | PostToolUse advisories                 | "silent when nothing moved and when nothing is attributable"                                                                                                                           |
| `daemon_upgrade_detector` (`v3.64.0.yaml:195-238`)                    | UserPromptSubmit advisory              | "SILENT when they match -- an advisory every turn for a fact that changes at most once per upgrade would be worse than the defect"; `is_dormant()` in self-install                     |
| `issue_filing_gate` (`v3.64.0.yaml:339-382`)                          | PreToolUse **deny**                    | on because it is "inert unless you actually file an issue against the hooks-daemon repository" — a refusal scoped to one command against one external tracker                          |
| `persistent_cron_assertor` (`v3.64.0.yaml:415-433`)                   | SessionStart advisory                  | "It says nothing at all until you declare `persistent_crons`"                                                                                                                          |
| `deployed_artefact_drift` (`v3.64.0.yaml:434-459`)                    | SessionStart advisory                  | "advisory and never blocks … repair is a choice rather than an instruction"                                                                                                            |

The fresh-install template says the same thing about the one guard closest
to Plan 00414's subject. `sensitive_content` is registered enabled even though
its two inputs are empty on a fresh install, because "adding terms is a
one-line config edit rather than also discovering the handler exists -- **a
guard nobody knows about protects nobody**" (`src/claude_code_hooks_daemon/daemon/init_config.py:147-152`).
`recovery_cron_advisor` — the handler Plan 00394 is about — ships on by
default for the same reason, stated in its own `get_default_enabled()`
(`handlers/post_tool_use/recovery_cron_advisor.py:453-463`; template line
`init_config.py:290`).

### What ships OFF by default

Every `dormant: true` entry in v3.64.0 and the UNRELEASED v3.65.0 manifest
also has a shared shape. It either **denies something**, **puts a human in the
loop**, **spends a resource the project did not ask to spend**, or is
**noisy by construction**.

| Key                                                                                            | Why off                                                                                                                               |
| ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `plan_workflow.close_requires_human_approval`, `plan_close_approval` (`v3.64.0.yaml:48-88`)    | human-in-the-loop; "the owner's ruling -- a mandatory sign-off 'is just going to lead to lots of plans kept open for no good reason'" |
| `worktree.merge_to_main_requires_human_approval` (`v3.64.0.yaml:89-126`)                       | human-in-the-loop, same ruling applied again                                                                                          |
| `persistent_crons` (`v3.64.0.yaml:383-414`)                                                    | spends a model turn per tick in every session; "there is no default job list"                                                         |
| `ask_user_question_blocker.options.mode: unattended` (`v3.65.0.yaml:11-30`)                    | changes a refusal's behaviour                                                                                                         |
| `session_actions_directive` (`v3.65.0.yaml:70-92`)                                             | "Opt-in, because it types a line into your terminal"                                                                                  |
| `routine_qa_sweep` (`v3.65.0.yaml:166-201`)                                                    | "a handler that fires with nothing to say becomes scenery nobody reads" — a judgement that most projects lack the input               |
| `host_hostname` (`v3.65.0.yaml:203-243`)                                                       | "pays status-line width"                                                                                                              |
| `flaggable_content_channel_guard`, `quarantine_artefact_read_guard` (`init_config.py:169-177`) | PreToolUse **deny**, members of the opt-in Plan 00278 feature family                                                                  |
| `model_fallback_detector` (`init_config.py:333`)                                               | "is noisy … Probably leave OFF"                                                                                                       |

The two cases that look like exceptions are not. `flaggable_work_advisor` is
an advisory that ships off — but it belongs to a feature family (Plan 00278)
whose master switch is elsewhere, and a handler that only has value once a
project opts into a family ships with that family's switch, not its own.
`bash_safe_mode` is "warn-first" and ships off — because it fires on a large
share of ordinary sequenced Bash, so it fails the silence condition, not the
advisory one.

### What the security register says about refusal surfaces

The register's own account of why 14 of 20 `unenumerated-spelling` rows are
still open: "every fix is a new refusal surface in every installing project"
(`CLAUDE/Security/README.md:136-141`). Plan 00412's consolidated worklist
uses the same line to owner-gate the fix for class 2,
`guard-self-disablement-unwatched`: "a PreToolUse deny on writes to
`.claude/hooks-daemon.yaml` is a new refusal surface in every installing
project" (`CLAUDE/Plan/00412-jobs-recurring-work-and-security-review/subagent-reports/260915-consolidated-defence-worklist.md:223-231`).
The buildable, non-gated half of that class shipped as two **reporting**
handlers, `guard_config_commit_gate` and `guard_config_drift`, both on by
default (`v3.65.0.yaml:94-164`), and the commit gate's manifest entry records
*why* it reports rather than denies: two denial designs were measured against
3,903 commits, both misfired on most genuine cases, and "a gate with an 80%
historical false-alarm rate gets switched off, which is the finding eating
itself" (`v3.65.0.yaml:106-111`).

### When "this repo only" was right

Exactly once in the recent record, and for a reason that generalises:
`daemon_restart_verifier` was moved out of the shared library because its
`matches()` "only ever fired inside the hooks-daemon repository itself, so it
never did anything for a client project" (`v3.64.0.yaml:462-475`). "This repo
only" is the answer when the **defect** is local, not when the **fix** is
convenient.

### The condition that makes "on by default" safe

Two mechanisms carry the weight:

- **Silence when clean.** Every default-on advisory above is silent when its
  input is absent. `reference_repo_sweep` goes further and records that a
  check *happened* even when clean, so a later reader can tell "nothing
  wrong" from "nothing checked" (`handlers/session_start/reference_repo_sweep.py:16-19`).
- **`CanBeDormant`.** A handler that config has switched off, or that has no
  input to act on, reports `is_dormant()` and the generated `CLAUDE.md` leaves
  it out rather than listing it as an enforced rule (Plan 00390,
  `CLAUDE/Plan/Completed/00390-niggles-ledger-five/PLAN.md:101-105`). This is
  what stops "on by default" from becoming "announced everywhere".

## The standing policy — decision

**A fix that closes a real gap ships ON by default in every installing
project when it is advisory (or a gate whose remedy is its own message) and
is silent where the gap does not exist; it ships DEFAULT-OFF only when it
denies an action, puts a human in the loop, spends a resource the project did
not ask to spend, or cannot be made silent when clean; and "fix this repo
only" is not a third option — it is either the answer to a defect that only
exists here, or the cheap first step shipped *alongside* the real fix, never
instead of it.**

Stated as tests, applied in order:

1. **Is the defect specific to this repository?** If yes, fix it here (a
   project handler or a config edit) and stop. None of the four plans passes
   this test — each names the gap in every client.
2. **Does the fix deny, ask a human, or spend a resource (a model turn, a
   terminal line, status-line width, network time) that the project did not
   opt into?** If yes, ship it dormant behind a named key, with the key and
   the reason in the manifest entry. This is the owner's recorded ruling on
   approval gates and on `persistent_crons`, and the security register's
   ruling on refusal surfaces.
3. **Otherwise, ship it on by default — provided it is silent when the gap
   is absent, silent on a resumed session where the state was already
   reported, and implements `CanBeDormant` where "the gap cannot exist here"
   is decidable from config.** A default-off advisory is a guard nobody
   enables, and the class-2 worklist names what that is: an unwatched
   disablement, only pre-applied.
4. **A handler whose value depends on an opt-in feature family ships with
   that family's switch**, not its own second switch (Plan 00384 Task 1.4's
   one-switch rule, `CLAUDE/Plan/Completed/00384-daemon-asserted-cron-and-autonomous-issue-sdlc/PLAN.md:81-84`).

### What it costs and who bears it

- **Client projects** bear a few lines of SessionStart or PostToolUse context
  per new session while a reported state persists, and a `migration_note`
  telling them how to switch it off. They do not bear a refusal they did not
  ask for.
- **This repository** bears the manifest entry, the `get_default_enabled()`
  / template consistency test, a `CanBeDormant` implementation where the
  handler has a config-decidable inert state, and the accumulated
  SessionStart budget. That budget is real: Plan 00390 measured the generated
  block at ~73 KB / ~18,300 tokens, which is why test 3's silence and
  dormancy conditions are conditions and not preferences.

### The strongest argument against

The register shows the cost of gating refusals: 14 known dangerous outcomes
that nothing denies, in every installing project, because each fix would be
"a new refusal surface". A policy that ships advisories freely and refusals
never is a policy that will keep accumulating open rows under "Defence
watches the gap, does not close it". The honest reply is that this policy
does not forbid a default-on deny — `issue_filing_gate` ships one — it
requires the deny to be scoped so narrowly that a project which never does
the denied thing never meets it. The open rows are open because their
denials cannot yet be scoped that way, not because denials are banned.

The second-strongest: default-on advisories teach skimming. Plan 00412's
worklist and three separate manifest entries all use the same sentence for
this ("gets switched off, which is the finding eating itself"). That is why
silence-when-clean is a hard condition of test 3 and why `routine_qa_sweep`,
which cannot yet promise it for most projects, correctly ships off.

### Does a human gate remain?

**No.** This is a codification of rulings the owner has already made and the
repository has already recorded — on approval gates (Plan 00367), on
`persistent_crons` (Plan 00384), on refusal surfaces (Security register,
Plan 00412), on inert-until-configured guards (`init_config.py:147-152`),
and on why a default-off protection is "exactly the reported failure"
(`v3.64.0.yaml:257-259`). Nothing in it turns on risk appetite or a
commercial preference the repository cannot see. It should be read by the
owner because it is now a standing rule, but reading is not a gate.

## Applying it

### Plan 00394 — where the failsafe cron coverage starts

**Decision: option 2 — give `recovery_cron_advisor` a SessionStart
counterpart, on by default, firing on new sessions only, sharing the
canonical prompt constant; do not take option 1 or option 3, because both
now carry a refusal surface the plan did not price in.**

Reasoning:

- The gap is in every installing project. `recovery_cron_advisor` ships on by
  default (`recovery_cron_advisor.py:453-463`, `init_config.py:290`), so every
  client already gets this cron — from its first plan write. Test 1 fails;
  option 1 alone is ruled out as an *answer*, and the plan itself says so
  (`PLAN.md:74-76`).
- **Plan 00416 changed the price of options 1 and 3.** Plan 00394 was filed on
  the 13th; two days later `cron_stop_enforcer` (UNRELEASED `v3.65.0.yaml:32-53`,
  `handlers/stop/cron_stop_enforcer.py:3-9`) made a `persistent_crons`
  declared job something the daemon **verifies at Stop and denies a stop
  over**. A declared job is no longer "advised", it is enforced. So option 1
  is not "config only, reversible" any more — in this repository it would
  deny a stop whenever the failsafe cron is absent — and option 3 would put
  that denial into every client. Test 2 fails for both.
- **Options 1 and 3 also contradict the failsafe cron's own lifecycle.**
  `recovery_cron_advisor`'s completion guidance says to `CronDelete` it once
  the session is genuinely finished (`recovery_cron_advisor.py:223-235`), and
  its canonical prompt says the same (`:179-182`). A declared job that the
  Stop enforcer requires to be present cannot also be a cron the agent is
  told to delete before stopping. The two mechanisms would fight on every
  clean session end. `persistent_crons` was also designed with "no default
  job list" as a stated property (`v3.64.0.yaml:411-413`), and its master
  switch defaults off (`config/models.py:1851`), so option 3 additionally
  needs a `changed` default flip every client inherits.
- Option 2 passes test 3. It is advisory; it is the same idempotent
  instruction the PostToolUse surface already gives ("Run CronList FIRST …
  reuse", `recovery_cron_advisor.py:193-203`); it fires on **new** sessions
  only, which is the plan's own finding about why the gap had not bitten — a
  resumed session keeps its crons (`PLAN.md:143-146`), exactly the
  `is_resume_session` gate every SessionStart advisory already uses
  (`secret_file_hygiene_checker.py:93-94`, `deployed_artefact_drift.py:96-97`).
- The "may both surfaces speak in one session" question answers itself: yes.
  The advice is idempotent by design, and the PostToolUse handler *already*
  repeats it every fifth progress edit (`recovery_cron_advisor.py:126, 211-221`). Repetition of a CronList-first instruction is the established
  design; a second speaker adds nothing a duplicate cron could come from.
- Share `_CANONICAL_CRON_PROMPT` and `CANONICAL_CRON_PROMPT_MARKER` from the
  existing module rather than copying them — the marker is already declared
  single-sourced for `failsafe_cron_blockage_suppressor`
  (`recovery_cron_advisor.py:160-166`), and a second copy is exactly the
  `asymmetric-sibling-protection` class the register watches for.

Costs and who bears them: this repository writes one SessionStart handler,
its tests, a manifest entry and the Task 2.4 correction to Plan 00384's
archived claim. Client projects bear an hourly no-op tick from session start
rather than from first plan write, in every session — a cost class the owner
already accepted when `recovery_cron_advisor` shipped default-on, and one the
daemon already bounds (`failsafe_cron_blockage_suppressor`, and the
`R-FAILSAFE-CRON-BACKED-OFF` back-off for sessions producing nothing).

Strongest argument against: the hourly turn is now spent in sessions that
never touch a plan — a short Q&A session, a one-off review — where the
PostToolUse design never spent it. That is a real cost. The plan's own reply
stands (`PLAN.md:59-64`): those sessions stall too, and the back-off handler
exists precisely to make an idle tick cheap. Option 1 as a stop-gap is *not*
recommended even as the "cheap first step", for the 00416 reason above.

Human gate: **none.** The only judgement an owner could still make is
whether the hourly tick in non-plan sessions is worth its cost, and the
repository already answers it twice (the handler's default and the back-off
machinery). Record it as an override the owner *may* make, not a decision
they *must*.

Two things found on the way, for the ledger rather than this plan: this
repository's config comment on `recovery_cron_advisor` reads "opt-in (false)
elsewhere" (`.claude/hooks-daemon.yaml:693-694`) and is wrong — the handler
is opt-out by default; and Plan 00388's provenance table
(`00388-…/PLAN.md:87-91`) is the right place for the new surface's row.

### Plan 00396 — how a topic maps to its owning docs

**Decision: option 1 — a config-declared `plan_grounding.topics` table, in a
handler that ships enabled but `CanBeDormant` (silent and unannounced) until
a project declares at least one topic; this repository declares its own
table, hand-derived from `CLAUDE/CLAUDE.md`'s routing table, as project
config.**

Reasoning:

- Option 3 is rejected on the plan's own evidence: it "would have FAILED on
  the real incident" (`PLAN.md:66-69`). A detector that misses its motivating
  case is not a detector.
- Option 2 makes a shipped handler depend on the shape of one project's prose
  table (`PLAN.md:62-65`). The routing table (`CLAUDE/CLAUDE.md:9-42`) maps
  *file → "route here for"* sentences, not *topic keyword → docs*; extracting
  match terms from it is a second heuristic on top of the first, and no
  client has that table. The correct use of option 2 is as the **source this
  repository reads when it writes its own option-1 config**, once, by hand.
- Option 1 is the `sensitive_content` shape exactly: registered enabled,
  inert until configured, because a guard nobody knows about protects nobody
  (`init_config.py:147-152`). It is also `command_hints`' shape — one handler
  driven by a config table, deliberately not a handler per entry
  (`handlers/post_tool_use/command_hints.py:3-6`). Test 3 passes: advisory,
  never blocks (plan non-goal), silent with no table, `CanBeDormant` so an
  unconfigured project's `CLAUDE.md` does not announce it (`PLAN.md:51`, Task 2.4).
- The generic-mechanism / project-specific-data split is the same one Plan
  00384 drew for `persistent_crons` (`00384/PLAN.md:26-28`): the daemon ships
  the assertion, the project declares what to assert.

Costs and who bears them: a project that wants the check writes a mapping,
and may never write one — that is the cost the plan already named
(`PLAN.md:60-61`). This repository writes the handler, reuses
`write_clobber_guard`'s read-tracking shape (`write_clobber_guard.py:97-98`;
a denied Read never counts, `:75-77`), and writes its own topics table. The
mapping is discoverable: a dormant-but-enabled handler is exactly what the
config-optimisation review inventories ("disabled-but-relevant handlers",
`config_optimisation_reminder.py:91-95`).

Strongest argument against: a table nobody fills is a handler that never
fires — the same shape as an un-enabled guard, and a project that most needs
it (one whose agents do not know where the docs are) is the one least likely
to have written the mapping. True. The mitigation is that this repository
fills its own table, so the motivating incident is covered where it
happened, and the mechanism is on the day a client wants it.

Human gate: **none.** The mapping mechanism has a defensible technical
answer and the plan's non-goals already settle advisory-not-blocking.

### Plan 00414 — an absent protected path is silent

**Decision: report absence for any path a live-enabled guard RESOLVES AND
WOULD CONSUME — today, `sensitive_content`'s word-list path, whether set
explicitly or inherited as the default — every new session while it stays
absent, silent on resume, silent once present, with an explicit way to
declare "no list, on purpose" that also makes it silent.**

Two questions, taken in order.

**Q1 — always, or only against an explicit declaration?** Neither, as the
plan poses it. The distinction that matters is not explicit-versus-default
but **consumed-versus-merely-protected**:

- The hygiene checker iterates `secret_file_guard`'s protected **globs**
  (`secret_file_hygiene_checker.py:98`, `secret_file_matching.py:54-61`).
  "Absent" is not a state a glob has; `.vault-pass*` is not missing from a
  project that has no vault. So "always report absence" is unimplementable
  for most of the list, and would be noise for the rest.
- The one concrete expected path in that list is the word list
  `sensitive_content` resolves and loads ("Missing file = feature inert",
  `handlers/pre_tool_use/sensitive_content.py:10-11, 544`). When that handler
  is enabled and the path is absent, a live guard's source loads zero terms
  and every consumer of it reports clean — F-PRIV-4, the register's own
  instance of `absence-indistinguishable-from-clean` (worklist `:402-422`).
  That is the finding, and it holds whether or not the key was typed.
- **"Only when explicitly declared" would have missed the motivating case.**
  This repository does not set `secret_word_list_path`
  (`.claude/hooks-daemon.yaml:186-190` carries `public_patterns` only); the
  collaborator's clone inherited the default path, and the default is what
  was absent. A rule keyed on explicit declaration has the same defect Plan
  00396 records for its option 3.

The class-5 Detector hypothesis says the same in its second part: "Fail when
a configured source resolves to nothing … should warn before it blocks"
(worklist `:454-460`). This plan is the warn.

**Q2 — once per checkout, or every session?** Every **new** session while the
state persists, silent on resume, silent once resolved — and never a
once-per-checkout marker. That is what every sibling the plan tells the
implementer to read actually does:

- `deployed_artefact_drift` speaks on every new session while drift persists
  and treats "repair is a choice" as the acknowledge route
  (`deployed_artefact_drift.py:96-97`; `v3.64.0.yaml:456-459`).
- `config_optimisation_reminder` speaks on every new session until a run is
  *recorded*, and prints the deliberate-silence command in the advisory
  itself (`config_optimisation_reminder.py:71-104`).
- `guard_config_drift` speaks on every session, resumes included, while the
  working tree disagrees with the commit (`guard_config_drift.py:127`).
- `lsp_noise_checker` speaks until the fix is applied (`v3.64.0.yaml:40-47`).

No SessionStart advisory in the tree uses a one-shot per-checkout notice,
and the plan's own objection to one is right: "easy to miss and easy to
ignore" (`PLAN.md:71-72`). What keeps the every-session form from being the
noise failure is the **acknowledge route**: a project with nothing to
withhold must be able to say so in config (an explicit null/none for the
word-list path, in whatever spelling the config model already accepts or a
new one), after which the check is silent because the declared state and
the disk agree. That is the `config_optimisation_reminder` shape: the
remedy is either fix it or declare it, and both end the advisory.

Design notes for the implementer, not decisions: put the absence finding in
`secret_file_hygiene_checker` rather than a new handler — two handlers
reporting on protected paths "teaches the reader to skim both"
(`deployed_artefact_drift.py:20-21`) — as a "declared but absent" section
resolved from the consuming handler's effective config; `Path.exists()` is
metadata and keeps the never-open-the-file contract (`PLAN.md:41-43`); the
message names the guard that is inert, which is Success Criterion 1.

Costs and who bears them: every fresh client install has `sensitive_content`
enabled with no word list, so every fresh client sees this advisory on new
sessions until it creates the list or declares none. That is one config edit,
the same edit every other advisory names, and it is the point — the
collaborator in the motivating case had no way to learn the file was
expected. This repository writes the finding, the acknowledge-route config
key if none exists, and the test that no protected file is opened.

Strongest argument against: a client with genuinely nothing to withhold is
nagged until they edit config for a feature they never wanted, and a nag
trains skimming — which is the failure Goal 3 (`PLAN.md:45-47`) exists to
avoid. The reply is that the alternative keeps F-PRIV-4 open in every client
too, and that the nag is one line, on new sessions only, with its own exit.

Human gate: **none.** Both questions have answers the sibling handlers
already gave; the plan's Task 1.2 anticipated that.

### Plan 00415 — should the freshness fingerprint cover config?

**Decision on the load-bearing question: report a SEPARATE
`config_fingerprint` in the health payload, and close the "a consumer
checking only the old one is no better off" objection at the choke point
every consumer already shares — `describe_fingerprint_mismatch` — which
takes both pairs, treats a missing config fingerprint as a staleness RISK
exactly as it already treats a missing source fingerprint, and names which
input moved.**

Reasoning:

- The plan calls the objection "decisive" and asks that it be weighed
  (`PLAN.md:79-86`). Weighed against the code, it dissolves. Every consumer
  in the tree reaches the verdict through one function: the acceptance
  harness (`tests/acceptance/conftest.py:108-130`, which *fails* rather than
  skips, `:135`), the CLI (`daemon/cli.py:1224-1256`), and the smoke test via
  that CLI (`scripts/qa/run_smoke_test.sh:73-75`). The health payload
  (`daemon/controller.py:1120-1123`) is the producer. There is no consumer
  that compares fingerprints by hand. So "a consumer left reading only the
  code fingerprint" is prevented by changing the one function's signature
  to require both — the sweep Task 1.5 asks for becomes a compile-time fact,
  not a review.
- A single blended digest cannot satisfy Goal 2 — the message "says WHICH
  input drifted" (`PLAN.md:47-50`) — and would break Goal 3, the honesty of
  `compute_source_fingerprint`'s `.py`-only contract
  (`daemon/source_fingerprint.py:52-54`; Plan 00371 non-goal,
  `00371/PLAN.md:91-96`). Two digests, one verdict, keeps both.
- "None means risk" is already the function's stated reasoning for the
  source half (`source_fingerprint.py:126-136`): "a caller that can't verify
  freshness must not silently trust a live-dispatch result either". A daemon
  that predates this plan reports no `config_fingerprint`, and must read as
  a RISK for the same reason — which also gives the upgrade path its
  correct failure mode (restart and retry) for free.
- Pin the invariant with a Detector, not a note: an integration test that
  asserts no module outside `source_fingerprint.py` reads
  `source_fingerprint` from a health payload without also reading
  `config_fingerprint`. That is a declared invariant pair in the register's
  `asymmetric-sibling-protection` sense, and it is what stops a fifth
  consumer re-opening the gap.

On the other two questions, a reasoned lean rather than a ruling, because
the plan's Task 1.1 asks for them together:

- **File bytes or resolved model?** The resolved model, serialised
  canonically (`model_dump(mode="json")` under `json.dumps(sort_keys=True)`),
  because it hashes what was actually *bound* — the plan's own argument
  (`PLAN.md:71-77`) — with determinism proved across two processes (Task
  1.4) before it ships, since a flapping guard is worse than the gap.
- **Unreadable config?** Mix a discriminator into the hashed input —
  `loaded` / `absent` / `invalid` — so that a malformed file and no file do
  not hash alike (`PLAN.md:88-92`), while the fallback-to-defaults that keeps
  the check from crashing (`source_fingerprint.py:99-107`) stays.

Blast radius under the standing policy: this is a correctness fix to a
verdict, not a new handler, and it ships on with no flag. Clients gain a
field in the health payload (additive) and a `check-source-fresh` that now
reports STALE after a config edit without a restart — which is the truth.

Costs and who bears them: this repository changes one function's signature,
one payload, and every in-tree caller; adds the determinism test and the
consumer-pair Detector; and sweeps Task 1.5. Clients pay nothing new — the
restart requirement is unchanged (plan non-goal).

Strongest argument against: two digests are two things to keep in step, and
a canonical serialisation of a Pydantic model is a maintenance surface that
can move under a library upgrade and make the guard cry stale at random,
which the plan rightly calls worse than the gap. The determinism test is
the answer, and it must be a real cross-process test, not a same-process
equality.

Human gate: **none.** The load-bearing question is structural and the code
answers it; the other two are engineering choices with a test that will say
whether they were made correctly.

## Summary

| Plan  | Decision                                                                                                                                    | Policy test that decides it                                    | Human gate |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------- |
| —     | On by default when advisory and silent-when-clean; dormant when it denies, asks a human or spends; "this repo only" only for a local defect | derived from the manifests and the register                    | none       |
| 00394 | Option 2: SessionStart counterpart, on by default, new sessions only, shared prompt constant                                                | test 2 fails options 1 and 3 after Plan 00416; test 3 passes 2 | none       |
| 00396 | Option 1: config-declared topics table, enabled but `CanBeDormant`; this repo declares its own                                              | test 3 (`sensitive_content` / `command_hints` shape)           | none       |
| 00414 | Report a consumed-and-absent path every new session, silent on resume/present/declared-none                                                 | test 3 plus the sibling handlers' own answer to Q2             | none       |
| 00415 | Separate `config_fingerprint`; one verdict function takes both and names which moved                                                        | correctness fix; no flag                                       | none       |

What this document does not do: implement anything, edit a PLAN.md task
list, or claim the owner has agreed. Each plan's Phase-1 "owner picks" task
can now be closed by recording this document as the pick, or re-opened by
the owner naming what here is wrong.
