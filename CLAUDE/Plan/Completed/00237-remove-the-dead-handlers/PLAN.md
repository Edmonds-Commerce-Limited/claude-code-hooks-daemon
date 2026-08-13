# Plan 00237: Remove The Dead Handlers

**Status**: Complete
**Created**: 2026-08-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

[Plan 00234](../00234-handler-value-audit/PLAN.md) audited all 100 handlers and
returned 10 REMOVE and 2 MERGE verdicts.
[Plan 00236](../Completed/00236-fix-what-is-broken-pass/PLAN.md) took the
repair slice; this plan takes the deletions.

Removal has a client-facing cost that repair does not: a handler name that
vanishes from the daemon while still present in a client's
`.claude/hooks-daemon.yaml` is an unknown key, and handler-name validation is a
hard error by design. Plan 00233 built `RETIRED_HANDLERS` for exactly this — a
deliberate map of retired config key to the reason it went — so every removal
here must land its registry entry in the same commit, plus a `config-changes`
manifest entry so upgrading projects are told rather than left to discover it.

The verdicts split into two very different risk classes, and the phases follow
that split rather than the audit's cohort order. Five handlers **cannot fire or
have no consumer** — deleting them changes no observable behaviour, and the
audit's evidence for each is a structural fact (`matches()` returns a hardcoded
False; the directory has no producer). Five **do fire** and removing them
changes what reaches the agent's context, so each needs its duty accounted for
before it goes. The two MERGE verdicts are last because one carries a live side
effect that must be relocated first.

## Goals

- Delete the 10 REMOVE handlers, each with a `RETIRED_HANDLERS` entry and a
  `config-changes` manifest row landed in the same commit
- Fold the 2 MERGE handlers into `plan_qa`, relocating `validate_plan_number`'s
  counter-advance side effect before its handler goes
- Resolve the shadowed Stop advisories Plan 00236 identified — remove or
  re-prioritise, but not leave registered-and-unreachable
- Delete what each removed handler took with it (dead readers, state files,
  cache modules) rather than leaving orphans behind
- Verify in a real client install, not only in self-install mode

## Non-Goals

- The cost-tuning FIX verdicts (status-line TTLs, `git_context_injector`
  payload) — deferred to a later pass with real verdict-log data behind it
- Re-auditing the KEEP verdicts
- Removing any handler whose duty is real but whose implementation is poor —
  that is a repair, and repairs were Plan 00236's job

## Tasks

### Phase 1: The five that cannot fire or have no consumer

Deleting these changes no observable behaviour. Each verdict rests on a
structural fact, re-verified here before deletion rather than taken on trust.

- [x] ✅ **Task 1.1**: `usage_tracking` (Status) — `matches()` has returned a
  hardcoded False since commit 71593163; config claims `enabled: true`, which
  is a lie about runtime state. Takes `stats_cache_reader.py` with it
- [x] ✅ **Task 1.2**: `cleanup` (SessionEnd) — reaps `temp/hooks/`, which
  nothing in the codebase writes and which does not exist on disk. The
  Plan 00233 shape exactly
- [x] ✅ **Task 1.3**: `yolo_container_detection` (SessionStart) —
  `show_on_session_start` defaults False independently of `enabled: true`, so
  it is silent in every install
- [x] ✅ **Task 1.4**: `subagent_completion_logger` — writer with zero readers
  repo-wide; superseded in intent by the verdict log. 3.4 MB live
- [x] ✅ **Task 1.5**: `notification_logger` — same class, same corroboration
- [x] ✅ **Task 1.6**: Checkpoint commit with registry + manifest entries
- [x] ✅ **Task 1.7**: DBF — guard the registry/manifest seam. Two checks in
  `tests/integration/test_config_migrations_integration.py`: every handler a
  manifest documents as `removed` must carry a `RETIRED_HANDLERS` entry, and
  every staged manifest must match the `v*.yaml` glob the release step moves.
  Both found real pre-existing bugs on first run — see Decision 2 and 3

### Phase 2: The five that DO fire

Each of these reaches the agent's context today, so the question is not "does
it run" but "does its duty survive elsewhere". Record that answer per handler.

**Correction to that framing, established by live probe**: two of the five do
NOT fire on an ordinary stop. A Stop dispatched through the live daemon with a
valid `STOPPING BECAUSE:` transcript returns `{}` — no advisory context at all
— because `auto_continue_stop` (priority 10, `terminal=True`) matched and broke
the chain. So `task_completion_checker` (20) and the Stop leg of
`remind_prompt_library` (100) are shadowed exactly as Plan 00236's guard
describes, and belong to Phase 1's "cannot fire" class rather than this one.
They remain reachable only in `auto_continue_stop`'s two narrow non-matching
cases (confirmed re-entry, AskUserQuestion turn), and `remind_prompt_library`
also runs on SubagentStop, where no terminal handler precedes it.

- [x] ✅ **Task 2.1**: `task_tdd_advisor` — its ~30-line payload is already
  resident via CLAUDE.md's eager `@`-imports, and its closing step told the
  agent to run a QA script `enforce_llm_qa` denies
- [x] ✅ **Task 2.2**: `remind_prompt_library` — points at an npm script and a
  `CLAUDE/PromptLibrary/` directory that do not exist, with no existence
  gating (both verified absent; `matches()` is `return True`). Removing it
  empties SubagentStop, so that section is now `subagent_stop: {}` on the
  same footing as `session_end` and `notification`
- [x] ✅ **Task 2.3**: `task_completion_checker` — static checklist whose
  substance `auto_continue_stop` *enforces* rather than reminds, and which the
  live probe showed is not even reached on an ordinary stop
- [x] ✅ **Task 2.4**: `post_clear_auto_execute` — its originating plan is
  Cancelled as unachievable and rates the surviving code marginal, and its
  once-per-session contract is implemented with a single `_last_session_id`
  slot, which cannot hold per-session state in a daemon that parallel sessions
  deliberately SHARE. `scripts/qa/check_handler_reference.py` cited it twice
  as its worked example; both comments repointed rather than left dangling
- [x] ✅ **Task 2.5**: `bash_error_detector` — REMOVE, decided on measurement
  (Decision 4): 274 fires, 45% of all behavioural handler activity,
  `allow=274`. A rate limit would only reduce the volume of an advisory whose
  content is "look at the thing you are looking at"
- [x] ✅ **Task 2.6**: Checkpoint commit — `f782d0a2`

### Phase 3: The shadowed Stop advisories

Decided: remove the Stop registrations. Re-prioritising below 10 is not a real
option — that band is the safety range, and putting an advisory ahead of a
terminal safety handler to win a race is the wrong fix for the wrong problem.
The `nitpick` pseudo-event already carries both detectors on a `stop:1/1`
trigger, so nothing is lost.

This is a DEPENDENCY INVERSION, not a deletion. Three times over, the leg that
cannot run holds what matters: the `get_claude_md()` bodies, and — via
`from ...handlers.stop.hedging_language_detector import ...` at the top of each
nitpick module — the compiled pattern sets themselves, under a comment calling
the Stop handler the "single source of truth". The live leg holds only the loop.

- [x] ✅ **Task 3.1**: MOVE the pattern constants and the `get_claude_md()`
  bodies into the nitpick modules, so the running code owns its own
  definitions. Deleting first would break the working detectors at import
  time. Flip the exemption entries in `test_claude_md_guidance_coverage.py` in
  the same edit
- [x] ✅ **Task 3.1b**: Carry `PREMATURE_STOP_PATTERNS` across too and wire it
  into the nitpick `_CATEGORY_PATTERNS`. The nitpick leg imports FOUR of the
  five dismissive sets — premature-halt language ("natural checkpoint",
  "pausing here") has never been detected by the leg that runs. This is a
  behaviour CHANGE, not a refactor, so it needs its own RED test rather than
  riding on the existing ones. RED confirmed failing before the wiring landed
- [x] ✅ **Task 3.2**: Delete `stop/hedging_language_detector.py` and
  `stop/dismissive_language_detector.py`, their tests, constants, priorities
  and config entries. This empties `stop:` down to `auto_continue_stop` alone
- [x] ✅ **Task 3.3**: Rewrite the Plan 00236 shadowing guard to prove the
  hazard with a SYNTHETIC probe handler rather than these two. The hazard —
  any Stop handler above priority 10 is unreachable — outlives the specific
  handlers, so a guard anchored to them dies with them. Never silence it.
  Gained a third test in the rewrite: a probe BELOW priority 10 DOES run, so
  the guard now distinguishes "shadowed by ordering" from "Stop dispatch is
  broken" — two very different bugs the old two-test shape could not separate
- [x] ✅ **Task 3.5**: DOGFOODING BUG found by the move (see JOURNAL 21:12).
  The injector built its handler list from `EventRouter`'s chains only, so it
  has never seen a pseudo-event handler — moving the guidance onto the nitpick
  pair silently DELETED both sections from `CLAUDE.md`, auto-committed. Fixed
  with `PseudoEventDispatcher.all_handlers()`, and guarded by
  `TestGuidanceActuallyReachesClaudeMd`: "returns guidance" and "guidance
  reaches the agent" are different properties and only the first was checked.
  `check_repo_hygiene`'s `orphaned-handler-guidance` covers the opposite
  direction; this is the missing half
- [x] ✅ **Task 3.6**: Pseudo-event handlers are invisible to THREE remaining
  enumeration surfaces — measured by running each, after reading the code got
  the mechanism wrong twice (JOURNAL 21:38, 21:46):
  - `get_handlers()` (live `handlers` IPC action) — walks router chains
  - `generate-docs` — `EVENT_TYPE_MAPPING` × `config.handlers`, and nitpick
    lives under `pseudo_events:`, so `.claude/HOOKS-DAEMON.md` has no Nitpick
    section at all
  - `generate-playbook` — `EVENT_TYPE_MAPPING` × module path, so both nitpick
    handlers' declared `get_acceptance_tests()` have never appeared in the
    playbook the BLOCKING release acceptance gate is generated from
    All pre-existing, none caused by this plan, none covered by the Task 3.5
    guard (which checks CLAUDE.md markers, not these tables). The playbook one
    is the most serious: a handler can ship indefinitely with acceptance tests
    that are never run and never reported as missing.
    Fixed by extracting `pseudo_events/registry.py` as the single source of
    truth (Decision 7) and reading it from all four surfaces — verified by
    RUNNING each command, playbook 0 → 8 mentions
- [x] ✅ **Task 3.7**: A FOURTH dead thing, found while wiring 3.6's filter:
  `PseudoEventConfig.handler_configs` was parsed and read by nothing, so
  `enabled: false` on a nitpick handler silently did nothing — no warning, no
  error, the handler kept firing. Every reader in `src/` was checked; there was
  no consumer. Same defect class as the whole plan. Dispatch and every
  reporting surface now filter through the shared registry, so the flag means
  one thing everywhere. Also fixed: the filter must key on the CONFIG FILE
  spelling `dismissive_language`, not `HandlerID.config_key`
  `dismissive_language_nitpick` — these handlers carry two
- [x] ✅ **Task 3.4**: Checkpoint commit

### Phase 3b: The shadowing hazard is LIVE in this repo

- [x] ✅ **Task 3.8**: `ReleaseBlockerHandler` (`.claude/project-handlers/stop/`)
  had never fired. Two bugs, the first hiding the second: priority 12 above the
  terminal `auto_continue_stop` at 10, and a bare `git status` inheriting the
  daemon's cwd of `/`. Both fixed and live-verified in both directions
  (JOURNAL 23:20, 23:45)
- [x] ✅ **Task 3.9**: DBF — the Task 3.3 guard used a synthetic probe and never
  asked whether THIS project had fallen into the trap, so it could not have
  caught 3.8. `TestThisProjectHasNotFallenIntoTheTrap` now walks the real
  registered Stop chain (config + project handlers) BEHAVIOURALLY, plus a
  vacuity companion (JOURNAL 23:45)

### Phase 4: The two MERGE verdicts

The two are NOT the same shape, and treating them as one bullet hid that
(JOURNAL 22:50, 22:58). Do them in the order 4.3 → 4.1 → 4.2: the advisor is a
clean deletion against a strict superset, while `validate_plan_number` carries
a counter-advancing side effect whose replacement (`counter-sanity`) is a
Stage 2 COMMIT check that only READS the counter. Delete the handler first and
the counter stops advancing for hand-created folders, after which
`counter-sanity` correctly blocks commits for drift the deletion itself caused.

- [x] ✅ **Task 4.1**: Relocate `validate_plan_number`'s counter-advance side
  effect BEFORE deleting the handler — the counter has three non-redundant
  writers and this was the DIRECT path (JOURNAL 21:58 → 22:04). Now
  `record_new_plan_document()` in `handlers/utils/plan_numbering.py`, called
  from `plan_qa_edit` on CREATION only, carrying the sanity WINDOW with it —
  see [DECISIONS.md](DECISIONS.md) Decision 8 for why the window is
  load-bearing. Live-proven both ways (JOURNAL 01:50)
- [x] ✅ **Task 4.2**: Fold `validate_plan_number` into `plan_qa`
  (`counter-sanity` / `no-new-collisions` are the real check; it never denied).
  Handler + tests deleted, registry and manifest entries added, stale
  `error_hiding_exclusions.json` sanction repointed (JOURNAL 01:50)
- [x] ✅ **Task 4.3**: Fold `plan_completion_advisor` into `plan_qa`.
  `terminal-placement-hint` is a strict SUPERSET — same trigger, same three
  steps, and it also handles Cancelled/Superseded with the configured archive
  directory, which the handler got wrong. Clean deletion, live-proven, and both
  handlers ship enabled so no default install loses the reminder (JOURNAL 00:40)

### Phase 5: Verification

- [x] ✅ **Task 5.1**: Config template, `.claude/hooks-daemon.yaml`, and
  generated docs regenerated. Also swept the user-facing docs for handlers
  removed EARLIER in this plan and found `LLM-INSTALL.md` still telling users
  to enable `bash_error_detector` in two places
- [x] ✅ **Task 5.2**: Full QA — 21/21, 12,183 tests, coverage 95.2%
- [x] ✅ **Task 5.3**: Daemon restart verified RUNNING, zero errors in the log
- [x] ✅ **Task 5.4**: Client-mode verification, both directions — a real
  client install (production installer, own venv/socket/hostname) with all 21
  retired keys reports `Daemon: HEALTHY` (exit 0); adding ONE bogus name
  reports `Daemon: DEGRADED` (exit 1). The paired negative is what makes the
  first result mean anything: `status`, `check` and `logs` show nothing in
  EITHER case, so checking those alone — which is what I did first — would
  have been a vacuous pass (JOURNAL 03:10)
- [x] ✅ **Task 5.5**: Commit and push

## Technical Decisions

Recorded in [DECISIONS.md](DECISIONS.md) — seven so far: empty event
sections, the six pre-registry retirements the guard surfaced, the stranded
manifest, `bash_error_detector` removed rather than narrowed, Phase 3 as
a dependency inversion, fixing the CLAUDE.md injector rather than routing
the moved guidance around it, and one shared source of truth for pseudo-event
handlers rather than three independent patches.

## Dependencies

- Depends on: [Plan 00234](../00234-handler-value-audit/PLAN.md) (the verdicts)
- Depends on: Plan 00233 (Complete) for `RETIRED_HANDLERS`
- Related: [Plan 00236](../Completed/00236-fix-what-is-broken-pass/PLAN.md),
  whose Decision 1 identified the shadowed Stop advisories in Phase 3

## Success Criteria

- [x] Every removed handler has a `RETIRED_HANDLERS` entry and a
  `config-changes` manifest row — 21 retired entries, 15 manifest removals,
  zero overlap with the 93 live `HandlerID` config keys. Enforced by
  `TestRemovedHandlersAreRetired`, which anchors to the MANIFEST rather than a
  hand-maintained list, so future removals are covered without anyone
  remembering to
- [x] A client config naming every retired handler starts cleanly, verified in
  a real client install rather than inferred from self-install mode — HEALTHY
  with all 21, DEGRADED with one bogus name added, so the pass is not vacuous
- [x] Nothing removed leaves an orphan behind — dead readers, state files and
  cache modules go with their handler. Also caught: a QA sanctioned-exception
  entry pointing at a deleted file, and a compiled regex referenced nowhere
- [x] Each Phase 2 removal records where its duty survives, or that it had none
- [x] Full QA passes; daemon restarts RUNNING — 21/21, 12,183 tests, 95.2%

## Delivery & Milestones

- Phase 1 delivered at `d46c3381` and `03eec8f0` — three handlers that could
  not fire, plus the guard that found two real bugs
- Phase 2 delivered at `f782d0a2` — five that fire and two that turned out not to
- Phase 3 delivered at `b8aa578d` and `a232db12` — the shadowed Stop detectors,
  their guidance, and the pseudo-event handlers that were invisible to every
  enumeration surface
- Phase 3b delivered at `c5584c67` — this repo's own release guard, which had
  never fired, and a guard over the REAL registered Stop chain
- Phase 4 delivered at `17131953` — the two MERGE verdicts, with the plan
  counter's writer relocated before its handler was deleted
