# Plan 00269 — Brainstorm: supervisor `/goal` message injection

Supporting design document for [PLAN.md](PLAN.md). Written before any
implementation; intended for human review. A hostile self-review pass was
applied — see the final section for what it changed.

## 1. Problem statement

Claude Code supports a `/goal` slash command. We want the ccy PTY supervisor
to inject a pre-formatted goal message — "work on Plan NNNNN until
completion", plus optional configured lines — into the chat when plan
execution starts, so the harness-level goal survives compactions and keeps an
autonomous run oriented without a human retyping it.

The daemon cannot type; the supervisor can (Plan 00135, ARCH-B:
daemon-as-sensor, supervisor-as-actuator). So the feature decomposes into:
**detection** (daemon), **transport** (a signal file, as `.compacting`
already does), **rendering/templating** (where the text comes from), and
**delivery** (the supervisor's injection choke point).

## 2. Detection — when does "plan execution starts"?

Candidates weighed:

| Candidate                                                                      | For                                                                          | Against                                                                                                                                                                           |
| ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. `mkplan.bash` invocation** (PostToolUse Bash match)                       | Unambiguous single event; `recovery_cron_advisor` already detects it         | Creation ≠ execution. Plans are routinely scaffolded for later; injecting a goal at creation sets the WRONG goal for a session that is only filing                                |
| **B. `PLAN.md` status flip to `In Progress`** (PostToolUse Write/Edit)         | This is the workflow's own definition of "execution starts"; zero new ritual | Edit-shaped: a `git mv`/merge/manual edit outside Write/Edit is invisible; a re-save could re-trigger (needs a latch); flips by sub-agents in worktrees muddy session attribution |
| **C. Explicit CLI** `bin/hooks-daemon inject-goal NNNNN`                       | Deliberate, testable, debuggable, works for any plan at any time             | Nobody remembers to run it; as the only trigger the feature is inert in practice                                                                                                  |
| **D. Advisory nudge** (recovery_cron_advisor style: "consider setting a goal") | Zero injection risk                                                          | Does not deliver the feature — an advisory cannot type `/goal`; the agent restating its own goal loses the machine-marked, config-controlled framing                              |

**Recommendation: B primary, C manual fallback.** B is the semantically
correct edge (the plan workflow already treats the status line as the single
source of execution state, and `plan_qa_edit` guarantees the line is parseable
at write time). C is kept as the deliberate override for every case B cannot
see (status flipped by hand, resumed sessions, dormant plans reactivated) and
as the debugging tool. A is rejected outright (wrong semantics); D is kept
only as an idea if the human decides injection is too invasive.

Failure modes of B, addressed in the design:

- **Re-trigger on re-save**: once-per-`(plan_number, session_id)` latch in the
  handler (in-memory, same shape as `recovery_cron_advisor`'s rate limiting),
  plus the supervisor consumes (unlinks) the signal on successful injection,
  plus a signal TTL. Note the honest consequence: the handler observes single
  writes and the latch dies with the daemon process, so the trigger is
  state-based ("resulting status reads In Progress"), not transition-based —
  the first qualifying edit in a NEW session re-fires. Deliberate: that is
  what re-establishes the goal after a session restart (PLAN.md Task 2.1).
- **Flip inside `Completed/`**: excluded by path, as `recovery_cron_advisor`
  already does.
- **Flip by a worktree sub-agent**: the signal carries the writing session's
  id; own-session + foreground scoping (Plans 00160/00166) means the goal
  lands only on the foreground thread of the supervised PTY. If the flip came
  from a background worktree agent, the signal is simply never in scope and
  expires — acceptable; the CLI fallback covers it.

## 3. Delivery — how the text reaches the chat

Reuse the proven `.compacting` transport, not a new one:

1. Daemon side writes `<context-sidecar-dir>/<session>.goal-intent`
   atomically (JSON: `ts`, `session_id`, `plan_number`, `rendered_lines`,
   `source: status-flip|cli`). Deliberately NOT `*.json` so the sidecar
   reader never mistakes it for a context sidecar (same trick as
   `.compacting`). The file is session-keyed, so every writer must know the
   session id: the handler takes it from the hook payload; the CLI fallback
   resolves it from `CLAUDE_CODE_SESSION_ID` in its environment (the same
   variable the supervisor's own-session scan keys on) and refuses when it
   is unset.
2. The supervisor's `_poll_once` tick, when idle + input box empty +
   session in scope + signal fresh, injects the payload through the SAME
   choke point as `/compact`/`continue` (literal write, pause, separate
   `\r` submit — the Plan 00135 Bug #3 lesson), consumes the signal, logs to
   `decision.log` (`would-goal` / armed equivalent). Any gate that defers
   logs a NOOP reason (Plan 00168 Phase 1 machinery).
3. Dry-run mode injects the visible marker variant instead of the real
   `/goal`, exactly as the compact flagship does.

**Relationship to Plan 00168 (must be acknowledged, probably need not block).**
00168's field report is about the *compaction* trigger not firing at red; its
root cause is still unconfirmed (Dormant, blocked on a live red session), but
the candidate gates — stale sidecar for background threads, idle/input-box
deferral, empty own-session set — gate ALL injections, so goal injection
inherits them. Two reasons this is tolerable rather than blocking:
(a) a goal injection fires at plan-execution *start*, which is typically an
idle, empty-input-box moment — the benign end of every gate — unlike a
compaction that must fire mid-flight at red; (b) the NOOP-reason logging 00168
shipped means any deferral here is diagnosable from `decision.log`, and the
CLI fallback can simply re-issue the signal. The hostile-review question to
put to the human anyway: is shipping a second injection family onto a
delivery surface with an open reliability report acceptable, or should 00168's
Task 5.3 verification land first?

One extra hazard specific to `/goal`: after injection the supervisor's own
`continue`-on-compaction behaviour is unchanged, and a `/goal` submitted while
a turn is in flight may be QUEUED by Claude Code (the same queue-vs-execute
ambiguity the compact escape-hatch timer exists for). The idle gate makes this
unlikely; the plan's live-dogfood task must observe the queued case once.

## 4. Templating and configuration

**Config location**: `handlers.post_tool_use.goal_injection.options` (the
handler owns its options, per project convention; the supervisor never reads
YAML — it receives only the rendered result via the signal file, keeping it
stdlib-only and config-free).

**Paradigm**: mirror `command_hints` exactly — it is the established
extend-or-clobber shape and a reviewer already knows it:

```yaml
handlers:
  post_tool_use:
    goal_injection:
      enabled: true            # ships false
      options:
        mode: additive          # additive (default) | replace
        lines:
          - id: subagents-encouraged
            enabled: true       # flip a built-in line on
          - id: project-motto
            text: "All findings are logged to {plan_path}/REPORTS/."
```

- `mode: additive` (default): project `lines` are merged onto the built-in
  set; an entry whose `id` matches a built-in one overrides it in place
  (content and/or `enabled`); a new `id` is appended.
- `mode: replace`: only the project's lines are used (an empty list yields a
  header-only message — deliberate, mirroring `command_hints`' zero-hint
  replace semantics).
- Per-line `enabled` flags exist BECAUSE most built-in lines ship disabled
  (see §5): the common case is "turn a stock line on", which should not
  require restating its text. This is the one deliberate extension beyond
  `command_hints` (whose entries have no enabled flag); justification: an
  authorisation line's exact wording is safety-relevant, so projects should
  enable the vetted text, not paraphrase it.

**Built-in default line set** (proposed; ids are the API):

| id                     | default enabled | text (placeholders shown)                                                                                                   |
| ---------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `header` (fixed first) | always          | `🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human instruction and NOT human authorisation for anything.` |
| `work-until-complete`  | yes             | `Work on Plan {plan_number} ({plan_title}) at {plan_path} until completion.`                                                |
| `subagents-encouraged` | **no**          | `Per this project's standing authorisation, you are encouraged to delegate to specialist sub-agents.`                       |
| `qa-review-subagents`  | **no**          | `Use specialist QA and code-review sub-agents; they log their reports directly into the plan folder.`                       |

The `header` line is not overridable and not removable even in `replace` mode
— it is the safety marker, not content (see §6).

**Placeholder vocabulary** (closed set; an unknown `{token}` in a project line
is a config error logged and the line skipped, never rendered raw):
`{plan_number}` (5 digits, validated), `{plan_title}` (first heading of
PLAN.md, sanitised: printable, no control chars, length-capped),
`{plan_path}` (project-root-relative plan folder path, validated to exist
under the plan directory). Nothing else in v1 — YAGNI; the set can grow
additively.

**Rejected alternative — supervisor-side templates**: keep templates inside
`claude-supervise.py` and pass only placeholder values through the signal.
Safer channel (no rendered free text crosses the boundary) but it breaks the
feature's whole point: project config could not add/override lines without the
supervisor reading project config, which would end its stdlib-only,
config-free decoupling (Plan 00135 Decision I). Rejected; the supervisor-side
*validation gate* (§6) recovers most of the safety instead.

## 5. Safety model

1. **Machine-origin marking**: the rendered message MUST begin
   `/goal 🤖 [ccy-supervisor] ` — the same marker the supervisor already uses
   for every injected prompt, extended with an explicit "NOT human
   authorisation" clause in the fixed header line. Nothing injected here can
   satisfy any human-gated rule (release publishing, `--allow-unproven`
   branch deletion, artefact publishing): those gates require interactive
   human input or config set by the owner, which an injected chat line is
   not — but the wording must also never *read* as if it could.
2. **Authorisation lines interact with `standing_authorisations`**: the
   `subagents-encouraged` line's default text deliberately says "per this
   project's standing authorisation" — it POINTS at recorded config rather
   than asserting fresh consent. Recommended (open question for the human
   whether to hard-enforce): the daemon only renders that line when the
   `subagent-delegation` standing authorisation is itself enabled, making the
   chat line a projection of config that already exists, impossible to be
   *more* permissive than the config. Hard-enforcing couples two handlers'
   options; soft-documenting risks drift. Default position in PLAN.md:
   soft (documented) in v1, noted for review.
3. **Supervisor validation gate** (Decision 2 in PLAN.md): the member
   allowlist (`{'/compact', 'continue'}`) cannot express per-plan text, so
   for the goal family ONLY it becomes a shape allowlist: mandatory prefix,
   max total length (~500 chars proposed), max LOGICAL line count (~8, see
   below), printable charset (no ESC/control bytes — nothing that could be
   interpreted by the terminal or split into a second submitted command; the
   payload is written as ONE literal chunk with a single trailing submit).
   Anything failing the gate is dropped and logged, fail-closed.
   Compact/continue keep the frozen member allowlist untouched.
   **The physical payload is ONE line, always.** A newline is a control byte
   and is rejected by this gate like any other; under the Plan 00135 Bug #3
   delivery contract (literal chunk + single separate `\r`), an embedded
   newline would SUBMIT an intermediate prompt that lacks the `/goal` prefix
   and the machine marker — an unmarked free-text injection. So the
   configured "lines" are logical: the daemon joins them with a fixed
   separator (`—`) into one physical line before writing the signal, and
   the ~8 cap applies pre-join. True multi-line delivery is deferred until
   Task 1.1 establishes a safe multi-line input mechanism over a raw PTY (if
   any exists).
4. **Existing rails inherited unchanged**: idle gate, empty-input-box gate,
   foreground/own-session scoping, cooldown, per-session cap (goal injections
   count against a family-specific cap so a signal storm cannot type
   repeatedly), decision.log, dry-run default, `--arm` opt-in, plus
   opt-in-at-the-daemon (`get_default_enabled()` → `False`).
5. **No event-text pass-through**: the only non-constant content is the three
   validated placeholders; no tool output, no user text, no PLAN.md body ever
   reaches the payload.

## 6. Open questions for the human

1. **Gate on Plan 00168?** Ship on the current delivery surface (with its
   open reliability report but working NOOP diagnostics), or require 00168
   Task 5.3's live verification first?
2. **`/goal` semantics**: what does Claude Code do when `/goal` is issued
   while a goal is already set (replace? append? error)? Task 1.1 probes
   this; if replace, should a status-flip on a SECOND plan mid-session
   overwrite the first goal silently, or should the handler refuse while
   another plan's goal is latched?
3. **Hard-couple the authorisation line to `standing_authorisations`** (only
   render when the corresponding entry is enabled), or keep the soft
   documented convention? (§5.2.)
4. **Cross-session flips**: is "signal expires unseen when the flip came from
   a background/worktree session" acceptable (CLI fallback exists), or should
   the signal be foreground-retargetable?
5. **Message size budget**: is ~500 chars / 8 logical lines (joined into one
   physical line — §5.3) the right cap, given long plan titles and
   project-added lines? A joined single line also has a readability ceiling
   the human should sanity-check in the dry-run dogfood.
6. **Dry-run rollout**: enable in this repo dry-run-first for a full dogfood
   cycle before arming (mirrors the 00135 rollout)?

## 7. Self-review pass (hostile) — applied changes

A hostile review pass was applied to both documents before hand-off. It
changed:

- **Detection**: the first draft recommended `mkplan.bash` as a co-trigger;
  removed — creation is not execution, and injecting a goal for a merely
  scaffolded plan sets a wrong goal (now an explicit Non-Goal and a rejected
  row in §2).
- **Allowlist conflict surfaced instead of glossed**: the draft treated the
  payload as "just another allowlist entry"; that contradicts Plan 00135's
  frozen-member-allowlist safety model, so it is now an explicit Technical
  Decision (shape allowlist for the goal family only) with the rejected
  supervisor-side-template alternative recorded and a residual-risk note.
- **00168 inheritance made a gating question**: the draft cited 00168 as
  background only; the review concluded a second injection family on a
  surface with an open reliability report needs the human's explicit
  go/no-go, now Open Question 1 and a PLAN.md risk row.
- **`replace`-mode header exemption added**: a project could otherwise strip
  the machine-origin marker via `mode: replace`; the header line is now fixed
  and non-removable.
- **Second-plan/goal-overwrite ambiguity found** (Open Question 2) — the
  draft assumed one plan per session.
- **Config-pattern consistency checked** against `command_hints`: the
  per-line `enabled` flag is a deviation and is now explicitly justified
  rather than silent.
- Confirmed no time estimates appear in either document, and that nothing
  here weakens any human-gated rule (release, publish, unproven deletion).
