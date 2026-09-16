# Audit: is the persistent-cron feature finished?

Read-only audit for Plan 00412. Every claim below is from code, tests, config
and plan files in `/workspace`, not from commit messages or release notes.

## Verdict

**The declaration half is finished. The feature as a whole is not, and it was
never designed to be.**

What shipped (Plan 00384, released in v3.64.0) is a *declaration and
re-statement* mechanism: a project writes down the crons it wants, and at
session start the daemon reads that declaration back to the agent. That part is
complete, tested, inert by default, and works. It is genuinely finished for
what it claims to be.

What does not exist — anywhere, in any form — is the other half: **anything
that knows whether a declared cron was created, whether it fired, or whether
firing accomplished anything.** There is no verification, no run record, no
missing-cron detection, no no-op detection, and no runtime dedupe. The daemon
issues an instruction into the void and never learns what happened to it.

This is stated honestly in the source (`persistent_cron_assertor.py:13`: "It
asserts by instruction, never by verification"), so it is a deliberate
boundary rather than an oversight. But "deliberate boundary" and "finished
feature" are different claims, and a job system built on top of this inherits
the blindness.

There are also **three open plans** blocked on cron-adjacent owner decisions
(00388, 00394, 00408), **one shipped documentation defect** that makes the
documented config example fail validation outright, and **two smaller
inaccuracies** in shipped upgrade material. Details below.

---

## 1. What the feature does today, end to end

### Declaration

`persistent_crons` is a top-level config block. Schema in
`/workspace/src/claude_code_hooks_daemon/config/models.py:1785-1876`:

- `PersistentCronConfig` — `id` (required, non-blank), `schedule` (required,
  validated as exactly 5 whitespace-separated fields), `prompt` (required,
  non-blank), `enabled` (default `true`), `description` (default `""`).
  `model_config = ConfigDict(extra="forbid")`.
- `PersistentCronsConfig` — `enabled` (default **`false`**), `jobs` (default
  `[]`), plus a model validator rejecting duplicate `id`s.
- `active_jobs()` returns `[]` whenever the section switch is off, overriding
  each job's own flag.

Validation is at config-load time, so a malformed schedule is a load error
rather than a job that silently never fires.

This repository declares exactly one job, at
`/workspace/.claude/hooks-daemon.yaml:1068-1083`: `id: issue-sdlc`, schedule
`23 * * * *`, whose prompt tells the agent to invoke the `issue-sdlc` skill.

### Session start

`/workspace/src/claude_code_hooks_daemon/handlers/session_start/persistent_cron_assertor.py`
(priority 70, enabled by default, non-terminal advisory).

- `matches()` → `bool(self._active_jobs())`. Silent unless the section switch
  is on *and* at least one job is enabled.
- `_load_config()` re-reads `.claude/hooks-daemon.yaml` itself and degrades to
  `Config()` (silence) on `ValidationError`/`OSError`/`ValueError`, so an
  invalid config cannot take the rest of the SessionStart chain down.
- `handle()` emits a context block: the "crons do not persist" explanation,
  an explicit disclaimer that the daemon cannot see session memory, a
  three-step reconcile instruction, and then every active job rendered as
  id + description + schedule + full prompt (verbatim, so the agent can
  re-create it).

### What the agent is told

Literally: run `CronList` first; for each declared job with no equivalent
already listed, create it with `CronCreate` (`recurring: true`) using the
given schedule and prompt; if one *is* listed, create nothing.

### What the agent must do manually

Everything. Read the advisory, run `CronList`, compare by eye, call
`CronCreate` per absent job. The daemon takes no action and receives no
confirmation. If the agent skips the advisory entirely, nothing notices and
nothing reports it.

---

## 2. What it does NOT do

Each of these was checked, not assumed.

**No verification that a declared cron exists.** The handler's own docstring
explains why: the daemon cannot read Claude Code session memory, so a finding
phrased "this cron is missing" would be a claim it cannot support, and the
agent would act on it by creating a duplicate. A test enforces the wording —
`test_it_does_not_claim_to_know_what_is_running` asserts the strings
`is missing`, `is not running` and `no cron found` never appear in the output.

**No record of a cron's run.** I listed every state file the daemon keeps under
`/workspace/untracked/` (`goal-ledger.json`, `stop-events.jsonl`,
`background-processes.jsonl`, `verdicts.json`, `version_check_cache.json`,
`config_optimisation_state.json`, `skill_scan_state.json`, …). **None records a
cron tick.** `failsafe-cron-cadence.json` is the closest, and it is not a run
log — it is a backoff counter for one specific cron, and it is absent on this
machine because it has never armed.

**But a delivered tick IS observable, and this matters for the design.**
`failsafe_cron_blockage_suppressor` (UserPromptSubmit) already sees cron ticks
arrive as prompts and classifies them by substring match
(`CANONICAL_CRON_PROMPT_MARKER in prompt`, i.e. the literal
`"FAILSAFE RECOVERY CHECK"` —
`/workspace/src/claude_code_hooks_daemon/handlers/user_prompt_submit/failsafe_cron_blockage_suppressor.py:268`).
Since the daemon holds every `persistent_crons.jobs[].prompt` verbatim, it
could recognise a declared job's tick *exactly* rather than by substring. The
observability exists; nothing consumes it for declared jobs. **This is the
single cheapest place to add a run record.**

**No way to detect declared-but-never-created.** Nothing anywhere. The failure
is silent and its only symptom is work that did not happen — which Plan 00393
N1 records as the most expensive way to discover a missing cron.

**No way to detect fired-but-did-nothing.** Worse: by the `issue-sdlc`
runbook's own design, a tick that stops with a recorded reason *is* a
successful tick. So a no-op tick and a productive tick are indistinguishable
from outside, and there is no counter that would show a run of consecutive
no-ops. Plan 00388 records this being hit for real — seven issues all labelled
`agent-needs-human`, so every selection rule missed, and the tick correctly
did nothing while costing a full model turn, hourly, indefinitely.

**Dedupe protection: declaration-level only.** Duplicate `id`s are rejected at
config load. At runtime there is nothing but the instruction to run `CronList`
first. If the agent ignores it, a second identical job is created and fires
alongside the first.

**No `source` filtering on SessionStart.** I checked: nothing in the daemon
reads the SessionStart `source` field (`startup`/`resume`/`clear`/`compact`).
So the advisory re-fires on a resume and on a post-compact session start.
Plan 00393 N1 observed that a *resumed* session brings its crons back with
identical IDs and no `CronCreate` call — meaning on those events the advisory
is pure context cost, and an agent that skips the `CronList` step is one
careless turn away from a duplicate.

**No operator visibility.** `bin/hooks-daemon config` prints the handler
(`persistent_cron_assertor: enabled, priority=70`) but **not the declared
jobs**. There is no CLI way to list, inspect, validate or dry-run a declared
cron.

---

## 3. Known gaps recorded in-tree

### Open plans, all `**Status**: Not Started`

**Plan 00394 — failsafe cron coverage starts at first plan write.** The
failsafe recovery cron, the most safety-critical of the three live crons, is
*not* declared under `persistent_crons`. It is established by
`recovery_cron_advisor`, a **PostToolUse** handler gated on a plan-lifecycle
moment — so a session has no recovery coverage until its first plan write.
The plan states plainly that Plan 00384 justified this omission on a
mis-stated equivalence ("`recovery_cron_advisor` already establishes this
shape") which does not hold for the only property that matters: surviving a
new session. Blocked on an owner choice between three fixes with different
blast radii (config edit to this repo / new SessionStart handler / daemon
default job).

**Plan 00388 — failsafe marker wiped by other crons in multi-cron sessions.**
The `[awaiting-human]` suppression marker is cleared by *any* prompt that is
not the canonical failsafe prompt — including the `issue-sdlc` tick and the
watchdog tick. Reproduced against the real handler, both clear the marker. The
plan records the irony: "the feature that exposed this bug is also a cause of
it." It also absorbed Plan 00392 N1 — the `issue-sdlc` cron has **no
stand-down mechanism at all**. Blocked on an owner decision about how the
daemon tells a human prompt from an automated tick. Three approaches plus a
2′ are recorded; none is obviously right.

The provenance table in 00388 is directly relevant to any job system:

| Cron                | Prompt origin                                                                           |
| ------------------- | --------------------------------------------------------------------------------------- |
| failsafe recovery   | daemon-authored verbatim (`recovery_cron_advisor`)                                      |
| issue-sdlc          | declared in config (`persistent_crons.jobs[].prompt`)                                   |
| background watchdog | **agent-composed** (`background_process_tracker` describes intent, leaves wording open) |

Only the middle row is a declared job. A job system that assumes "every
recurring thing is declared" is wrong today for two of three live crons.

**Plan 00408 — handler hygiene.** Records that
`persistent_cron_assertor.py:74` hardcodes the config path rather than asking
`ProjectContext.config_path()`. Noted as pre-existing house style (three other
handlers do the same), not as a defect.

### In Plan 00384 itself

Every task and success criterion is ticked, but two carry explicit caveats:

- Success criterion on prompt injection: "**partially verified, and the limit
  is recorded rather than papered over.** No adversarial body existed in the
  backlog to test against… A deliberately hostile body remains untested."
- The journal's closing entry (`thought`, "what I would not claim about this
  loop") records that the stale-`agent-working` recovery path "is written and
  has never fired", and that the loop's whole safety argument rests on
  `/release` staying human-gated.

Task 1.1 also records that `CronCreate` is a harness tool and cannot be
unit-tested, so what is pinned by test is only that the advisory explains
*why* re-creation is needed.

### Tests

Two files, both green (`27` cases, run during this audit):

- `/workspace/tests/unit/config/test_persistent_crons_config.py` — inertness,
  5-field schedule validation, blank id/prompt rejection, duplicate-id
  rejection, `active_jobs()` gating, unknown-key rejection.
- `/workspace/tests/unit/handlers/session_start/test_persistent_cron_assertor.py`
  — silence conditions, output content (schedule/prompt verbatim, id,
  `CronList`+`CronCreate` present, "why" present), the no-false-claims wording
  guard, multi-job rendering, wiring.

No xfails, no skips, no TODO markers, no allowlist entries. **What is absent
is any test of behaviour beyond the advisory's text** — which is consistent,
since there is no behaviour beyond the advisory's text.

The declared acceptance test carries
`requires_event="SessionStart event (new session only)"`. I checked how that
field is consumed: it is metadata rendered into the playbook
(`daemon/playbook_generator.py:471`) and nothing more. So the only end-to-end
check of this feature is a **manual** one at a real session start.

---

## 4. Defects found during this audit (not recorded anywhere in-tree)

### D1 — the shipped config example does not validate (real, user-facing)

`/workspace/CLAUDE/UPGRADES/config-changes/v3.64.0.yaml:400-408` documents the
block as:

```yaml
persistent_crons:
  enabled: true
  jobs:
    - name: issue-sdlc          # <- schema field is `id`
```

and its prose (line 392-393) says each job takes "a `name`, a `schedule` and
the `prompt`". The schema has **no `name` field**, requires `id`, and sets
`extra="forbid"`. Validated against the real model:

```
2 validation errors for PersistentCronsConfig
jobs.0.id    Field required
jobs.0.name  Extra inputs are not permitted
```

A client copying the documented example gets a hard config-load failure. This
is the manifest a client reads during `check-config-migrations`, and the entry
carries `migration_note` saying this is "the one new feature in this release
that a project must opt into BY HAND" — so the example is the primary
adoption path, and it is broken.

Nothing guards this: `example_yaml` is free text parsed only as a string
(`install/config_migrations.py:154`) and printed to the client. No test
validates any manifest example against the schema it documents.

The `.md` upgrade guide (`v3.63.0-to-v3.64.0.md:211`) and the release-note
callout are both correct — only the config-changes manifest is wrong. That
split is itself worth noting: three copies of the same example, one wrong.

### D2 — the reference config carries no `persistent_crons` block

Plan 00384 Success Criterion 2 claims "the reference config carries the entry
so a new install can see it without gaining it." `.claude/hooks-daemon.yaml.example`
carries the **handler** entry (lines 618-620) but has only four top-level keys
— `version`, `daemon`, `handlers`, `pseudo_events`. There is no
`persistent_crons:` section, commented or otherwise.

Partly mitigated: the example config does not carry `plan_workflow` or
`worktree` either, so it is handler-focused by convention rather than a
complete reference. But the criterion as written is not met, and combined with
D1 it means a client's two discovery routes are "a section absent from the
reference config" and "an example that fails to load."

### D3 — the handler is untagged, contradicting shipped material

`v3.64.0.yaml:419` describes the handler as "PLANNING tagged". Checked at
runtime: `tags=[]`. Of twenty SessionStart handlers, only this one and
`tool_disable_advisor` are untagged.

This has a concrete consequence, not just a doc mismatch. Tags feed
`config_optimisation/areas.py::area_for`, which buckets handlers in the
config-optimisation checklist:

```
untagged session_start  -> "Session, environment & daemon"
planning session_start  -> "Plan & documentation workflow"
```

So the handler is filed under the wrong area in the checklist an operator
reads when tuning their config.

---

## 5. Existing CLI surface — what a job runner could reuse

**There is no `hooks-daemon run-job <ID>` and nothing resembling it.** The word
`cron` does not appear anywhere in
`/workspace/src/claude_code_hooks_daemon/daemon/cli.py` (9,117 lines, ~90
subcommands). There is no way to list, run, validate or record a declared job
from the CLI.

What exists and is directly reusable:

**Command registration** — `/workspace/src/claude_code_hooks_daemon/daemon/cli.py`.
One `cmd_<verb>(args: argparse.Namespace) -> int` function per verb;
`subparsers.add_parser(...)` + `.set_defaults(func=cmd_<verb>)`; dispatch is
a single `args.func(args)` at the tail. Adding a verb is mechanical.

**Project-root resolution** — same file:

- `apply_global_project_root(args)` (line 203) — lets `bin/hooks-daemon`'s
  pre-subcommand `--project-root` anchor survive the subparser.
- `get_project_path(override)` (line 153) — strict: insists on a git remote
  and loadable config, `SystemExit`s otherwise. Right for daemon-talking verbs.
- `resolve_tree_root(args)` (line 227) — lenient, returns `None` instead of
  exiting. Right for a verb that only reads a directory.
- `_daemon_untracked_dir(project_root)` (line 1935) — resolves the state
  directory across self-install and client layouts. **Any job-run ledger
  belongs here.**

**The closest existing prior art for a job catalogue** —
`/workspace/src/claude_code_hooks_daemon/daemon/housekeeping.py` +
`cmd_housekeeping` (cli.py:6473). A frozen-dataclass step registry
(`HousekeepingStep`: `name`, `purpose`, `cli_argv`, `via_skill`, `mutates`,
`confirmation_required`, `restarts_daemon`), an ordered `HOUSEKEEPING_STEPS`
tuple, `plan_pass(apply=[...])` returning dispositions, and
`render_procedure()` that emits a procedure for the agent to execute. The
module is pure data and pure functions — **it runs nothing**. `--list` prints
the catalogue; `--apply <step>` releases a HELD step. If a job system needs a
"declare jobs, render what to run, gate the mutating ones" shape, this is it,
already built and already dogfooded by two entry points
(`idle_housekeeping_advisory` names the same steps).

**Last-run state / run ledger patterns**:

- `/workspace/src/claude_code_hooks_daemon/config_optimisation/state.py` —
  `record_run(path, version)` / `load_state(path)`, a JSON sidecar under the
  daemon untracked dir; corrupt or missing reads as "never run"; write
  failures logged and swallowed. Driven by
  `cmd_record_config_optimisation_run` (cli.py:5109), which exists precisely
  so a skill does not hand-write the state file. **This is the closest
  existing model for "record that a job ran", and it already has a CLI verb.**
- `/workspace/src/claude_code_hooks_daemon/utils/cron_cadence.py` — atomic
  session-scoped JSON state (`CadenceState`, `write_cadence`, temp-file swap,
  fail-open on every path, capped backoff via `MAX_CADENCE_HOURS`).
- `/workspace/src/claude_code_hooks_daemon/utils/blockage_marker.py` —
  session-scoped marker with expiry.
- Append-only JSONL ledgers already in use: `stop-events.jsonl`,
  `background-processes.jsonl`, `budget-exhaustion-events.jsonl`.

**Background-work reaping** —
`/workspace/src/claude_code_hooks_daemon/daemon/background_harvester.py` +
`cmd_harvest_background` (cli.py:3652), driven by a watchdog cron whose prompt
is agent-composed.

**Output conventions** — `print()` to stdout; errors to `stderr` prefixed
`ERROR:`; exit `0` on success (a *finding* is not an error — see
`cmd_optimise_checklist`), `2` for bad args or unreadable config; a
`--format json` / `--json` flag alongside the text renderer, with a
`report_as_json()` next to `render_report()`.

---

## 6. The hard constraint, stated plainly

Claude Code crons live in session memory. `CronCreate`'s `durable` parameter is
documented as having no effect. Recurring jobs auto-expire after 7 days. The
daemon cannot read that memory, cannot create a cron, cannot delete one, and
cannot observe one except by seeing its tick arrive as a prompt.

### What a cron-driven job system CAN guarantee

- **That the declaration is durable and correct.** It lives in tracked config,
  is schema-validated at load, and cannot silently carry a malformed schedule
  or a duplicate id.
- **That the declaration is presented at every session start**, in full, with
  the exact schedule and prompt needed to re-create it.
- **That a delivered tick is recognisable.** The daemon authors or holds the
  prompt text for daemon-caused crons, so it can classify an arriving tick
  exactly — this already happens for the failsafe cron and could be extended
  to every declared job at low cost.
- **Therefore: that a tick which arrived can be recorded, counted, rate-limited
  or stood down.** Everything downstream of "the tick reached the model" is
  within reach today.

### What it CANNOT guarantee

- **That a declared cron exists.** Creation depends on an agent reading an
  advisory and acting on it. No confirmation returns to the daemon.
- **That a cron will fire.** It fires only while the REPL is idle; it cannot
  interrupt active work; it dies with the session; it expires after 7 days.
- **That a job is not duplicated.** Runtime dedupe is an instruction, not a
  mechanism.
- **That a tick accomplished anything.** Nothing observes the tick's outcome,
  and in the `issue-sdlc` design a no-op is by definition a success.
- **That absence is detected.** The symptom of a cron that was never created is
  silence, and silence is exactly what a healthy no-op also looks like.

### What this bounds

**A job system built on Claude Code crons cannot be a scheduler. It can only
be a declaration plus a best-effort delivery channel, with the daemon as a
recorder of what arrived.** Any guarantee phrased "this job runs every hour"
is unsupportable. Guarantees phrased "this job is declared, and here is every
tick that was observed, with what it reported" are supportable — and would
require building the missing half: a tick recogniser keyed on the declared
prompts, a run ledger under the daemon untracked dir, and a CLI verb to read
it. Every primitive for that already exists in the tree (§5); none of them is
wired to `persistent_crons`.

**One consequence worth stating before any design work.** Two of the three
crons live in this repository's sessions are *not* declared — the failsafe
recovery cron (Plan 00394, open) and the background watchdog (agent-composed
by design). A job system scoped to `persistent_crons` would cover one of
three. Whether the other two get declared is the open owner decision in
Plans 00394 and 00388, and it is upstream of the job-system design rather
than a detail inside it.
