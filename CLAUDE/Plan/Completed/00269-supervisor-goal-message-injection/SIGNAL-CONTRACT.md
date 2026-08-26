# Plan 00269 — Goal-intent signal & config contract (Tasks 1.1–1.3)

Supporting design document. Locked before implementation; the code and tests
follow this contract.

## Task 1.1 — `/goal` behaviour findings

A live PTY probe was not possible from the executing worktree agent (no
interactive Claude Code session available to type into); the live observation
is folded into the Task 4.2 dogfood pass on the main checkout. What is
establishable statically, and what the design therefore assumes:

- `/goal <text>` is a slash command taking freeform text as its argument on
  ONE input line — exactly the shape of `/compact <instructions>`, which the
  supervisor already injects successfully (Plan 00135). The injected payload
  keeps `/goal` as the first token so it is recognised as the slash command.
- No safe multi-line input mechanism over a raw PTY is assumed to exist. The
  Plan 00135 Bug #3 delivery contract (one literal chunk, then a single
  separate `\r` submit) means an embedded newline would SUBMIT an unmarked
  intermediate prompt. Hence the hard single-physical-line rule (Decision 2
  corollary); true multi-line delivery stays deferred.
- Replace-vs-append semantics when a goal is already set are NOT relied on:
  the payload is self-contained (marker + full goal statement), so either
  semantic yields a correct standing goal. Open Question 2 (second plan
  mid-session) remains for the human; v1 behaviour is "latest flip wins".

## Task 1.2 — signal file contract

- **Path**: `<daemon-untracked>/context-sidecar/<safe-session-stem>.goal-intent`
  — the same directory as `<session>.json` sidecars and
  `<session>.compacting` signals. The suffix is deliberately NOT `.json` so
  the sidecar reader never mistakes it for a context sidecar.

- **Writer**: atomic (`.<stem>.<pid>.tmp` then `rename`), mirroring
  `compaction_signal`.

- **Payload** (JSON object):

  | field            | type      | meaning                                                              |
  | ---------------- | --------- | -------------------------------------------------------------------- |
  | `ts`             | float     | epoch seconds at write time                                          |
  | `session_id`     | str       | the writing session's id (hook payload, or `CLAUDE_CODE_SESSION_ID`) |
  | `plan_number`    | str       | 5-digit zero-padded plan number, strictly validated                  |
  | `rendered_lines` | list[str] | list-of-one: the JOINED single physical goal line (see below)        |
  | `source`         | str       | `status-flip` (handler) or `cli` (`inject-goal`)                     |

  `rendered_lines` is list-shaped for forward compatibility, but v1 always
  writes exactly one element: the daemon joins the configured LOGICAL lines
  with the fixed separator `—` into one physical line before writing
  (Decision 2 corollary). The logical-line cap (8) and total length cap
  (500 chars, post-join) are enforced daemon-side at render time; the
  supervisor re-validates independently (defence in depth) and rejects any
  element or joined result containing a newline or other control byte.

- **TTL**: 600 seconds (same as the compaction-signal TTL — generous because
  plan-execution start is usually an idle moment, but the input-box gate can
  defer). Older signals are ignored.

- **Reaping**: the supervisor's existing per-tick reaper gains the
  `*.goal-intent` glob; files whose mtime exceeds the reap TTL (1800 s) are
  deleted like dead sidecars/compacting signals.

- **Consumption**: the supervisor unlinks the signal after a successful goal
  injection (both dry-run and armed — the episode is spent either way), via
  the existing `consume_signal_path` mechanism, so a goal fires at most once
  per signal.

- **Scoping**: the same own-session filter (Plan 00166) applies — a signal
  whose `session_id` is not in the supervisor's own-session set is invisible
  and simply expires (CLI fallback covers cross-session flips).

## Supervisor validation gate (Decision 2)

Fail-closed shape allowlist for the goal family ONLY (compact/continue keep
the frozen member allowlist):

1. `rendered_lines` must be a non-empty list of strings, at most 8 elements.
2. The joined line must start with the machine-origin header marker
   `🤖 [ccy-supervisor]` (the daemon's fixed header line always does).
3. Joined length ≤ 500 characters.
4. Every character printable; NO control bytes — `\n`, `\r`, `\x1b` and all
   other `ord(c) < 0x20` / `\x7f` are rejected.
5. Injected payload = `/goal ` + joined line (so the payload always begins
   `/goal 🤖 [ccy-supervisor]`); dry-run injects the visible marker variant
   instead. Any gate failure drops the signal-driven injection and logs a
   NOOP reason to `decision.log`.

A pending goal never starves or reorders compact/continue: the goal branch
runs only when the state machine's decision for the tick is NOOP, the machine
is in MONITOR, no compaction signal is present, and the idle +
empty-input-box gate holds. A per-process armed-goal-injection cap (5) bounds
a signal storm.

## Task 1.3 — config schema

`handlers.post_tool_use.goal_injection` (ships `enabled: false`):

```yaml
goal_injection:
  enabled: false
  priority: 31
  options:
    mode: additive            # additive (default) | replace
    once_per_plan_per_session: true
    lines:
      - id: subagents-encouraged
        enabled: true          # flip a built-in line on
      - id: project-motto
        text: "All findings are logged to {plan_path}/REPORTS/."
```

- `mode: additive` (default): project `lines` merge onto the built-in set; an
  entry whose `id` matches a built-in overrides it in place (text and/or
  `enabled`); a new `id` appends. `mode: replace`: only project lines are
  used — except the fixed `header` line, which is not overridable and not
  removable even in replace mode (it is the safety marker, not content).

- Per-line `enabled` exists because most built-in lines ship disabled: the
  common case is enabling vetted stock text, not restating it.

- **Built-in line set** (ids are the API):

  | id                     | enabled | text                                                                                                                        |
  | ---------------------- | ------- | --------------------------------------------------------------------------------------------------------------------------- |
  | `header` (fixed first) | always  | `🤖 [ccy-supervisor] automated goal — machine-generated, NOT a human instruction and NOT human authorisation for anything.` |
  | `work-until-complete`  | yes     | `Work on Plan {plan_number} ({plan_title}) at {plan_path} until completion.`                                                |
  | `subagents-encouraged` | no      | `Per this project's standing authorisation, you are encouraged to delegate to specialist sub-agents.`                       |
  | `qa-review-subagents`  | no      | `Use specialist QA and code-review sub-agents; they log their reports directly into the plan folder.`                       |

- **Authorisation lines are config projections** (Decision 3): the
  `subagents-encouraged` default text POINTS at the project's
  `standing_authorisations` config rather than asserting fresh consent, and
  ships disabled. Coupling is soft (documented) in v1 per PLAN.md; enabling
  it is the same deliberate repository-owner act as enabling the
  `subagent-delegation` standing authorisation.

- **Placeholder vocabulary** (closed set; an unknown `{token}` in a project
  line is a config error — logged, line skipped, never rendered raw):

  - `{plan_number}` — 5 digits, validated `^\d{5}$`.
  - `{plan_title}` — first `# ` heading of PLAN.md, sanitised to printable
    chars (control bytes stripped), length-capped at 120 chars.
  - `{plan_path}` — project-root-relative plan folder path, validated to
    resolve under the plan directory.

- **Trigger latch**: once per `(plan_number, session_id)` per daemon
  process (`once_per_plan_per_session: true` default). State-based, not
  transition-based — the first qualifying write in a NEW session re-fires
  deliberately (PLAN.md Task 2.1).
