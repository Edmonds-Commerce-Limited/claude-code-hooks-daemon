# Decision: what survives degraded mode

Supporting document for Plan 00412, run `2026-001`, check `D-SEC`. Closes the
owner gate opened by
[DECISION-degraded-mode-guard-surface.md](DECISION-degraded-mode-guard-surface.md).
Decision only — nothing here was implemented, and the implementation work the
ruling requires is listed at the end as unbuilt.

## The ruling

**DECISION: endorse "B, then A" — with both narrowed to what the code actually
does, and one item added ahead of B because it is the cheapest link in the
chain and the request document did not see it.**

1. **First, before B: make the drift reporters speak on the malformed case.**
   `compare_guard_config` returns `DriftReport(parse_failed=True)` when either
   document does not parse (`utils/guard_config_drift.py:184-185`), and
   `has_drift` is False for that report (`:79-81`), so both consumers render
   nothing (`handlers/session_start/guard_config_drift.py:177-178`,
   `handlers/pre_tool_use/guard_config_commit_gate.py:164`). The two handlers
   built by this plan to watch this file are silent on precisely the line that
   degrades the daemon. That is a one-line-of-output change with no behaviour
   change, and it is the finding restated.
2. **B, corrected.** Half of B already exists and is untested: a `StatusLine`
   event in degraded mode is answered with `HookResult.configuration_error`,
   and the `Status` wire form joins `context` into the rendered line
   (`core/hook_result.py:571-584`), so the status line *is* the degraded
   warning today. What B still has to build is the content: the advisory must
   name the configured, enabled, deny-capable `PreToolUse` handlers that are
   NOT running (count and names — today it says only "handlers may not be
   configured correctly", `hook_result.py:1169-1170`), and it must say whether
   the COMMITTED config validates. That second line is the only
   typo-versus-deliberate discriminator the system can honestly offer, and it
   turns the remediation from "fix the configuration" into "restore the file
   from HEAD".
3. **A, under Plan 00304's own admission test.** A handler joins the safety
   net only if it is constructed cold and its verdict is invariant under every
   valid `options:` block. The request document's list fails that test in
   three of four places (evidence below). Admitted: `curl_pipe_shell` and
   `dangerous_permissions` (the document's `chmod_world_writable` is a rule
   name, not a handler; the handler is `dangerous_permissions`,
   `constants/handlers.py:94-96`). Not admitted as listed: `sed_blocker`,
   `secret_file_guard`, `project_containment`. The Detector that keeps the
   list honest is required; its behaviour is specified below and its home is
   deferred to the sibling ruling.
4. **C is not attempted now — but for different reasons than the document
   gives.** D is rejected.

## Evidence

### The chain, checked link by link

**Link 1 — a config-validation failure fails open: TRUE.**
`daemon/controller.py:915-926`: when `_degraded` is set, `process_event`
returns before the router for every event type; only `_degraded_mode_safety_net`
(`:794-841`) runs first, and it constructs exactly one handler,
`DestructiveGitHandler`, cold (`:817-822`). `_degraded` is set at startup only
(`initialise` → `_validate_config`, `:339`, `:757-791`): a YAML parse failure
raises inside `ConfigLoader.load` and lands in the `except` (`:783-791`); a
parseable file with an unknown handler name (`config/validator.py:474-507`), a
non-boolean `enabled`, or an out-of-range `priority` (`:526-550`) lands in the
error list. Nothing re-reads the file while the daemon runs, so a malformed
write bites at the next restart, not at the write.

One thing the document's table understates: the early return is for **every**
event, so it is not only the five `PreToolUse` guards named there. `Stop` and
`SubagentStop` teeth (the cron enforcers, the stop-explanation block),
`PostToolUse` linting and `SessionStart` directives are all off too. Plan
00416's teeth do not survive degraded mode either.

**Link 2 — nothing guards writes to the config: true when written, overtaken
since, and imprecise in a way that matters.** The document is dated 15 Sep
(`728362ca`). On 16 Sep this plan shipped two handlers that watch exactly this
file: `guard_config_drift` at `SessionStart` (`8423f48b`, enabled at
`.claude/hooks-daemon.yaml:736`) and `guard_config_commit_gate` at commit time
(`4e57549b`, enabled at `:590`). Three qualifications:

- Neither **denies**. Both are report-only by measured design
  (`guard_config_commit_gate.py:9-22`: an 80% historical false-alarm rate for
  any denying variant). So "nothing guards" is still true if "guard" means
  deny.
- Both run **inside the chain that degraded mode skips**. Once the daemon has
  restarted on the broken file, the reporters that would name the breakage do
  not execute (link 1). They are useful only in the window between the write
  and the restart.
- Both are **silent in that window on the malformed case**, per ruling item 1.
  They name `enabled: false`, a removed block and a widened exclusion
  (`DriftKind`, `utils/guard_config_drift.py:40-51`); an unparseable document
  produces an empty report on purpose, so that "an advisory that fires wrongly
  every session is one that gets switched off" (`:173-175`). That reasoning
  holds for a *no-baseline* case and not for a *parse-failed* one: a working
  tree that does not parse against a HEAD that does is not a false alarm.

Also relevant to option C: a `Write`/`Edit` guard on this path would not see a
Bash write. This repository's own CLAUDE.md states the rule ("a `>`, `>>`,
`tee` or a `cat <<EOF` heredoc reaches disk unexamined") and it applies to the
config file as much as to any other.

**Link 3 — every deny message names the key that disables the handler: TRUE,
but it belongs to a different route than link 1.** The footer is appended to
every `DENY`/`ASK` by `inject_config_key_footer` (`core/router.py:36-72`). What
it names is the `enabled: false` key. Setting that key is a **valid**
configuration: the daemon does not degrade, the other guards keep running, and
`guard_config_drift` reports it by name as `DISABLED`
(`utils/guard_config_drift.py:140-148`). The malformed-line route of link 1
needs no map — any syntax error in any line does it. So the composition
sentence ("one malformed line reduces the guard set to one handler, nothing
prevents that line being written, and the deny messages are a map of which
line to write") joins two routes that do not meet: the mapped route is
observed and bounded to one handler; the unmapped route is unobserved and
takes everything. The property the document names — that a typo and a
deliberate weakening are reported the same way — is true of the second route
only, and it is the second route that items 1 and 2 of the ruling address.

### What degraded mode looks like today, against "looks healthy"

The recommendation says "a degraded guard surface currently looks like a
healthy one". That overstates it, and the overstatement changes what B must
build:

- Every hook response carries `configuration_error`'s context
  (`hook_result.py:1168-1195`): on `SessionStart` as a `systemMessage`, on
  `PreToolUse` as `additionalContext`, and on `StatusLine` as the rendered
  line itself (`:571-584`). The state is loud on every surface an agent
  reads.
- `status`, `check` and `config-validate` all report the degraded verdict
  (Plan 00304 Phase 3; `controller.py:1114-1127`;
  `tests/unit/daemon/test_cli_degraded_mode_visibility.py`).
- What is **missing** is content, not volume: the advisory does not say which
  handlers are off, and it does not say whether the committed file is fine.
  Those two lines are B.
- What is **untested** is the status line: `test_controller_degraded_mode.py`
  exercises `PRE_TOOL_USE` and `POST_TOOL_USE` only (`:217-233`). The status
  line's behaviour is a consequence of `to_json`'s `Status` branch, not of any
  decision anyone made about degraded mode; a test pins it so a later change
  to the `Status` wire form cannot silently remove it.

### Option A's list, checked against Plan 00304's admission test

Plan 00304 admitted `DestructiveGitHandler` because it "hard-codes its own
patterns and takes no config", and rejected a general widening because
"'config-independent' is not a property the existing architecture tracks
per-handler" (`Completed/00304-.../PLAN.md:119-124`). The safety net runs a
handler with **no options at all** — so any option that can change a verdict
means the cold handler enforces something the project did not configure.

| Handler                 | Option that changes the verdict                                                                                                                                | Admitted |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| `destructive_git`       | none                                                                                                                                                           | already  |
| `curl_pipe_shell`       | none                                                                                                                                                           | yes      |
| `dangerous_permissions` | none                                                                                                                                                           | yes      |
| `sed_blocker`           | blocking mode `STRICT` vs `DIRECT_INVOCATION_ONLY` (`sed_blocker.py:45-61`): cold `STRICT` denies a `Write` of a sed-bearing script the project allowed        | no       |
| `secret_file_guard`     | glob extend/replace, `allowed_consumers`, `exclude_paths` (`secret_file_guard.py:142`, `:327`, `:348`): cold defaults under-protect custom globs AND over-deny | no       |
| `project_containment`   | `allowed_external_paths` (`project_containment.py:586`)                                                                                                        | no       |

`ProjectContext` is initialised before validation (`controller.py:260` versus
`:339`), so a handler's need for the project root is **not** a barrier; only
its options are. The test is verdict-invariance, not "has no config block".

The route that would cover the three excluded handlers is a different design:
run a handler with its own `options:` taken from the parsed document when that
block is a dict, even though the document as a whole failed validation. That
makes "degraded" a per-handler state rather than a daemon state, which Plan
00304 explicitly scoped out (Non-Goals, `:50-56`). It is the named follow-on,
it needs its own decision, and it is not made here.

### Why C is not attempted now — the document's reason and the real ones

The document's objection is the bootstrap problem: "a broken config cannot be
fixed if fixing it requires a working daemon". The code does not have that
problem. A `PreToolUse` guard runs only while the daemon is healthy; once the
daemon has degraded on a broken file the guard is off (link 1), so the fix
write passes. Fail-open **is** the escape hatch, and it needs no designing.

The reasons C is still not the next move are these:

- **The guard cannot see the writes that matter most.** A `Write`/`Edit`
  guard is bypassed by every Bash write, as the CLAUDE.md rule states. The
  one file where that gap is the whole question is this one.
- **Validator-version skew.** The RUNNING daemon's validator would judge the
  file. After a code upgrade and before a restart, a config naming a handler
  the new code ships is "Unknown handler" to the old validator
  (`validator.py:474-507`). The `RETIRED_HANDLERS` carve-out at `:478-486` is
  the same skew in the other direction, and Plan 00233 already paid for it
  once — "the daemon into degraded mode every session for a decision that was
  ours, not theirs". A denying C would block the documented upgrade path at
  the step where the config is edited.
- **The advisory form of C already exists.** `config-validate` (`cli.py:3300`)
  agrees with the daemon's own verdict since Plan 00304 Task 3.2. "Run
  `config-validate` before `restart`" is a documentation line, not a handler.

If C is ever built it should validate against the code **on disk**, not the
code in memory, and it should be `ASK`, not `DENY`. Neither is designed here.

### Why D is rejected

The precedent is the php-qa-ci canary (`Completed/00304-.../PLAN.md:12-19`):
the degrading value was written by an OLDER daemon's own template, not by a
typo and not by an adversary. Ordinary drift reached degraded mode on a real
client with no denial on the wire. Accepting that as documented is accepting
the case that has already happened.

## What it costs, and who bears it

**Item 1 (reporters speak on parse failure).** No verdict changes anywhere.
An installing project sees one new advisory line, at session start or at
commit, only when its working-tree config fails to parse while HEAD's parses.
A project whose committed config is itself unparseable is already degraded and
the handler does not run, so the line cannot fire wrongly every session.

**Item 2 (B).** No verdict changes anywhere. In degraded mode the advisory
grows by a list of handler names and one line about HEAD. The status line
shows what it shows today; the test only pins it. Zero cost to a healthy
project — which is the property the request document valued B for, and it
survives the correction.

**Item 3 (A, narrowed).** Bounded to degraded mode. Where today `curl … | sh`
and `chmod 777` are ALLOWED with a warning, they are DENIED with the same
degraded note `destructive_git` already appends (`controller.py:830-841`).
Neither handler has an option, so no project configured them to permit those
commands. The one behaviour change: a project that set `enabled: false` on
either handler sees a deny it turned off — exactly what is already true of
`destructive_git` under Plan 00304, because the net ignores the config
entirely. That is the precedent's cost, extended to two handlers with the same
shape; honouring `enabled: false` from the parsed document is the same
follow-on design named above.

**Not covered by this ruling, and said plainly.** `secret_file_guard` stays
off in degraded mode. Plan 00272 recorded "No agent escape hatch — this block
is the only lift, and it is a human's edit" (`.claude/hooks-daemon.yaml:278-281`);
degraded mode is an agent-reachable escape hatch for it. That contradiction is
real, it is recorded here, and it is resolved by the per-handler follow-on, not
by a cold-default net that would protect this repository's default globs and
silently not protect a client's replaced ones.

## The Detector — required behaviour, home deferred

The sibling ruling decides whether the Detector is a `scripts/qa/` Detector or
a test. Whatever it is, it must:

1. Fail when a `PreToolUse` handler that satisfies the admission test —
   constructible with no arguments and verdict-invariant under its `options:`
   surface — is absent from `_degraded_mode_safety_net`.
2. Fail when a handler that is IN the net has acquired an option, so the list
   cannot keep a member that no longer qualifies.
3. Read the admission property from a **declaration on the handler**, not
   from inference. Plan 00304 is right that the architecture does not track
   config-independence; the Detector cannot infer verdict-invariance from
   source, so the handler must declare it (a tag or class attribute is the
   natural shape) and the Detector compares the declared set with the net's
   set and fails on any asymmetry in either direction.
4. Fail when a declared handler's `__init__` requires arguments — the net
   constructs cold, and a declaration that cannot be honoured is worse than
   none.

The list is currently two handlers plus the incumbent. The Detector exists so
it can be three without anyone remembering to look.

## The strongest argument against, stated fairly

Against narrowing A: `secret_file_guard` is the first row of the request
document's table, and it is first for a reason — a protected file's contents
read into context is irreversible where a `curl | sh` at least leaves a
process to notice. Excluding it leaves the most consequential guard unprotected
in exactly the state this decision exists to address, on a technicality about
options.

The rebuttal is that the technicality is the canary. A cold
`secret_file_guard` runs the daemon's default globs, not the project's. A
project that REPLACED the globs gets no protection for its own protected paths
while believing the net covers it; a project with `allowed_consumers` gets its
configured consumer denied. A net that protects the daemon repository well and
a client badly is Plan 00304's canary in reverse, and it would be discovered
the same way. The honest cover for `secret_file_guard` is the per-handler
follow-on, which reads the project's own block; it is named, it is unbuilt,
and it is the next decision, not this one.

## Human gate?

**None for items 1 to 3.** Plan 00304's owner ruling — fail-open, keep the
daemon running, a small explicitly config-independent net — stands, and this
ruling is its consequence: the net grows by two handlers that pass the same
test the incumbent passed, and the advisory says what it already implied. No
installing project's healthy-mode surface changes at all; the degraded-mode
change is two denies that no configuration could have permitted. That is a
determinate reading of `controller.py`, `hook_result.py` and the two handlers'
option surfaces, not a risk appetite.

**Two things this ruling does not decide, and hands back:** the per-handler
follow-on (run a handler with its parsed `options:` while the document as a
whole is invalid, and honour `enabled: false` in the net), and any denying
form of C. Each changes what "degraded" means and each needs its own decision.

## Corrections to the request document, for the record

- "Nothing guards writes to the config": overtaken the next day by
  `guard_config_drift` and `guard_config_commit_gate`; both report rather
  than deny, both are silent on an unparseable working tree, both are off
  once the daemon has degraded.
- "A degraded guard surface currently looks like a healthy one": every hook
  response, the status line, `status`, `check` and `config-validate` all say
  DEGRADED. What is missing is *which* handlers and *whether HEAD is fine*.
- Option B's "surface it in the status line": already true as a consequence
  of the `Status` wire form; untested.
- Option A's `chmod_world_writable`: the handler is `dangerous_permissions`.
- Option A's `sed_blocker`, `secret_file_guard` "using default globs" and (by
  the table) `project_containment`: each has an option that changes its
  verdict, so none passes the test the precedent set.
- Option C's "bootstrap problem": not present in the code — fail-open is the
  escape hatch. The real obstacles are Bash-write blindness and
  validator-version skew.
- The blast radius table omits every non-`PreToolUse` tier; `Stop`-time teeth
  are off in degraded mode too.

## Implementation this ruling makes necessary — all unbuilt

1. `utils/guard_config_drift.py`: `has_drift` (or a sibling property) true on
   `parse_failed`; `_render` in both consumers emits a line naming the
   unparseable document and the `git checkout HEAD -- .claude/hooks-daemon.yaml`
   remediation already used for drift.
2. `HookResult.configuration_error` (or its caller in `controller.py`): the
   count and names of configured, enabled, deny-capable `PreToolUse` handlers
   not running, and whether `HEAD:.claude/hooks-daemon.yaml` validates.
3. A test in `tests/unit/daemon/test_controller_degraded_mode.py` that a
   `STATUS_LINE` event in degraded mode renders the degraded text.
4. `_degraded_mode_safety_net`: add `CurlPipeShellHandler` and
   `DangerousPermissionsHandler`, each with a test mirroring
   `test_degraded_mode_still_blocks_destructive_git`.
5. A declared config-independence property on those three handlers, and the
   Detector specified above, in the home the sibling ruling assigns.

With this recorded, check `D-SEC` of run `2026-001` is decided, and the plan's
remaining question on this finding is who builds items 1 to 5 and in which
task.
