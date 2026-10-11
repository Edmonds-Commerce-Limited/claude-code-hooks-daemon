# Ruling 3.2: PreToolUse during the venv build window

**Coordinator ruling (Fable-assisted), 2026-10-11.** Made under the owner's
standing guidance in
[00474 OWNER-RULINGS-261011.md](../../00474-niggles-ledger-seventeen/OWNER-RULINGS-261011.md)
("clear winners are decided by the coordinator, not put to the owner"; a hard
question may go to a `fable` sub-agent). It is recorded as the coordinator's
decision, never as the owner's. No code was changed in making it.

## Question

On a fresh checkout, the Plan 00456 self-heal builds the missing venv in the
background. The build outlasts a hook call by a wide margin (the detached
build's default bound is `VENV_BUILD_TIMEOUT_DEFAULT=900`,
`scripts/install/venv.sh:437`). While it runs, no daemon can answer, so no
guard judges any tool call. What should PreToolUse do in that window?

- **(A)** Wait on the build lock up to a bound, then proceed.
- **(B)** Deny with "daemon still building" instead of failing open.
- **(C)** Keep failing open, but announce it on every turn and on the status
  line (which now reads "venv building", merged 2790de8eb).

## Evidence

### What init.sh does today, per state

The per-state, per-event map lives in `emit_hook_error` (`init.sh:640` on).

- **Installed project, daemon unreachable (the "standard" state)**: PreToolUse
  is denied unless stdin is the exact recovery command. The gate is at
  `init.sh:686-698`, and it is explicitly switched OFF for every named setup
  state: `CI_ENFORCED`, `REPO_UNCONFIGURED`, `VENV_MISSING`, `NOT_INSTALLED`,
  `VERSION_MISMATCH` (`init.sh:687-692`). The comment at `init.sh:681-682`
  says so in words: "Gated to ONLY the standard case (every named state below
  stays unconditionally fail-open, untouched by MA4)". The deny is encoded at
  `init.sh:1097-1099`, with its own text at `init.sh:1003-1013` ("Hook safety
  handlers are ACTIVE and denying by default until the daemon answers again").
- **Daemon starting**: `ensure_daemon` returns 1 with `_HOOKS_DAEMON_STARTING`
  set (`init.sh:2659-2665`), and PreToolUse is denied with "the daemon is
  starting; retry" (`init.sh:981-989`). The in-hook wait is capped by
  `_HOOKS_DAEMON_START_DEADLINE=15` (`init.sh:1574-1580`), chosen because "A
  PreToolUse hook that reaches the 60 s timeout lets the call run unjudged".
  This is the closest precedent for a transient state, and it is fail-closed.
  `FailOpenBoundaries.md:106-114` records that as deliberate.
- **Venv missing (the build window is a sub-state of this)**: diagnosed at
  `init.sh:2748-2764`. A real clone with a readable version calls
  `_venv_self_heal` (`init.sh:2755`), which runs the clone's
  `scripts/venv_bootstrap.sh hook`, starts ONE detached build under the venv
  build lock and returns at once (`init.sh:2220-2232`). Bootstrap state
  `started` or `running` sets the status text to
  `⏳ HOOKS DAEMON VENV BUILDING - wait, no action needed` (`init.sh:46`,
  `2757-2760`). The response for this state (`init.sh:1066-1077`): Stop and
  SubagentStop BLOCK with `venv_block_reason` (`init.sh:843`, `1072-1074`);
  every other event, PreToolUse included, fails open through
  `_hooks_daemon_fail_open_json` (`init.sh:1076`), which puts `context_msg` in
  `additionalContext` for PreToolUse (`init.sh:447-449`, `489`).
- **What that fail-open answer already says, on every call**: `context_msg`
  for `VENV_MISSING` (`init.sh:845-862`) carries "ALL safety handlers, code
  quality checks, and workflow enforcement are INACTIVE" and, for the
  `started` state, "A BUILD HAS STARTED — nothing to do but wait ... Build log:
  ... When it finishes, the next hook starts the daemon on its own"
  (`init.sh:793-800`); for `running`, the pid and elapsed count
  (`init.sh:801-813`). `UserPromptSubmit` is in the context-event list
  (`init.sh:449`), so every user turn gets it too. The Stop block reason adds
  " - a venv build is running in the background" (`init.sh:799`, `812`).
- **Not provisioned**: a separate answer per event (`init.sh:665-671`,
  `_hooks_daemon_emit_needs_provision`), with the provision command the one
  exempt PreToolUse call (`init.sh:378-382`, `496-497`, `610`). The status
  text is at `init.sh:2408`.

So, concretely: the build window is already announced on every hook event and
on the status line. The one thing it is not is judged.

### FailOpenBoundaries.md

- The class: "The guarded action proceeds because the guard could not reach a
  verdict" (`CLAUDE/Security/FailOpenBoundaries.md:9`). What makes it a
  security class is that "the party the guard constrains can induce the
  condition" (`:17-20`).
- "No instance is fixed. Converting any of these to fail-closed changes
  behaviour in every installing project ... so the fix is owner-gated"
  (`:100-104`).
- A start under way denies, "it fails closed, and the operator sees why"
  (`:106-114`). The counter-example explains WHY a gate may fail closed: "the
  rephrase always exists" (`:90-98`).

The build window is not caller-induced: it is produced by cloning, not by
anything the agent types, and the agent cannot shorten or lengthen it.

### Threat-model rulings

- `CLAUDE/ARCHITECTURE.md:788-795`: "The daemon helps an agent that makes
  mistakes. It does not defend against a hostile one ... the hook layer fails
  open for tool calls in some setup states (for example the CI passthrough, and
  a project that is not installed). On an installed project an unreachable
  daemon does NOT open the gate for tool calls". The build window sits in the
  "setup state" family by the code's own classification (`init.sh:681-692`).
- What is protected is the outcome: "uncommitted work, protected file
  contents, what reaches GitHub, repository history, the system Python"
  (`ARCHITECTURE.md:809-811`). "False positives cost real work. A guard that
  denies ordinary commands ... fails the agents it exists to help"
  (`:847-850`).
- Owner ruling A1 (`00483/OWNER-RULINGS-261005.md:12-13`): "Fail-closed is too
  problematic. Deliberate evasion is out of scope. I'm not sure any kind of
  fail-closed is really sensible." Read by the coordinator as: deny only on a
  positive finding; a cap, deadline or unreadable input allows with a loud
  advisory (`:15-17`). `00483/PLAN.md:255` records the same.
- `00474/OWNER-RULINGS-261011.md:26` (N333): "Hooks daemon should not be
  trying to fight Claude Code".
- Plan 00503 (`00503/PLAN.md:23-26`): the owner removed the upgrade owner
  approval on 2026-10-11 because "It adds busy work and no safety ... The
  project's threat model is careless agents, not hostile ones, so a guard
  against forging the approval defends against nothing in scope."

### Claude Code hook timeout behaviour

Vendored at `remote-docs/code.claude.com/docs/en/hooks.md` (a vendored copy,
licence unreviewed, cited by line only):

- `:872`: a `command` hook that reaches its `timeout` is cancelled and its
  output discarded, "so on most events a timed-out hook renders no decision".
- `:876`: on PreToolUse, "A timed-out `command` ... hook doesn't block the tool
  call. The call continues through the normal permission flow, so don't count
  on a stalled hook to act as a gate."
- `:3329` repeats it: "On PreToolUse ... a timed-out command hook lets the tool
  call continue."

This project's PreToolUse hook has `"timeout": 60` (`.claude/settings.json:21`).
The project has already been bitten: "150 of those ran the hook past its 60 s
timeout, and PreToolUse failed open" (`init.sh:1692-1694`), and the start
deadline was lowered for that reason (`init.sh:1574-1580`).

## Options weighed

### (A) Wait on the build lock up to a bound, then proceed

- **Consistency**: there is a precedent for an in-hook wait, but it is the
  start deadline (`init.sh:1580`) against a daemon start, which is far shorter
  than a `uv sync`.
- **Risk**: none removed. Any bound that fits inside the hook timeout is
  shorter than the build, so the wait expires and the call proceeds unjudged
  anyway. A bound past the hook timeout is worse: Claude Code cancels the
  hook, discards its output, and the call proceeds with NO advisory at all
  (`hooks.md:872`, `:876`), which is the one outcome worse than the status
  quo.
- **Friction**: every tool call during the window (each hook is a fresh
  process, so nothing remembers the last wait) stalls for the full bound. A
  first session's opening becomes a sequence of hangs with nothing on screen
  but the status line.
- **Timeout risk**: the whole point of the option is to spend the hook budget
  waiting, so it is the option most exposed to the documented silent
  fail-open.
- **Size**: small to write, but it needs a lock probe
  (`venv_lock_is_held`, `scripts/install/venv.sh`) in the hook's hot path and
  a new deadline constant with tests.

A is dominated: it adds latency and buys no judgement. Ruled out.

### (B) Deny with "daemon still building"

- **Consistency**: matches the STARTING precedent (`init.sh:981-989`) and the
  "installed project, daemon unreachable denies" sentence in
  `ARCHITECTURE.md:791-793`. It is the strongest argument for B. But the code
  classifies `VENV_MISSING` with the setup states that stay fail-open
  (`init.sh:681-692`), and the STARTING deny is honest only because its
  retry advice is true for a start. For a venv build it is not: the agent
  would be told to retry a call that stays denied until `uv sync` finishes.
- **Risk during the window**: the window is not caller-induced, and a fresh
  clone has no uncommitted work to lose. The protected outcomes
  (`ARCHITECTURE.md:809`) are reachable in principle (an agent could push, or
  `cat` a protected file) but a careless agent's opening moves in a fresh
  clone are orientation: reads, `git status`, `ls`. The expected loss is low,
  and the owner's A1 ruling says plainly that fail-closed on a non-finding is
  "too problematic".
- **Friction**: high, and it has a wedge shape the project has already met.
  With every PreToolUse denied, the agent cannot even wait: `sleep` is a Bash
  tool call and is denied like the rest. Meanwhile Stop and SubagentStop
  BLOCK in this state (`init.sh:1072-1074`), so an unattended agent that
  gives up cannot stop either. The result is deny, text, stop blocked, deny,
  for the whole build, burning turns. This is exactly the loop
  `init.sh:971-978` (R4-MA2) was written to avoid. Fixing it needs a `sleep`
  carve-out, which is new attack surface for no gain, or a change to the Stop
  behaviour, which widens the change.
- **The state is not always transient**: `failed`, `refused`, `disabled`,
  `error` and the orphan-venv case (`init.sh:814-841`, `2765-2768`) have no
  build coming. B must therefore be scoped to `started`/`running` only, or it
  becomes a permanent fail-closed on states the owner's A1 ruling says must
  not be, and a state the status text itself calls "no action needed".
- **Timeout risk**: none; the deny is immediate.
- **Size**: moderate. The gate at `init.sh:687-692` gains a bootstrap-state
  condition, a new deny text is added beside `init.sh:981-989`, both encoders
  (`jq` at `1066-1077` and python at `1149-1157`) change, and the
  `test_init_sh_pretooluse_fail_closed.py` family grows. Plus whatever
  resolves the wedge.

B is consistent with one precedent and inconsistent with the owner's three
most recent rulings (A1, N333, 00503), and it makes a fresh clone's first
session worse in a way the project has already documented as a defect.

### (C) Keep failing open, announce on every turn and on the status line

- **Consistency**: this IS the current policy for every setup state
  (`init.sh:681-692`, `1066-1077`), and it is the direction of A1
  ("allow with a loud advisory"), N333 and 00503.
- **Risk**: the same low, bounded, non-caller-induced exposure as today. The
  trace is in-band, which is the column `FailOpenBoundaries.md:59-62` says is
  the one that pays: every PreToolUse carries "ALL safety handlers ...
  INACTIVE" plus the build state (`init.sh:793-813`, `855`), every prompt
  gets it (`init.sh:449`), the status line names it (`init.sh:46`), and the
  Stop block keeps the session from ending as if nothing happened.
- **Friction**: none beyond the build itself. Work proceeds.
- **Timeout risk**: none.
- **Size**: the announcement half is ALREADY MERGED. What is missing is one
  sentence of guidance, since the message says what is happening but not what
  the agent should refrain from meanwhile.

### A combination or a better option

A "deny only the destructive subset during the window" variant was considered:
it means re-implementing guard logic in bash, in the hot path, without the
daemon, and is rejected on size alone. A "wait, then deny" variant inherits
A's latency and B's wedge.

## Ruling

**C is the clear winner.** PreToolUse keeps failing open during the build
window, as it does for every setup state, and the window is announced on
every hook event and on the status line. The evidence makes the choice:

1. The owner has ruled three times, most recently on 2026-10-11, against a
   gate that denies on no finding (A1, N333, 00503). B is such a gate, on a
   window the agent did not cause and cannot shorten.
2. A cannot work: the build outlasts any bound the hook budget permits, and a
   longer bound silently removes even the advisory (`hooks.md:876`).
3. The one defect the task names, "every safety handler was inactive, and
   nothing showed the owner it was happening" (`PLAN.md:64-66`), is answered
   by Phases 1-2: the status line now says so, and the per-call context
   already did.

One refinement is ruled in with C, because the current message tells the
agent what is happening but not how to behave: the `started` and `running`
remedies (`init.sh:793-813`) gain a short behavioural line, in the measured
register `init.sh:951-953` asks for. Something like: "Until the status line
clears, keep to reads and ordinary edits. Do not commit, push, delete branches
or touch protected files meanwhile: no guard is judging these calls." This
speaks to the careless agent, which is the one the daemon exists for, and
costs a few lines.

This is a coordinator ruling. The owner may reverse it; the reversal cost is
below.

## Implementation outline

Small. One behavioural sentence, one test, two doc lines.

- `init.sh:793-800` (`started`) and `init.sh:801-813` (`running`): append the
  behavioural line to `_hd_venv_missing_remedy`. Keep it short; the message is
  repeated on every event.
- `tests/integration/test_init_sh_status_down_text.py` (the Phase 2 test
  file): add a case that drives `ensure_daemon` into the `started` state and
  asserts the PreToolUse fail-open `additionalContext` carries the new line,
  and that the response is still an allow (no `permissionDecision: deny`), so
  the policy itself is pinned rather than inferred from the gate at
  `init.sh:687-692`.
- `CLAUDE/Security/FailOpenBoundaries.md`: one paragraph after "The CI
  passthrough does not cover a start under way" (`:106-118`) recording that
  the venv build window is a declared fail-open, not caller-induced, with its
  in-band trace (per-call context, status line, Stop block), and citing this
  ruling. If `scripts/qa/fail-open-boundaries.yaml` already carries a row for
  the `VENV_MISSING` branch, point it at this ruling; if not, add one, since
  the inventory's rule is that every fail-open has a row (`:57-62`).
- `CLAUDE/ARCHITECTURE.md:790-791`: add "a venv build under way" to the
  example setup states, so the threat-model section names it.
- `PLAN.md` Task 3.2: mark decided (coordinator, Fable-assisted), link here.

No change to the gate at `init.sh:687-692`, to either encoder, or to the Stop
behaviour.

## Reversal cost

If the owner prefers B: the gate at `init.sh:687-692` drops the
`VENV_MISSING != true` condition when `_HOOKS_DAEMON_BOOTSTRAP_STATE` is
`started` or `running`; a deny text is added beside `init.sh:981-989` naming
the build log and an honest wait; the `jq` and python encoders at
`init.sh:1066-1077` and `:1149-1157` route PreToolUse to the deny in that
sub-state only; and the `test_init_sh_pretooluse_fail_closed.py` family gains
the cases. A few dozen lines of shell plus tests. The wedge (deny plus Stop
block, no way to wait) would need its own decision: either a `sleep`
carve-out in `_is_daemon_recovery_command` (`init.sh:240-262`) or a Stop allow
in that sub-state. The behavioural sentence added under C stays useful under
B for the other bootstrap states, so nothing ruled here is thrown away.

If the owner prefers A: not recommended under any reading of the timeout
evidence, but it is a small addition in `ensure_daemon` before `init.sh:2745`,
bounded under the hook timeout, and it composes with C rather than replacing
it.
